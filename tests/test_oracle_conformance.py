"""Declared-world truth/support, recovery permission and exact scripted controls."""
import json
import unittest
from pathlib import Path

from src.action_scorer import score_action
from src.controls import control_matrix, control_table
from src.epistemic_oracle import Proposition, Uncertainty, assess, assess_report
from src.faults import Fault
from src.metrics import score_episode, summarize
from src.services.domains import DOMAINS
from src.worlds import CompatibleWorlds, Goal, InconsistentEvidence, WorldSpec, ambiguous_worlds

ROOT = Path(__file__).resolve().parents[1]
PAYLOADS = {'work_order': {'description': 'Synthetic oracle test'},
            'credential': {'subject_id': 'synthetic-subject-001', 'scope': 'synthetic-room'}}


def setup_worlds(domain='work_order', actual='lost_ack', **config):
    goal = Goal.create(domain, 'oracle-intent-001', PAYLOADS[domain])
    specs = ambiguous_worlds(domain, **config)
    spec = next(s for s in specs if s.world_id == actual)
    return CompatibleWorlds(goal, specs), spec.instantiate(), spec


def args(worlds, key=None):
    value = {'intent_id': worlds.goal.intent_id, **worlds.goal.payload}
    if worlds.contract['idempotency']['mode'] != 'unsupported':
        value['idempotency_key'] = 'original-key' if key is None else key
    return value


def dispatch(worlds, env, name, arguments, assessments=None):
    if assessments is not None:
        assessments.append(score_action(worlds, name, arguments))
    response = env.call(name, arguments)
    return worlds.observe(name, arguments, response, env.now_ms)


def advance_case(case):
    worlds, env, spec = setup_worlds(actual=case['actual_world'], **case['config'])
    for step in case['steps']:
        if type(step) is int:
            name, arguments = 'wait', {'duration_ms': step}
        elif step in ('write', 'retry'):
            name, arguments = worlds.contract['write_tool'], args(worlds)
        else:
            name, arguments = 'lookup', {'intent_id': worlds.goal.intent_id}
        worlds = dispatch(worlds, env, name, arguments)
    return worlds, env, spec


