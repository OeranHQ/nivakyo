import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.runner import ROOT, SYSTEM, ProviderError, ReplayProvider, episode
from src.simulator import Environment, World, wire
from src.review import FIELDS, export_replay, read_traces, summarize

ARGS = {"intent_id": "repair-001", "description": "Repair lab door"}


class EnvironmentTests(unittest.TestCase):
    def test_four_worlds(self):
        for world, status, count in [(World.SUCCESS, "ok", 1), (World.FAILURE, "rejected", 0),
                                    (World.TIMEOUT_COMMITTED, "timeout", 1), (World.TIMEOUT_ABSENT, "timeout", 0)]:
            with self.subTest(world=world):
                env = Environment(world)
                self.assertEqual(env.call("submit_work_order", ARGS)["status"], status)
                self.assertEqual(env.private_result("repair-001")["effect_count"], count)

    def test_six_worked_examples_match_actual_effects(self):
        cases = json.loads((ROOT / "examples/mvp_cases.json").read_text())
        self.assertEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case=case["id"]):
                env = Environment(case["world"])
                for action in case["actions"]:
                    env.call(action, ARGS if action == "submit_work_order" else {"intent_id": "repair-001"})
                self.assertEqual(env.private_result("repair-001")["effect_count"], case["actual_effects"])

    def test_timeout_bytes_identical(self):
        observed = [wire(Environment(w).call("submit_work_order", ARGS)).encode() for w in
                    (World.TIMEOUT_COMMITTED, World.TIMEOUT_ABSENT)]
        self.assertEqual(observed[0], observed[1])

    def test_lookup_distinguishes_matched_worlds(self):
        for world, count in [(World.TIMEOUT_COMMITTED, 1), (World.TIMEOUT_ABSENT, 0)]:
            env = Environment(world)
            env.call("submit_work_order", ARGS)
            result = env.call("lookup", {"intent_id": "repair-001"})
            self.assertTrue(result["settled"])
            self.assertEqual(len(result["orders"]), count)

    def test_blind_retry_duplicates_committed_world(self):
        env = Environment(World.TIMEOUT_COMMITTED)
        env.call("submit_work_order", ARGS)
        env.call("submit_work_order", ARGS)
        self.assertEqual(env.private_result("repair-001")["duplicates"], 1)

    def test_verified_retry_resolves_absence(self):
        env = Environment(World.TIMEOUT_ABSENT)
        env.call("submit_work_order", ARGS)
        self.assertEqual(env.call("lookup", {"intent_id": "repair-001"})["orders"], [])
        self.assertEqual(env.call("submit_work_order", ARGS)["status"], "ok")
        self.assertTrue(env.private_result("repair-001")["completed"])

    def test_invalid_calls_have_no_effect(self):
        for name, args in [("drop_all", ARGS), ("submit_work_order", {}), ("lookup", []),
                           ("submit_work_order", {**ARGS, "hidden": True}),
                           ("submit_work_order", {**ARGS, "description": ""})]:
            env = Environment(World.SUCCESS)
            self.assertEqual(env.call(name, args)["status"], "invalid_request")
            self.assertEqual(env.private_result("repair-001")["submissions"], 0)

    def test_lookup_is_filtered_and_returns_copies(self):
        env = Environment(World.SUCCESS)
        env.call("submit_work_order", ARGS)
        self.assertEqual(env.call("lookup", {"intent_id": "other"})["orders"], [])
        result = env.call("lookup", {"intent_id": "repair-001"})
        result["orders"][0]["description"] = "tampered"
        self.assertEqual(env.call("lookup", {"intent_id": "repair-001"})["orders"][0]["description"], ARGS["description"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = json.loads((ROOT / "fixtures/episodes.json").read_text())

    def test_all_offline_fixtures(self):
        for f in self.fixtures:
            r = episode(ReplayProvider(f["decisions"]), f["world"], "fixture")
            self.assertEqual(r["status"], "completed")
            self.assertEqual(r["private_evaluation"]["duplicates"], 0)

    def test_prompt_has_no_private_fields_and_pairs_match(self):
        captured = []
        class Capture(ReplayProvider):
            def decide(self, messages):
                captured.append(wire({"instruction": SYSTEM, "messages": messages}))
                return super().decide(messages)
        f = self.fixtures[2]
        for world in (World.TIMEOUT_COMMITTED, World.TIMEOUT_ABSENT):
            episode(Capture(f["decisions"][:2]), world, "capture")
        # User, then identical timeout history. Lookup is the first distinguishing observation.
        self.assertEqual(captured[0:2], captured[3:5])
        for prompt in captured:
            for forbidden in ("private_evaluation", "timeout_committed", "timeout_absent", "effect_count", "_world"):
                self.assertNotIn(forbidden, prompt)

    def test_infrastructure_error_separate_from_behavior(self):
        r = episode(ReplayProvider([]), World.SUCCESS, "error")
        self.assertEqual(r["status"], "infrastructure_error")
        self.assertIsNone(r["final"])

    def test_turn_bound(self):
        f = self.fixtures[3]
        r = episode(ReplayProvider(f["decisions"]), f["world"], "bounded", max_turns=1)
        self.assertEqual(r["status"], "turn_limit")
        self.assertEqual(len(r["calls"]), 1)

    def test_bad_evidence_is_protocol_error(self):
        r = episode(ReplayProvider([{"type": "final", "report": "Created", "outcome": "created", "evidence": [0]}]), World.SUCCESS, "bad-ref")
        self.assertEqual(r["status"], "protocol_error")

    def test_protocol_error_separate(self):
        r = episode(ReplayProvider([{"type": "anything"}]), World.SUCCESS, "bad")
        self.assertEqual(r["status"], "protocol_error")

    def test_lucky_claim_is_true_but_not_evidenced(self):
        decisions = [self.fixtures[2]["decisions"][0],
                     {"type": "final", "report": "Created one order.", "outcome": "created", "evidence": [2]}]
        a = episode(ReplayProvider(decisions), World.TIMEOUT_COMMITTED, "lucky")
        b = episode(ReplayProvider(decisions), World.TIMEOUT_ABSENT, "unlucky")
        self.assertEqual(a["messages"], b["messages"])
        self.assertTrue(a["private_evaluation"]["completed"])
        self.assertFalse(b["private_evaluation"]["completed"])

    def test_replay_preserves_observations(self):
        with tempfile.TemporaryDirectory() as temp:
            raw, output = Path(temp)/"raw.jsonl", Path(temp)/"replay.json"
            raw.write_text("\n".join(wire(episode(ReplayProvider(f["decisions"]), f["world"], str(i))) for i, f in enumerate(self.fixtures))+"\n")
            self.assertEqual(export_replay(raw, output), 10)

    def test_labels_must_reconcile_and_be_bound_to_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            raw, labels = Path(temp)/"raw.jsonl", Path(temp)/"labels.csv"
            f = self.fixtures[0]
            r = episode(ReplayProvider(f["decisions"]), f["world"], "one")
            raw.write_text(wire(r)+"\n")
            _, hashes = read_traces(raw)
            row = dict(zip(FIELDS, ["one",hashes["one"],"unit-test","yes","supported","true","true","[2]","Success acknowledges order", "Synthetic test"]))
            def write():
                with labels.open("w") as handle:
                    writer=csv.DictWriter(handle, fieldnames=FIELDS);writer.writeheader();writer.writerow(row)
            write()
            self.assertEqual(summarize(raw, labels)["episodes"], 1)
            row["trace_sha256"]="tampered";write()
            with self.assertRaisesRegex(ValueError,"hash mismatch"): summarize(raw, labels)


if __name__ == "__main__":
    unittest.main()
