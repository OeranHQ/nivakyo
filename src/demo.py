"""Fresh offline smoke run. Labels are fixture-derived, explicitly not manual annotations."""
import argparse
import csv
import json
from pathlib import Path

from src.review import FIELDS, read_traces, summarize
from src.runner import ROOT, ReplayProvider, episode
from src.simulator import wire


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    fixtures = json.loads((ROOT / "fixtures/episodes.json").read_text())
    records = [episode(ReplayProvider(f["decisions"]), f["world"], "offline-%02d" % i) for i, f in enumerate(fixtures, 1)]
    raw = args.output_dir / "raw.jsonl"
    raw.write_text("".join(wire(r) + "\n" for r in records))
    _, hashes = read_traces(raw)
    labels = args.output_dir / "labels.csv"
    with labels.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for r in records:
            writer.writerow(dict(zip(FIELDS, [r["episode_id"], hashes[r["episode_id"]],
                "fixture-derived; not manual", "yes", "supported", "true",
                str(r["private_evaluation"]["completed"]).lower(), json.dumps(r["final"]["evidence"]),
                "Authored fixture: final claim cites successful submission, definitive rejection or authoritative lookup; retries follow established absence.",
                "Scripted smoke test; no model inference or independent annotation."])))
    result = summarize(raw, labels)
    (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