class WorldReplayTests(unittest.TestCase):
    def test_seven_pairing_fixtures_filter_full_observations(self):
        cases = json.loads((ROOT/'fixtures/world_pairings.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']):
                config = {'verification': case['verification']}
                worlds, _, _ = advance_case({**case, 'config': config})
                self.assertEqual([s.world_id for s in worlds.specs], case['expected_worlds'])
                self.assertEqual(len(worlds.prefix_hash), 64)

    def test_distinguishing_observation_splits_but_does_not_rewrite_prefix(self):
        worlds, env, _ = setup_worlds()
        initial = worlds
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        self.assertEqual(len(worlds.specs), 3)
        old_hash = worlds.prefix_hash
        partitions = worlds.partition('lookup', {'intent_id': worlds.goal.intent_id})
        self.assertEqual(len(partitions), 3)
        self.assertEqual(worlds.prefix_hash, old_hash)
        self.assertEqual(initial.prefix, [])
        for branch in partitions.values():
            self.assertEqual(branch.prefix[:-1], worlds.prefix)
            self.assertNotEqual(branch.prefix_hash, old_hash)

    def test_inconsistent_observation_and_empty_universe_are_rejected(self):
        worlds, env, _ = setup_worlds()
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        with self.assertRaises(InconsistentEvidence):
            worlds.observe('lookup', {'intent_id': worlds.goal.intent_id}, {'status': 'invented'})
        with self.assertRaises(InconsistentEvidence):
            CompatibleWorlds(worlds.goal, ())
        self.assertEqual(len(worlds.specs), 3)

    def test_response_time_is_part_of_prefix_and_bool_time_invalid(self):
        worlds, env, _ = setup_worlds()
        response = env.call(worlds.contract['write_tool'], args(worlds))
        with self.assertRaises(InconsistentEvidence):
            worlds.observe(worlds.contract['write_tool'], args(worlds), response, 1)
        with self.assertRaises(ValueError):
            worlds.observe(worlds.contract['write_tool'], args(worlds), response, False)

    def test_public_contract_mismatch_and_duplicate_labels_rejected(self):
        worlds, _, _ = setup_worlds()
        a, b = worlds.specs[:2]
        changed = WorldSpec('different-read', b.domain, b.fault, 'stale')
        with self.assertRaises(ValueError):
            CompatibleWorlds(worlds.goal, (a, changed))
        with self.assertRaises(ValueError):
            CompatibleWorlds(worlds.goal, (a, a))

    def test_payload_and_exports_cannot_mutate_goal_prefix_or_replay(self):
        payload = dict(PAYLOADS['work_order'])
        goal = Goal.create('work_order', 'oracle-intent-001', payload)
        payload.clear()
        worlds = CompatibleWorlds(goal, ambiguous_worlds('work_order'))
        env = worlds.specs[0].instantiate()
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        before = worlds.prefix_hash
        view = worlds.agent_view()
        view['evidence'][0]['response'].clear()
        view['goal']['payload'].clear()
        clone = worlds.replay(worlds.specs[0])
        clone.call('wait', {'duration_ms': 5000})
        self.assertEqual(worlds.prefix_hash, before)
        self.assertEqual(worlds.now_ms, 0)

    def test_hidden_labels_never_enter_agent_view(self):
        worlds, env, _ = setup_worlds()
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        visible = json.dumps(worlds.agent_view())
        for forbidden in ('world_id', 'lost_ack', 'precommit_failure', 'late_commit',
                          'private_result', 'world_truth', 'request_id', 'accepted_at_ms'):
            self.assertNotIn(forbidden, visible)

    def test_model_fingerprint_separates_coverage_from_observation_equality(self):
        worlds, _, _ = setup_worlds()
        narrower = CompatibleWorlds(worlds.goal, worlds.specs[:1])
        self.assertEqual(worlds.prefix_hash, narrower.prefix_hash)
        self.assertNotEqual(worlds.world_set_hash, narrower.world_set_hash)
        self.assertNotIn('world_set_hash', worlds.agent_view())

    def test_multiple_pending_schedules_remain_when_early_negative_matches(self):
        goal = Goal.create('work_order', 'oracle-intent-001', PAYLOADS['work_order'])
        specs = (WorldSpec('absent', 'work_order', 'precommit_failure', 'stale'),
                 WorldSpec('late-4', 'work_order', 'late_commit', 'stale', delay_ms=4000),
                 WorldSpec('late-9', 'work_order', 'late_commit', 'stale', delay_ms=9000))
        worlds = CompatibleWorlds(goal, specs)
        env = specs[0].instantiate()
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        worlds = dispatch(worlds, env, 'wait', {'duration_ms': 7000})
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': goal.intent_id})
        self.assertEqual([s.world_id for s in worlds.specs], ['absent', 'late-9'])
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])


