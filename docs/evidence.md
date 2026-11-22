# Development evidence

The included run uses Codex CLI 0.160.0 and model alias `gpt-6.1-sol`, with low reasoning effort, at most six decisions per episode and a 60-second process timeout. Temperature and seed were not configured. The alias does not identify frozen weights.

| Initial outcome | Episodes | Exactly one final effect | Supported reports | Duplicate effects |
| --- | ---: | ---: | ---: | ---: |
| Clear success | 2 | 2 | 2 | 0 |
| Definitive rejection | 2 | 2 | 2 | 0 |
| Timeout after commit | 3 | 3 | 3 | 0 |
| Timeout without commit | 3 | 3 | 3 | 0 |
| Total | 10 | 10 | 10 | 0 |

All six ambiguous timeout episodes used lookup. The three committed worlds needed no second submission; the three absent worlds retried after an authoritative empty lookup. Both definitive rejections were safely retried. Review inspected each complete visible history and final prose, then compared actual effects. Labels are **AI manual trace reviews**, not independent human annotations.

The run contains 31 recorded successful model decisions, 15 simulated submissions and six lookups. Emitted usage totals 566,914 input tokens, including 219,648 cached input tokens, and 1,547 output tokens. No dollar cost or deterministic live inference is inferred.

## Files and checks

- `results/mvp/raw.jsonl`: ten completed live development episodes.
- `results/mvp/labels.csv` and `summary.json`: trace-bound reviewed labels and reconciled counts.
- `results/mvp/run_manifest.json`: runtime/data hashes and settings.
- `fixtures/live_replay.json`: ten exact replay fixtures from the live run.
- `results/mvp/infrastructure-attempt-01.jsonl`, `infrastructure-labels.csv` and `infrastructure-summary.json`: ten CLI initialization failures with no model decision or usage emitted. These exclusions are separate from behavioral denominators.
- `results/fresh-smoke/`: ten fixture-driven episodes. Eight end with a completed task; two correctly report definitive failure. All ten scripted reports are supported, illustrating that reporting and task completion differ.
- `results/mvp/one-turn-check.jsonl`: ten episodes stopped by a one-decision cap, with no final reports, demonstrating that execution status and actual effects differ.

Use `make validate` for prompt/effect/history integrity and exact live replay, `make review` for annotation reconciliation, `make test` for behavior and publication safeguards, and `make demo` for a fresh offline trace/labels/summary.

## Interpretation limits

One synthetic context, explicit recovery instructions, one model alias and authoritative lookup make this a development demonstration. Ten episodes do not establish a general failure rate, novelty, provider comparison, or intervention effectiveness. The CLI adds platform context that is not fully exported. No native tool use was observed; native capabilities were audited rather than hard-disabled. Replaying existing traces does not increase the number of live samples.
