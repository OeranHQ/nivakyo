"""Enforced simulator key guarantees and an observable intent-pinning baseline."""
import copy
import hashlib
from dataclasses import dataclass

from src.clock import milliseconds
from src.ledger import canonical


@dataclass(frozen=True)
class KeyContract:
    enabled: bool = False
    retention_ms: object = None

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('Key support must be a boolean')
        if self.retention_ms is not None:
            milliseconds(self.retention_ms)
            if not self.enabled or self.retention_ms == 0:
                raise ValueError('Retention requires supported keys and a positive duration')

    def public(self):
        return {'mode': 'atomic_same_key' if self.enabled else 'unsupported',
                'scope': 'service/key with identical intent and payload' if self.enabled else None,
                'coalesces_in_flight': self.enabled, 'payload_match_required': self.enabled,
                'retention': ('indefinite' if self.retention_ms is None else 'bounded')
                    if self.enabled else 'not_applicable',
                'retention_ms': self.retention_ms,
                'pending_keys_retained': self.enabled}


class IntentKeyGuard:
    """Uses public guarantees/results only; no evaluator state or pending queue access.

    No-key repeats require observed terminal absence. Supported keys are pinned even
    when a caller asks to change them. Expired pins block conservatively. Decisions
    and actual dispatched arguments remain separate in the audit log.
    """
    def __init__(self, service):
        self._service = service
        contract = service.public_contract()
        self._tool = contract['write_tool']
        self._fields = tuple(contract['payload_fields'])
        self._keys = contract['idempotency']
        self._intents = {}
        self._audit = []

    @property
    def audit(self):
        return copy.deepcopy(self._audit)

    def public_contract(self):
        return self._service.public_contract()

    def call(self, name, arguments):
        requested = copy.deepcopy(arguments)
        dispatched = copy.deepcopy(arguments)
        block = None
        item = None
        valid_write = (name == self._tool and type(arguments) is dict
                       and set(arguments) in (set(self._fields) | {'intent_id'},
                                               set(self._fields) | {'intent_id', 'idempotency_key'})
                       and all(type(v) is str and v.strip() for v in arguments.values()))
        if valid_write:
            identity = arguments['intent_id']
            signature = canonical({k: arguments[k] for k in ('intent_id',) + self._fields})
            item = self._intents.get(identity)
            if item and item['signature'] != signature:
                block = 'Intent was already bound to a different payload'
            elif item and self._keys['mode'] == 'unsupported' and item['state'] != 'absent':
                block = 'Earlier write is not confirmed terminal and effect-free'
            elif item and self._keys['mode'] != 'unsupported' and item['expires_at_ms'] is not None and self._service.now_ms >= item['expires_at_ms']:
                block = 'Pinned key retention window ended; reconcile before further dispatch'
            if not block:
                if item is None:
                    ttl = self._keys['retention_ms']
                    item = {'signature': signature, 'key': 'guard-' + hashlib.sha256(signature.encode()).hexdigest()[:24],
                            'state': 'absent', 'expires_at_ms': None if ttl is None else self._service.now_ms + ttl}
                if self._keys['mode'] != 'unsupported':
                    dispatched['idempotency_key'] = item['key']
                # Unsupported supplied keys are forwarded and rejected, never silently enabled.
        if block:
            result = {'status': 'blocked', 'reason': block, 'executed': False}
        else:
            result = self._service.call(name, dispatched)
            if valid_write and result['status'] in ('ok', 'pending', 'timeout', 'partial_response', 'rejected'):
                item['state'] = 'absent' if result['status'] == 'rejected' else 'unresolved'
                self._intents[arguments['intent_id']] = item
            if name == 'lookup' and type(arguments) is dict and type(arguments.get('intent_id')) is str:
                item = self._intents.get(arguments.get('intent_id'))
                if item and result.get('authoritative') is True and result.get('terminal') is True:
                    item['state'] = 'absent' if not result['effects'] else 'exists'
        self._audit.append({'requested_name': name, 'requested_arguments': requested,
                            'dispatched_arguments': None if block else dispatched,
                            'blocked': bool(block), 'result': copy.deepcopy(result)})
        return copy.deepcopy(result)