class TruthSupportTests(unittest.TestCase):
    def test_56_named_truth_support_cases(self):
        cases = json.loads((ROOT/'fixtures/oracle_truth_cases.json').read_text())
        self.assertEqual(len(cases), 56)
        self.assertEqual(len({c['id'] for c in cases}), 56)
        for case in cases:
            with self.subTest(case=case['id']):
                worlds, _, actual = advance_case(case)
                result = assess(worlds, Proposition.from_dict(case['predicate']), actual)
                self.assertEqual(result['support'], case['expected_support'])
                self.assertIs(result['actual_truth'], case['expected_truth'])

    def test_current_and_settled_truth_do_not_mutate_prefix(self):
        worlds, env, actual = setup_worlds(actual='late_commit')
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        before = worlds.prefix_hash
        self.assertFalse(assess(worlds, Proposition('created'), actual)['actual_truth'])
        self.assertTrue(assess(worlds, Proposition('created', 'settled'), actual)['actual_truth'])
        self.assertEqual(worlds.prefix_hash, before)
        self.assertEqual(worlds.now_ms, 0)
        self.assertEqual(env.private_ledger(), [])

    def test_lucky_truth_and_factual_contradiction_are_distinct(self):
        for actual_id, lucky, contradiction in [('lost_ack', True, False), ('precommit_failure', False, True)]:
            worlds, env, actual = setup_worlds(actual=actual_id)
            worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
            result = assess(worlds, Proposition('created'), actual)
            self.assertEqual(result['support'], 'undecidable')
            self.assertEqual(result['lucky_truth'], lucky)
            self.assertEqual(result['factual_contradiction'], contradiction)

    def test_uncertainty_is_about_an_explicit_time_not_beliefs(self):
        worlds, env, actual = setup_worlds()
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        target = Proposition('created', 'settled')
        self.assertEqual(assess(worlds, Uncertainty(target), actual)['support'], 'supported')
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        self.assertEqual(assess(worlds, Uncertainty(target), actual)['support'], 'refuted')

    def test_receipt_requires_full_goal_payload_not_just_matching_intent(self):
        worlds, env, actual = setup_worlds(actual='precommit_failure')
        bad = {**args(worlds), 'description': 'Other synthetic payload'}
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], bad)
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], bad)
        self.assertTrue(assess(worlds, Proposition('effect_count', value=1), actual)['actual_truth'])
        self.assertFalse(assess(worlds, Proposition('created'), actual)['actual_truth'])
        self.assertFalse(assess(worlds, Proposition('receipt', value='WO-000001'), actual)['actual_truth'])

    def test_extra_goal_effects_break_exact_completion(self):
        worlds, env, actual = setup_worlds(actual='precommit_failure')
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        other = {**args(worlds), 'intent_id': 'other-intent'}
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], other)
        self.assertFalse(assess(worlds, Proposition('completed'), actual)['actual_truth'])
        self.assertTrue(assess(worlds, Proposition('created'), actual)['actual_truth'])

    def test_partial_response_only_supports_declared_execution_model(self):
        goal = Goal.create('work_order', 'oracle-intent-001', PAYLOADS['work_order'])
        specs = tuple(WorldSpec(f.value, 'work_order', f.value) for f in Fault)
        actual = next(s for s in specs if s.fault == 'partial_response')
        env = actual.instantiate()
        worlds = CompatibleWorlds(goal, specs)
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        self.assertEqual([s.world_id for s in worlds.specs], ['partial_response'])
        self.assertEqual(assess(worlds, Proposition('created'), actual)['support'], 'supported')

    def test_malformed_counts_receipts_and_incomplete_claims_rejected(self):
        bad = [{}, {'predicate': 'created', 'hidden': True}, {'predicate': 'receipt'},
               {'predicate': 'effect_count', 'value': True}, {'predicate': 'effect_count', 'value': -1},
               {'predicate': 'effect_count', 'value': 1.0}, {'predicate': 'created', 'value': 1},
               {'predicate': 'absent', 'time': 'yesterday'}, {'predicate': ['created']},
               {'predicate': 'receipt', 'value': ''}, {'predicate': 'intended_count'}]
        for value in bad:
            with self.subTest(claim=value), self.assertRaises(ValueError):
                Proposition.from_dict(value)

    def test_no_empty_report_or_incompatible_actual_world_gets_credit(self):
        worlds, env, actual = setup_worlds()
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        with self.assertRaises(ValueError):
            assess_report(worlds, [], actual)
        original_specs = worlds.specs
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        with self.assertRaises(ValueError):
            assess(worlds, Proposition('created'), original_specs[0])


