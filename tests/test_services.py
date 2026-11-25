"""Offline conformance checks for synthetic effects, timing and recovery contracts."""
import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from src.clock import VirtualClock
from src.contracts import IntentKeyGuard, KeyContract
from src.faults import Fault, Verification
from src.ledger import ExecutionLedger
from src.services import CREDENTIALS, WORK_ORDERS, ServiceEnvironment
from src.services.domains import DOMAINS

ROOT = Path(__file__).resolve().parents[1]
PAYLOADS = {'work_order': {'description': 'Repair synthetic test hatch'},
            'credential': {'subject_id': 'synthetic-subject-001', 'scope': 'synthetic-test-room'}}


def arguments(domain='work_order', key=None, intent='intent-001'):
    value = {'intent_id': intent, **PAYLOADS[domain]}
    if key is not None:
        value['idempotency_key'] = key
    return value


def write(env, args=None):
    return env.call(env.public_contract()['write_tool'], args or arguments())


def lookup(env, intent='intent-001'):
    return env.call('lookup', {'intent_id': intent})


def wait(env, ms):
    return env.call('wait', {'duration_ms': ms})



def expected_trace(row):
    """Full public trace from declared fixture values, independent of the service code."""
    domain = row['domain']
    args = arguments(domain, 'original-key' if row['keyed'] else None)
    tool = 'submit_work_order' if domain == 'work_order' else 'issue_credential'
    receipt = {'effect_id': ('WO' if domain == 'work_order' else 'CRED') + '-000001',
               'intent_id': 'intent-001', 'payload': PAYLOADS[domain]}
    if row['first_status'] == 'timeout':
        first = {'status': 'timeout', 'message': 'Acknowledgement unavailable; execution outcome unknown'}
    elif row['first_status'] == 'partial_response':
        first = {'status': 'partial_response', 'raw': '{"status":"ok","effect":'}
    elif row['first_status'] == 'rejected':
        first = {'status': 'rejected', 'committed': False, 'terminal': True}
    else:
        first = {'status': 'ok', 'effect': receipt, 'replayed': False}
    def read(now):
        if row['verification'] == 'none':
            return {'status': 'unavailable', 'message': 'No verification path is available'}
        n = row['first_lookup_effects'] if now == 0 else row['lookup_effects_at_4000']
        result = {'status': 'ok', 'effects': [receipt] if n else [],
                  'authoritative': row['verification'] == 'authoritative',
                  'as_of_ms': now - (3000 if row['verification'] == 'stale' else 0)}
        if row['verification'] == 'authoritative':
            pending = row['initial_pending'] if now == 0 else 0
            result.update(terminal=not pending, pending_count=pending,
                          execution_state='pending' if pending else ('committed' if n else 'not_executed'))
        return result
    return [{'tool': tool, 'arguments': args, 'observed_at_ms': 0, 'response': first},
            {'tool': 'lookup', 'arguments': {'intent_id': 'intent-001'}, 'observed_at_ms': 0, 'response': read(0)},
            {'tool': 'wait', 'arguments': {'duration_ms': 4000}, 'observed_at_ms': 4000,
             'response': {'status': 'ok', 'now_ms': 4000}},
            {'tool': 'lookup', 'arguments': {'intent_id': 'intent-001'}, 'observed_at_ms': 4000, 'response': read(4000)}]


