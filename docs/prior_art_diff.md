# Component attribution and overlap

This inventory describes the legacy MVP code at the 23 November 2026 audit and inspected public sources. The additional temporal implementation is documented in [service_environment.md](service_environment.md). It does not assert novelty or that absent features were exhaustively ruled out. Exact versions, access scope and licenses are in [related_work.md](related_work.md).

| Component | Established overlap | Current nivakyo implementation | Reuse disposition |
| --- | --- | --- | --- |
| Frozen failed observation and evidence-grounded reports | FTA simulator and prompt construction | Work-order timeout observations; trace-bound manual AI review | Conceptual attribution; no imported source, scenarios or labels |
| Committed-effect ledger and temporal settlement | LIMBO world/services/grader | Private order list; every MVP request settles synchronously | Conceptual attribution; no imported code; temporal mechanics are not implemented |
| Permission distinct from fortunate final outcome | RetryBench scoring, service and retry contract | Worked examples distinguish supported claims from truth; lookup is settled/fresh | Conceptual attribution; no copied code, prompts or data; PolyForm code is not relicensed |
| Shared response across matched worlds | Did It Happen? counterfactual engine | Same timeout bytes in two worlds; separate runner episodes | Existing MVP does not perform upstream-style response sharing; no imported engine |
| Fault injection, explicit effects, strict replay | ToolStorm engine/contracts/replay | Small purpose-built simulator and exact replay fixtures | No ToolStorm dependency or source copy; fixture replay is not new inference |
| Dataset/agent/scorer separation | Inspect documentation | Provider adapter, environment, review and validator modules | No Inspect dependency or code reuse |

A model can avoid duplicates by doing nothing. It can also act safely while making a claim unsupported by its observations. Therefore duplicate counts, actual task completion and report support remain separate measurements. This is a design motivation, not a claim that these distinctions originated here.

The existing implementation is a single-domain, four-outcome MVP. It has no virtual clock, stale reads, pending execution, general compatible-world oracle, diagnostic fork or validated free-text extractor. Describing these capabilities as current would be inaccurate.

## Reuse ledger

As of 23 November 2026, this audit imported no upstream runtime source, tests, prompts, tasks, responses or labels into public nivakyo artifacts. Selected upstream files were inspected as research material. The general semantic vocabulary is attributed in related work. Service-contract schema and explanatory examples are project-authored with AI assistance. Existing replay fixtures derive from nivakyo's own retained traces.

For any later actual adaptation, record upstream URL/revision/path, local destination, modification, license scope and required notice before including it. MIT source copies retain their notices. Data and documentation can have separate licenses. Do not infer permission for code reuse from a paper's license or a repository's public visibility.