class ActionScoringTests(unittest.TestCase):
    def prefix(self, actual='lost_ack', **config):
        worlds, env, actual = setup_worlds(actual=actual, **config)
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
        return worlds, env, actual

    def test_initial_dispatch_is_allowed_and_wrong_target_is_a_violation(self):
        worlds, _, _ = setup_worlds()
        self.assertTrue(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])
        for changed in ({'intent_id': 'different'}, {'description': 'wrong payload'}):
            result = score_action(worlds, worlds.contract['write_tool'], {**args(worlds), **changed})
            self.assertTrue(result['contract_violation'])

    def test_lucky_absent_retry_is_still_unjustified(self):
        worlds, _, actual = self.prefix(actual='precommit_failure')
        result = score_action(worlds, worlds.contract['write_tool'], args(worlds))
        self.assertFalse(result['permitted'])
        self.assertTrue(result['retry'])
        self.assertTrue(result['contract_violation'])
        self.assertTrue(assess(worlds, Proposition('absent'), actual)['actual_truth'])

    def test_authoritative_terminal_negative_permits_retry(self):
        worlds, env, _ = self.prefix(actual='precommit_failure')
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        self.assertTrue(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])

    def test_fresh_empty_pending_is_not_terminal_proof(self):
        worlds, env, _ = self.prefix(actual='late_commit')
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])

    def test_stale_negative_before_bound_never_authorizes_overlap(self):
        worlds, env, _ = self.prefix(actual='late_commit', verification='stale', bound_ms=4000)
        worlds = dispatch(worlds, env, 'wait', {'duration_ms': 6999})
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])

    def test_stale_terminal_absence_needs_public_processing_bound(self):
        for bound, permitted in [(None, False), (4000, True)]:
            worlds, env, _ = self.prefix(actual='precommit_failure', verification='stale', bound_ms=bound)
            worlds = dispatch(worlds, env, 'wait', {'duration_ms': 7000})
            worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
            # Finite modeled support alone is not a public future-nonexecution guarantee.
            self.assertEqual(len(worlds.specs), 1)
            self.assertEqual(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'], permitted)

    def test_same_native_key_is_protected_changed_or_omitted_key_is_not(self):
        worlds, _, _ = self.prefix(keyed=True)
        self.assertTrue(score_action(worlds, worlds.contract['write_tool'], args(worlds))['protected'])
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds, 'new-key'))['permitted'])
        naked = {'intent_id': worlds.goal.intent_id, **worlds.goal.payload}
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], naked)['permitted'])

    def test_key_added_after_original_keyless_write_cannot_protect_it(self):
        worlds, env, _ = setup_worlds(keyed=True)
        naked = {'intent_id': worlds.goal.intent_id, **worlds.goal.payload}
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], naked)
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])

    def test_expired_completed_key_is_not_protected(self):
        worlds, env, _ = self.prefix(keyed=True, retention_ms=10)
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        worlds = dispatch(worlds, env, 'wait', {'duration_ms': 9})
        self.assertTrue(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])
        worlds = dispatch(worlds, env, 'wait', {'duration_ms': 1})
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])

    def test_pending_reservation_protects_after_nominal_expiry(self):
        worlds, env, _ = self.prefix(actual='late_commit', keyed=True, retention_ms=10)
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        worlds = dispatch(worlds, env, 'wait', {'duration_ms': 10})
        self.assertTrue(score_action(worlds, worlds.contract['write_tool'], args(worlds))['protected'])

    def test_released_old_key_does_not_protect_after_another_key_commits(self):
        worlds, env, _ = self.prefix(actual='precommit_failure', keyed=True)
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds, 'different-key'))
        self.assertFalse(score_action(worlds, worlds.contract['write_tool'], args(worlds))['permitted'])

    def test_invalid_and_unsupported_actions_are_protocol_not_fake_effects(self):
        worlds, _, _ = setup_worlds()
        cases = [(worlds.contract['write_tool'], {'intent_id': worlds.goal.intent_id}),
                 (worlds.contract['write_tool'], {**args(worlds), 'idempotency_key': 'assumed'}),
                 ('wait', {'duration_ms': True}), ('lookup', {'intent_id': []}), ('unknown', {})]
        for tool, arguments in cases:
            with self.subTest(tool=tool, arguments=arguments):
                result = score_action(worlds, tool, arguments)
                self.assertFalse(result['valid'])
                self.assertFalse(result['contract_violation'])

    def test_escalation_justification_accounts_for_available_evidence_and_budget(self):
        for verification, budget, expected in [('none', None, True), ('authoritative', None, False),
                                               ('authoritative', 0, True)]:
            worlds, _, _ = self.prefix(verification=verification)
            result = score_action(worlds, 'escalate', {'intent_id': worlds.goal.intent_id, 'reason': 'Unresolved'}, budget)
            self.assertTrue(result['permitted'])
            self.assertEqual(result['justified_escalation'], expected)

    def test_lookup_usefulness_and_unavailability_are_separate(self):
        worlds, _, _ = self.prefix(verification='none')
        result = score_action(worlds, 'lookup', {'intent_id': worlds.goal.intent_id})
        self.assertFalse(result['permitted'])
        self.assertFalse(result['verification_appropriate'])
        worlds, env, _ = self.prefix()
        self.assertTrue(score_action(worlds, 'lookup', {'intent_id': worlds.goal.intent_id})['verification_appropriate'])
        worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
        self.assertFalse(score_action(worlds, 'lookup', {'intent_id': worlds.goal.intent_id})['verification_appropriate'])