class ClockLedgerTests(unittest.TestCase):
    def test_inclusive_boundary_and_stable_order(self):
        clock = VirtualClock()
        out = []
        clock.schedule_at(10, lambda: out.append(('a', clock.now_ms)))
        clock.schedule_at(10, lambda: out.append(('b', clock.now_ms)))
        clock.advance(9)
        self.assertEqual(out, [])
        clock.advance(1)
        self.assertEqual(out, [('a', 10), ('b', 10)])
        self.assertEqual(clock.now_ms, 10)

    def test_due_callback_can_schedule_same_boundary(self):
        clock = VirtualClock()
        out = []
        def first():
            out.append('a')
            clock.schedule_at(10, lambda: out.append('c'))
        clock.schedule_at(10, first)
        clock.schedule_at(10, lambda: out.append('b'))
        clock.settle()
        self.assertEqual(out, ['a', 'b', 'c'])
        self.assertEqual(clock.now_ms, 10)

    def test_invalid_time_never_moves_clock(self):
        clock = VirtualClock()
        for invalid in (-1, True, 1.5, '3', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                clock.advance(invalid)
        clock.advance(2)
        with self.assertRaises(ValueError):
            clock.schedule_at(1, lambda: None)
        self.assertEqual(clock.now_ms, 2)

    def test_ledger_append_only_and_detached_payload(self):
        ledger = ExecutionLedger()
        payload = {'description': 'Synthetic fixture'}
        first = ledger.commit('r1', 'work_order', 'WO', 'i1', payload, 0, 3)
        payload['description'] = 'mutated caller input'
        self.assertEqual(first.receipt()['payload']['description'], 'Synthetic fixture')
        with self.assertRaises(FrozenInstanceError):
            first.committed_at_ms = 3
        receipt = first.receipt()
        receipt['payload']['description'] = 'mutated receipt'
        self.assertEqual(first.receipt()['payload']['description'], 'Synthetic fixture')
        self.assertIsInstance(ledger.effects, tuple)
        with self.assertRaises(ValueError):
            ledger.commit('r1', 'work_order', 'WO', 'i1', payload, 0, 3)
        ledger.commit('r2', 'work_order', 'WO', 'i1', payload, 4, 3)
        with self.assertRaises(ValueError):
            ledger.commit('r3', 'work_order', 'WO', 'i1', payload, 3, 3)
        self.assertEqual(len(ledger.effects), 2)


class DomainTests(unittest.TestCase):
    def test_scenario_goals_omissions_one_effect_and_duplicates(self):
        scenarios = json.loads((ROOT/'fixtures/service_scenarios.json').read_text())
        self.assertEqual(len(scenarios), 4)
        self.assertEqual({s['domain'] for s in scenarios}, set(DOMAINS))
        for scenario in scenarios:
            with self.subTest(scenario=scenario['id']):
                domain, intent, payload = scenario['domain'], scenario['intent_id'], scenario['payload']
                env = ServiceEnvironment(domain)
                goal = DOMAINS[domain].goal(intent, payload)
                self.assertEqual(goal['required_effects'], 1)
                self.assertEqual(scenario['goal']['required_effects'], 1)
                self.assertTrue(env.private_result(intent, payload)['omitted'])
                args = {'intent_id': intent, **payload}
                write(env, args)
                self.assertTrue(env.private_result(intent, payload)['completed'])
                write(env, args)
                truth = env.private_result(intent, payload)
                self.assertFalse(truth['completed'])
                self.assertEqual(truth['duplicates'], 1)
                self.assertEqual(truth['effect_count'], 2)

    def test_wrong_payload_and_other_intent_are_not_goal_completion(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain)
            wrong = arguments(domain)
            wrong[next(iter(PAYLOADS[domain]))] = 'different-synthetic-payload'
            write(env, wrong)
            truth = env.private_result('intent-001', PAYLOADS[domain])
            self.assertFalse(truth['completed'])
            self.assertTrue(truth['omitted'])
            self.assertEqual(truth['collateral_effects'], 1)
            write(env, arguments(domain, intent='other-intent'))
            self.assertEqual(lookup(env)['effects'][0]['payload'], {k: wrong[k] for k in PAYLOADS[domain]})
            self.assertEqual(len(lookup(env)['effects']), 1)
            self.assertFalse(env.private_result('other-intent', PAYLOADS[domain])['completed'])

    def test_invalid_calls_do_not_consume_initial_fault_or_create_effect(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain, Fault.LOST_ACK)
            tool = DOMAINS[domain].write_tool
            bad = [(tool, {}), (tool, {**arguments(domain), 'private': True}),
                   (tool, {**arguments(domain), 'intent_id': ''}), (tool, []),
                   ('lookup', {'intent_id': []}), ('wait', {'duration_ms': True}),
                   ('wait', {'duration_ms': -1}), ('wait', {'duration_ms': 86400001}),
                   ('escalate', {'intent_id': 'i'}), ([], {}), ('unknown', {})]
            for name, args in bad:
                self.assertEqual(env.call(name, args)['status'], 'invalid_request')
            self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['accepted_requests'], 0)
            self.assertEqual(write(env, arguments(domain))['status'], 'timeout')
            self.assertEqual(env.now_ms, 0)

    def test_credential_receipts_are_identifiers_not_secrets(self):
        env = ServiceEnvironment('credential')
        result = write(env, arguments('credential'))
        self.assertEqual(set(result['effect']), {'effect_id', 'intent_id', 'payload'})
        self.assertTrue(result['effect']['effect_id'].startswith('CRED-'))
        self.assertNotIn('secret', result['effect'])
        self.assertEqual(set(result['effect']['payload']), {'subject_id', 'scope'})


