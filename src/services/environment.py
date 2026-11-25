"""Two-domain deterministic service environment, isolated from the legacy MVP loop."""
import copy
import json
from dataclasses import dataclass

from src.clock import VirtualClock, milliseconds
from src.contracts import KeyContract
from src.faults import Fault, Verification, partial_observation, timeout_observation
from src.ledger import ExecutionLedger, canonical
from src.services.domains import DOMAINS


@dataclass
class _Request:
    request_id: str
    intent_id: str
    payload_json: str
    accepted_at_ms: int
    scheduled_completion_at_ms: object = None
    completed_at_ms: object = None
    state: str = 'pending'
    effect: object = None


class ServiceEnvironment:
    def __init__(self, domain, fault=Fault.CLEAR_SUCCESS, verification=Verification.AUTHORITATIVE,
                 key_contract=None, delay_ms=4000, visibility_lag_ms=3000,
                 max_in_flight_ms=None):
        if type(domain) is not str or domain not in DOMAINS:
            raise ValueError('Unknown synthetic domain')
        self._domain = DOMAINS[domain]
        self._fault = Fault(fault)
        self._verification = Verification(verification)
        if key_contract is not None and not isinstance(key_contract, KeyContract):
            raise ValueError('Expected KeyContract')
        self._key_contract = key_contract or KeyContract()
        self._delay_ms = milliseconds(delay_ms)
        if self._delay_ms == 0:
            raise ValueError('Late commits need a positive delay')
        milliseconds(visibility_lag_ms)
        self._lag_ms = visibility_lag_ms if self._verification == Verification.STALE else 0
        if self._verification == Verification.STALE and self._lag_ms == 0:
            raise ValueError('Stale verification needs positive lag')
        if max_in_flight_ms is not None:
            milliseconds(max_in_flight_ms)
            if self._fault == Fault.LATE_COMMIT and max_in_flight_ms < self._delay_ms:
                raise ValueError('Hidden schedule exceeds declared processing guarantee')
        self._bound_ms = max_in_flight_ms
        self._clock = VirtualClock()
        self._ledger = ExecutionLedger()
        self._requests = []
        self._keys = {}
        self._evidence = []
        self._escalations = []

    @property
    def now_ms(self):
        return self._clock.now_ms

    @property
    def evidence(self):
        return copy.deepcopy(self._evidence)

    def public_contract(self):
        """Agent-facing guarantees only: no fault identity or actual pending schedule."""
        return {'contract_version': 'synthetic-service-v1', 'domain': self._domain.name,
                'write_tool': self._domain.write_tool, 'payload_fields': list(self._domain.payload_fields),
                'goal': 'Exactly one authorized effect, with the intended identity and payload',
                'idempotency': self._key_contract.public(),
                'verification': self._verification.value,
                'read_semantics': {
                    Verification.NONE: 'No lookup available',
                    Verification.AUTHORITATIVE: 'Complete fresh intent lookup including pending work; NOT_EXECUTED is terminal and effect-free',
                    Verification.STALE: 'Complete intent snapshot lagging virtual time; empty does not establish current absence or terminality',
                }[self._verification],
                'max_visibility_lag_ms': None if self._verification == Verification.NONE else self._lag_ms,
                'max_in_flight_ms': self._bound_ms,
                'bound_origin': 'attempt_acceptance', 'due_events_before_read': True,
                'effects_reversible': False, 'fault_scope': 'Only the first accepted write may be faulted',
                'tools': [self._domain.write_tool, 'wait', 'escalate'] +
                         ([] if self._verification == Verification.NONE else ['lookup'])}

    def agent_view(self):
        return {'contract': self.public_contract(), 'now_ms': self.now_ms, 'evidence': self.evidence}

    def call(self, name, arguments):
        # Keep malformed input records JSON-safe without leaking arbitrary object reprs.
        try:
            safe_arguments = json.loads(canonical(arguments))
        except (ValueError, TypeError, OverflowError):
            safe_arguments = None
        result = self._dispatch(name, arguments)
        self._evidence.append({'tool': name if type(name) is str else None,
                               'arguments': safe_arguments, 'observed_at_ms': self.now_ms,
                               'response': copy.deepcopy(result)})
        return copy.deepcopy(result)

    def _dispatch(self, name, args):
        invalid = {'status': 'invalid_request', 'error': 'Invalid tool or argument fields'}
        if type(name) is not str or type(args) is not dict:
            return invalid
        if name == self._domain.write_tool:
            expected = {'intent_id'} | set(self._domain.payload_fields)
            if set(args) not in (expected, expected | {'idempotency_key'}):
                return invalid
            if not all(type(v) is str and v.strip() for v in args.values()):
                return invalid
            if 'idempotency_key' in args and not self._key_contract.enabled:
                return {'status': 'invalid_request', 'error': 'Service does not support idempotency keys'}
            return self._write(args)
        if name == 'lookup':
            if set(args) != {'intent_id'} or type(args['intent_id']) is not str or not args['intent_id'].strip():
                return invalid
            return self._lookup(args['intent_id'])
        if name == 'wait':
            if set(args) != {'duration_ms'} or type(args['duration_ms']) is not int or not 0 <= args['duration_ms'] <= 86400000:
                return invalid
            self._clock.advance(args['duration_ms'])
            return {'status': 'ok', 'now_ms': self.now_ms}
        if name == 'escalate':
            if set(args) != {'intent_id', 'reason'} or not all(type(v) is str and v.strip() for v in args.values()):
                return invalid
            self._escalations.append(dict(args))
            return {'status': 'escalated', 'intent_id': args['intent_id'],
                    'message': 'Recorded for synthetic review; execution is not cancelled or resolved'}
        return invalid

    def _commit(self, request):
        if request.state != 'pending':
            raise RuntimeError('Only pending requests can commit')
        request.effect = self._ledger.commit(request.request_id, self._domain.name,
            self._domain.effect_prefix, request.intent_id, json.loads(request.payload_json),
            self.now_ms, self._lag_ms)
        request.state = 'committed'
        request.completed_at_ms = self.now_ms

    def _write(self, args):
        intent_id = args['intent_id']
        payload = {k: args[k] for k in self._domain.payload_fields}
        signature = canonical({'intent_id': intent_id, 'payload': payload})
        key = args.get('idempotency_key')
        if key is not None and key in self._keys:
            original_signature, request, expires_at = self._keys[key]
            # An accepted pending request retains its key reservation through expiry.
            if expires_at is not None and self.now_ms >= expires_at and request.state != 'pending':
                del self._keys[key]
            elif original_signature != signature:
                return {'status': 'key_conflict', 'error': 'Key is bound to another intent or payload'}
            elif request.state == 'pending':
                return {'status': 'pending', 'message': 'Matching request is still in flight'}
            else:
                return {'status': 'ok', 'effect': request.effect.receipt(), 'replayed': True}
        initial = not self._requests
        request = _Request('REQ-%06d' % (len(self._requests) + 1), intent_id, canonical(payload), self.now_ms)
        self._requests.append(request)
        if key is not None:
            ttl = self._key_contract.retention_ms
            self._keys[key] = (signature, request, None if ttl is None else self.now_ms + ttl)
        fault = self._fault if initial else Fault.CLEAR_SUCCESS
        if fault in (Fault.CLEAR_FAILURE, Fault.PRECOMMIT_FAILURE):
            request.state = 'not_executed'
            request.completed_at_ms = self.now_ms
            if key is not None:
                del self._keys[key]  # Rejected, effect-free attempts do not consume the key.
            if fault == Fault.CLEAR_FAILURE:
                return {'status': 'rejected', 'committed': False, 'terminal': True}
            return timeout_observation()
        if fault == Fault.LATE_COMMIT:
            request.scheduled_completion_at_ms = self.now_ms + self._delay_ms
            self._clock.schedule_at(request.scheduled_completion_at_ms, lambda: self._commit(request))
            return timeout_observation()
        self._commit(request)
        if fault == Fault.LOST_ACK:
            return timeout_observation()
        if fault == Fault.PARTIAL_RESPONSE:
            return partial_observation()
        return {'status': 'ok', 'effect': request.effect.receipt(), 'replayed': False}

    def _lookup(self, intent_id):
        if self._verification == Verification.NONE:
            return {'status': 'unavailable', 'message': 'No verification path is available'}
        # Inclusive ordering: process events due exactly at this read time first.
        self._clock.advance(0)
        effects = [e for e in self._ledger.effects if e.intent_id == intent_id]
        if self._verification == Verification.STALE:
            return {'status': 'ok', 'effects': [e.receipt() for e in effects if e.visible_at_ms <= self.now_ms],
                    'authoritative': False, 'as_of_ms': self.now_ms - self._lag_ms}
        pending = sum(r.state == 'pending' and r.intent_id == intent_id for r in self._requests)
        return {'status': 'ok', 'effects': [e.receipt() for e in effects],
                'authoritative': True, 'as_of_ms': self.now_ms, 'terminal': pending == 0,
                'execution_state': 'pending' if pending else ('committed' if effects else 'not_executed'),
                'pending_count': pending}

    def settle(self):
        """Evaluator only. Never adds observations or model decisions."""
        self._clock.settle()

    def private_result(self, intent_id, payload):
        """Evaluator only; explicitly distinguishes current from settled effects."""
        if not self._domain.validate_payload(payload):
            raise ValueError('Invalid goal payload')
        effects = [e for e in self._ledger.effects if e.intent_id == intent_id]
        matched = [e for e in effects if e.payload_json == canonical(payload)]
        pending = sum(r.state == 'pending' for r in self._requests)
        collateral = len(self._ledger.effects) - len(matched)
        return {'fault': self._fault.value, 'effect_count': len(effects),
                'matched_effects': len(matched), 'duplicates': max(0, len(effects) - 1),
                'omitted': len(matched) == 0, 'collateral_effects': collateral,
                'completed': len(matched) == 1 and len(self._ledger.effects) == 1 and pending == 0,
                'settled': pending == 0, 'pending_requests': pending,
                'accepted_requests': len(self._requests), 'escalations': len(self._escalations),
                'now_ms': self.now_ms}

    def private_ledger(self):
        return [e.evaluation_record() for e in self._ledger.effects]

    def private_requests(self):
        """Evaluator-only acceptance, pending schedule and terminal transition records."""
        return [{'request_id': r.request_id, 'intent_id': r.intent_id,
                 'payload': json.loads(r.payload_json), 'state': r.state,
                 'accepted_at_ms': r.accepted_at_ms,
                 'scheduled_completion_at_ms': r.scheduled_completion_at_ms,
                 'completed_at_ms': r.completed_at_ms} for r in self._requests]