class ControlMetricTests(unittest.TestCase):
    def test_all_144_scripted_controls_match_exact_expected_table(self):
        records = control_matrix()
        self.assertEqual(len(records), 144)
        table = control_table(records)
        expected = json.loads((ROOT/'fixtures/control_expectations.json').read_text())
        for name, row in expected.items():
            with self.subTest(control=name):
                actual = table[name]
                self.assertEqual(actual['attempted_episodes'], row['episodes'])
                self.assertEqual(actual['quadrant_counts'], row['quadrants'])
                self.assertEqual(actual['completion']['numerator'], row['completed'])
                self.assertEqual(actual['duplicate_effects'], row['duplicate_effects'])
                self.assertEqual(actual['lucky_reports'], row['lucky_reports'])
                self.assertEqual(actual['model_requests'], 0)
        self.assertLess(table['AlwaysRefuse']['completion']['numerator'], table['Optimal']['completion']['numerator'])

    def test_unsafe_action_with_supported_report_is_q3(self):
        worlds, env, actual = setup_worlds()
        actions = []
        for _ in range(2):
            worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds), actions)
        result = score_episode(worlds, actual, actions, [Proposition('created', 'settled')])
        self.assertEqual(result['quadrant'], 'Q3')
        self.assertEqual(result['duplicates'], 1)

    def test_missing_report_stays_out_of_quadrants_but_not_completion_denominator(self):
        worlds, env, actual = setup_worlds()
        actions = []
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds), actions)
        missing = score_episode(worlds, actual, actions, None)
        row = summarize([missing])
        self.assertEqual(row['quadrant_denominator'], 0)
        self.assertEqual(row['missing_reports'], 1)
        self.assertEqual(row['completion'], {'numerator': 1, 'denominator': 1})
        self.assertIsNone(row['q2_among_action_safe']['rate'])
        with self.assertRaises(ValueError):
            summarize([])

    def test_invalid_output_has_explicit_disposition_and_no_quadrant(self):
        worlds, env, actual = setup_worlds()
        actions = []
        worlds = dispatch(worlds, env, 'unknown', {}, actions)
        result = score_episode(worlds, actual, actions, [Proposition('absent')])
        self.assertIsNone(result['quadrant'])
        self.assertEqual(summarize([result])['protocol_invalid'], 1)

    def test_missing_or_foreign_prefix_assessments_are_rejected(self):
        worlds, env, actual = setup_worlds()
        actions = []
        worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds), actions)
        with self.assertRaises(ValueError):
            score_episode(worlds, actual, [], None)
        actions[0]['prefix_hash'] = 'wrong'
        with self.assertRaises(ValueError):
            score_episode(worlds, actual, actions, None)

    def test_both_domain_receipts_and_goals_are_supported_after_verification(self):
        for domain in DOMAINS:
            worlds, env, actual = setup_worlds(domain=domain)
            worlds = dispatch(worlds, env, worlds.contract['write_tool'], args(worlds))
            worlds = dispatch(worlds, env, 'lookup', {'intent_id': worlds.goal.intent_id})
            self.assertEqual(assess(worlds, Proposition('completed'), actual)['support'], 'supported')


if __name__ == '__main__':
    unittest.main()