class FaultVerificationTests(unittest.TestCase):
    def test_declared_matrix_all_72_cells_and_expected_traces(self):
        matrix = json.loads((ROOT/'fixtures/service_fault_matrix.json').read_text())
        self.assertEqual(len(matrix), 72)
        self.assertEqual(len({r['id'] for r in matrix}), 72)
        for row in matrix:
            with self.subTest(cell=row['id']):
                domain = row['domain']
                env = ServiceEnvironment(domain, row['fault'], row['verification'],
                        KeyContract(row['keyed']), max_in_flight_ms=4000)
                args = arguments(domain, 'original-key' if row['keyed'] else None)
                first = write(env, args)
                self.assertEqual(first['status'], row['first_status'])
                before = env.private_result('intent-001', PAYLOADS[domain])
                self.assertEqual(before['effect_count'], row['initial_effects'])
                self.assertEqual(before['pending_requests'], row['initial_pending'])
                read = lookup(env)
                self.assertEqual(read['status'], row['first_lookup_status'])
                if 'effects' in read:
                    self.assertEqual(len(read['effects']), row['first_lookup_effects'])
                wait(env, 4000)
                read = lookup(env)
                if 'effects' in read:
                    self.assertEqual(len(read['effects']), row['lookup_effects_at_4000'])
                history = env.evidence
                self.assertEqual(history, expected_trace(row))
                env.settle()
                final = env.private_result('intent-001', PAYLOADS[domain])
                self.assertEqual(final['effect_count'], row['settled_effects'])
                self.assertEqual(final['pending_requests'], 0)
                self.assertEqual(env.evidence, history)

    def test_three_ambiguous_worlds_have_identical_visible_prefixes(self):
        for domain in DOMAINS:
            for verification in Verification:
                for keyed in (False, True):
                    views = []
                    for fault in (Fault.PRECOMMIT_FAILURE, Fault.LOST_ACK, Fault.LATE_COMMIT):
                        env = ServiceEnvironment(domain, fault, verification, KeyContract(keyed), max_in_flight_ms=4000)
                        write(env, arguments(domain, 'original-key' if keyed else None))
                        views.append(json.dumps(env.agent_view(), sort_keys=True).encode())
                    self.assertEqual(views[0], views[1])
                    self.assertEqual(views[1], views[2])

    def test_stale_lookup_does_not_remove_pending_work(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain, Fault.LATE_COMMIT, Verification.STALE)
            write(env, arguments(domain))
            for _ in range(3):
                read = lookup(env)
                self.assertEqual(read['effects'], [])
                self.assertNotIn('terminal', read)
            self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['pending_requests'], 1)
            # Blind retry looks successful now; the original still commits later.
            write(env, arguments(domain))
            env.settle()
            self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['duplicates'], 1)

    def test_authoritative_empty_read_can_still_be_pending(self):
        env = ServiceEnvironment('work_order', Fault.LATE_COMMIT)
        write(env)
        read = lookup(env)
        self.assertEqual(read['effects'], [])
        self.assertFalse(read['terminal'])
        self.assertEqual(read['execution_state'], 'pending')
        wait(env, 3999)
        self.assertEqual(lookup(env)['pending_count'], 1)
        wait(env, 1)
        read = lookup(env)
        self.assertTrue(read['terminal'])
        self.assertEqual(read['execution_state'], 'committed')
        self.assertEqual(len(read['effects']), 1)

    def test_terminal_failure_negative_permits_safe_retry(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain, Fault.PRECOMMIT_FAILURE)
            write(env, arguments(domain))
            read = lookup(env)
            self.assertTrue(read['terminal'])
            self.assertEqual(read['execution_state'], 'not_executed')
            write(env, arguments(domain))
            self.assertTrue(env.private_result('intent-001', PAYLOADS[domain])['completed'])

    def test_stale_visibility_exact_boundary(self):
        env = ServiceEnvironment('work_order', Fault.LATE_COMMIT, Verification.STALE, max_in_flight_ms=4000)
        write(env)
        wait(env, 4000)
        self.assertEqual(lookup(env)['effects'], [])
        self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['effect_count'], 1)
        wait(env, 2999)
        self.assertEqual(lookup(env)['effects'], [])
        wait(env, 1)
        self.assertEqual(len(lookup(env)['effects']), 1)
        self.assertEqual(lookup(env)['as_of_ms'], 4000)

    def test_partial_response_is_malformed_but_execution_is_complete(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain, Fault.PARTIAL_RESPONSE)
            result = write(env, arguments(domain))
            with self.assertRaises(ValueError):
                json.loads(result['raw'])
            self.assertEqual(result['status'], 'partial_response')
            self.assertEqual(len(lookup(env)['effects']), 1)
            self.assertTrue(env.private_result('intent-001', PAYLOADS[domain])['completed'])

    def test_no_verification_does_not_prevent_settlement(self):
        env = ServiceEnvironment('work_order', Fault.LATE_COMMIT, Verification.NONE)
        write(env)
        self.assertNotIn('lookup', env.public_contract()['tools'])
        self.assertEqual(lookup(env)['status'], 'unavailable')
        env.settle()
        self.assertTrue(env.private_result('intent-001', PAYLOADS['work_order'])['completed'])

    def test_deterministic_settlement_never_adds_visible_evidence(self):
        results = []
        for _ in range(2):
            env = ServiceEnvironment('credential', Fault.LATE_COMMIT)
            write(env, arguments('credential'))
            before = env.evidence
            env.settle()
            self.assertEqual(before, env.evidence)
            env.settle()
            results.append((env.private_ledger(), env.private_result('intent-001', PAYLOADS['credential'])))
        self.assertEqual(results[0], results[1])

    def test_public_results_and_histories_are_detached(self):
        env = ServiceEnvironment('credential')
        args = arguments('credential')
        result = write(env, args)
        args['subject_id'] = 'mutated caller'
        result['effect']['payload']['subject_id'] = 'mutated result'
        view = env.agent_view()
        view['evidence'][0]['response']['effect']['payload']['subject_id'] = 'mutated history'
        view['contract']['payload_fields'].append('hidden')
        self.assertEqual(lookup(env)['effects'][0]['payload'], PAYLOADS['credential'])
        self.assertEqual(env.evidence[0]['arguments']['subject_id'], PAYLOADS['credential']['subject_id'])
        self.assertNotIn('hidden', env.public_contract()['payload_fields'])

    def test_no_evaluator_metadata_in_model_view(self):
        env = ServiceEnvironment('work_order', Fault.LATE_COMMIT, Verification.STALE)
        write(env)
        lookup(env)
        visible = json.dumps(env.agent_view(), sort_keys=True)
        for hidden in ('late_commit', 'request_id', 'REQ-', 'committed_at_ms', 'visible_at_ms', 'pending_requests', 'accepted_requests', '_ledger', 'effect_count'):
            self.assertNotIn(hidden, visible)
        env.settle()
        self.assertIn('committed_at_ms', env.private_ledger()[0])

    def test_execution_record_fixture_has_acceptance_schedule_and_completion(self):
        fixtures = json.loads((ROOT/'fixtures/service_ledger_cases.json').read_text())
        self.assertEqual(len(fixtures), 2)
        for case in fixtures:
            domain = case['domain']
            env = ServiceEnvironment(domain, Fault.LATE_COMMIT, Verification.STALE)
            write(env, arguments(domain))
            self.assertEqual(env.private_requests(), case['pending_requests'])
            self.assertEqual(env.private_ledger(), [])
            request_copy = env.private_requests()
            request_copy[0]['payload'].clear()
            env.settle()
            self.assertEqual(env.private_ledger(), case['settled_ledger'])
            self.assertEqual(env.private_requests(), case['settled_requests'])

    def test_invalid_configuration_rejected(self):
        for kwargs in ({'delay_ms': 0}, {'max_in_flight_ms': 3999}, {'max_in_flight_ms': True}):
            with self.assertRaises(ValueError):
                ServiceEnvironment('work_order', Fault.LATE_COMMIT, **kwargs)
        with self.assertRaises(ValueError):
            ServiceEnvironment('work_order', verification='stale', visibility_lag_ms=0)


