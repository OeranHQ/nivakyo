"""Offline integrity checks of frozen live evidence. Does not replace report review."""
import hashlib
import json
import tempfile
from pathlib import Path

from src.review import export_replay, read_traces, summarize
from src.runner import ROOT, SYSTEM
from src.simulator import Environment, wire


def validate():
    raw = ROOT / "results/mvp/raw.jsonl"
    records, _ = read_traces(raw)
    if len(records) != 10 or any(r["status"] != "completed" or r["provider"] != "codex-cli" for r in records):
        raise ValueError("Expected ten completed live development episodes")
    for r in records:
        if len(r["calls"]) > r["settings"]["max_turns"]:
            raise ValueError("Turn cap exceeded")
        env = Environment(r["private_evaluation"]["world"])
        for i, message in enumerate(r["messages"]):
            if message["role"] == "tool":
                observed = env.call(message["name"], message["arguments"])
                if observed != message["content"]:
                    raise ValueError("Tool observations disagree with simulator")
        if env.private_result("repair-001") != r["private_evaluation"]:
            raise ValueError("Actual outcome disagrees with replayed effects")
        for call in r["calls"]:
            # Each turn consumes one assistant decision and (except final) one tool response.
            prefix = r["messages"][:1 + 2 * call["turn"]]
            prompt = wire({"instruction": r["instruction"], "messages": prefix})
            if hashlib.sha256(prompt.encode()).hexdigest() != call["prompt_sha256"]:
                raise ValueError("Prompt hash mismatch")
            for forbidden in ("private_evaluation", "timeout_committed", "timeout_absent", "effect_count", "_world"):
                if forbidden in prompt:
                    raise ValueError("Hidden state leaked into application prompt")
            for event in call["events"]:
                if event.get("item", {}).get("type") not in (None, "reasoning", "agent_message"):
                    raise ValueError("Unexpected native item in live trace")
            if not call["usage"]:
                raise ValueError("Live call missing usage")
    with tempfile.TemporaryDirectory() as temp:
        if export_replay(raw, Path(temp) / "replay.json") != 10:
            raise ValueError("Live replay incomplete")
    summary = summarize(raw, ROOT / "results/mvp/labels.csv")
    print("PASS: ten live traces, prompt hashes, no observed native tools, simulator effects, labels and exact replay")
    return summary


if __name__ == "__main__":
    validate()