class KeyRecoveryTests(unittest.TestCase):
    def test_same_key_and_payload_deduplicate_every_committing_fault(self):
        for domain in DOMAINS:
            for fault in (Fault.CLEAR_SUCCESS, Fault.LOST_ACK, Fault.LATE_COMMIT, Fault.PARTIAL_RESPONSE):
                with self.subTest(domain=domain, fault=fault):
                    env = ServiceEnvironment(domain, fault, key_contract=KeyContract(True))
                    args = arguments(domain, 'key-one')
                    write(env, args)
                    write(env, args)
                    env.settle()
                    again = write(env, args)
                    self.assertTrue(again['replayed'])
                    truth = env.private_result('intent-001', PAYLOADS[domain])
                    self.assertEqual(truth['effect_count'], 1)
                    self.assertEqual(truth['accepted_requests'], 1)

    def test_same_key_different_payload_or_intent_rejected(self):
        for domain in DOMAINS:
            for fault in (Fault.LOST_ACK, Fault.LATE_COMMIT):
                env = ServiceEnvironment(domain, fault, key_contract=KeyContract(True))
                original = arguments(domain, 'key-one')
                write(env, original)
                changed = {**original, next(iter(PAYLOADS[domain])): 'different-synthetic-value'}
                self.assertEqual(write(env, changed)['status'], 'key_conflict')
                self.assertEqual(write(env, {**original, 'intent_id': 'other'})['status'], 'key_conflict')
                env.settle()
                self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['effect_count'], 1)

    def test_changed_or_omitted_keys_can_duplicate(self):
        for domain in DOMAINS:
            for key in ('key-two', None):
                env = ServiceEnvironment(domain, Fault.LATE_COMMIT, key_contract=KeyContract(True))
                write(env, arguments(domain, 'key-one'))
                write(env, arguments(domain, key))
                env.settle()
                self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['duplicates'], 1)

    def test_unsupported_key_is_rejected_without_effect(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain, Fault.LOST_ACK)
            self.assertEqual(write(env, arguments(domain, 'assumed-key'))['status'], 'invalid_request')
            self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['accepted_requests'], 0)
            self.assertEqual(write(env, arguments(domain))['status'], 'timeout')

    def test_rejected_attempt_does_not_consume_key(self):
        for fault in (Fault.CLEAR_FAILURE, Fault.PRECOMMIT_FAILURE):
            env = ServiceEnvironment('work_order', fault, key_contract=KeyContract(True))
            args = arguments(key='original-key')
            write(env, args)
            self.assertEqual(write(env, args)['status'], 'ok')
            self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['effect_count'], 1)

    def test_completed_key_expiry_inclusive_boundary(self):
        env = ServiceEnvironment('work_order', key_contract=KeyContract(True, 10))
        args = arguments(key='expiring-key')
        write(env, args)
        wait(env, 9)
        self.assertTrue(write(env, args)['replayed'])
        wait(env, 1)
        self.assertFalse(write(env, args)['replayed'])
        self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['duplicates'], 1)

    def test_pending_reservation_survives_retention_and_negative_reads(self):
        env = ServiceEnvironment('work_order', Fault.LATE_COMMIT, Verification.STALE, KeyContract(True, 10))
        args = arguments(key='short-lived-key')
        write(env, args)
        wait(env, 10)
        self.assertEqual(lookup(env)['effects'], [])
        self.assertEqual(write(env, args)['status'], 'pending')
        env.settle()
        self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['effect_count'], 1)

    def test_key_contract_rejects_false_guarantee_configs(self):
        for args in ((False, 1), (True, 0), (True, -1), (True, True), ('yes', None)):
            with self.assertRaises(ValueError):
                KeyContract(*args)

    def test_guard_pins_keys_and_exposes_actual_dispatch(self):
        for domain in DOMAINS:
            env = ServiceEnvironment(domain, Fault.LATE_COMMIT, key_contract=KeyContract(True))
            guard = IntentKeyGuard(env)
            tool = DOMAINS[domain].write_tool
            guard.call(tool, arguments(domain, 'caller-key-one'))
            guard.call(tool, arguments(domain, 'caller-key-two'))
            self.assertEqual(guard.audit[0]['dispatched_arguments']['idempotency_key'],
                             guard.audit[1]['dispatched_arguments']['idempotency_key'])
            self.assertEqual(guard.audit[1]['requested_arguments']['idempotency_key'], 'caller-key-two')
            env.settle()
            self.assertEqual(env.private_result('intent-001', PAYLOADS[domain])['effect_count'], 1)
            audit = guard.audit
            audit.clear()
            self.assertEqual(len(guard.audit), 2)

    def test_keyless_guard_blocks_pending_and_stale_negatives(self):
        for verification in Verification:
            env = ServiceEnvironment('work_order', Fault.LATE_COMMIT, verification)
            guard = IntentKeyGuard(env)
            tool = WORK_ORDERS.write_tool
            guard.call(tool, arguments())
            guard.call('lookup', {'intent_id': 'intent-001'})
            before = len(env.evidence)
            result = guard.call(tool, arguments())
            self.assertEqual(result['status'], 'blocked')
            self.assertIsNone(guard.audit[-1]['dispatched_arguments'])
            self.assertEqual(len(env.evidence), before)
            env.settle()
            self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['effect_count'], 1)

    def test_keyless_guard_allows_authoritative_terminal_absence(self):
        env = ServiceEnvironment('work_order', Fault.PRECOMMIT_FAILURE)
        guard = IntentKeyGuard(env)
        guard.call(WORK_ORDERS.write_tool, arguments())
        guard.call('lookup', {'intent_id': 'intent-001'})
        self.assertEqual(guard.call(WORK_ORDERS.write_tool, arguments())['status'], 'ok')
        self.assertTrue(env.private_result('intent-001', PAYLOADS['work_order'])['completed'])

    def test_guard_does_not_invent_unsupported_keys_or_change_payload(self):
        env = ServiceEnvironment('work_order')
        guard = IntentKeyGuard(env)
        self.assertEqual(guard.call(WORK_ORDERS.write_tool, arguments(key='invalid'))['status'], 'invalid_request')
        self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['accepted_requests'], 0)
        guard.call(WORK_ORDERS.write_tool, arguments())
        self.assertEqual(guard.call(WORK_ORDERS.write_tool, {**arguments(), 'description': 'different'})['status'], 'blocked')
        self.assertEqual(guard.call('lookup', {'intent_id': []})['status'], 'invalid_request')

    def test_guard_blocks_expired_pin_without_claiming_execution(self):
        env = ServiceEnvironment('work_order', Fault.LOST_ACK, key_contract=KeyContract(True, 10))
        guard = IntentKeyGuard(env)
        guard.call(WORK_ORDERS.write_tool, arguments())
        guard.call('wait', {'duration_ms': 10})
        result = guard.call(WORK_ORDERS.write_tool, arguments())
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['executed'])
        self.assertEqual(env.private_result('intent-001', PAYLOADS['work_order'])['effect_count'], 1)

    def test_escalation_does_not_cancel_or_resolve_pending_effects(self):
        env = ServiceEnvironment('credential', Fault.LATE_COMMIT)
        write(env, arguments('credential'))
        result = env.call('escalate', {'intent_id': 'intent-001', 'reason': 'Cannot establish outcome'})
        self.assertEqual(result['status'], 'escalated')
        self.assertEqual(env.private_result('intent-001', PAYLOADS['credential'])['pending_requests'], 1)
        env.settle()
        truth = env.private_result('intent-001', PAYLOADS['credential'])
        self.assertEqual(truth['effect_count'], 1)
        self.assertEqual(truth['escalations'], 1)


if __name__ == '__main__':
    unittest.main()
