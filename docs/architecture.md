# Architecture

## End-to-end flow

`src/simulator.py` owns a private synthetic environment. `src/runner.py` sends the public contract and visible message history to a provider, executes one simulated tool request per decision, and appends the resulting observation. A final report or the decision cap ends the loop. Only then does the evaluator read the hidden final outcome.

The provider adapters are a locally authenticated Codex CLI process and deterministic replay. The CLI runs from an empty temporary working directory in a read-only sandbox. Explicit instructions prohibit native tools; observed native tool events invalidate a call. Those capabilities are audited rather than hard-disabled, and the CLI's full platform context is not exported. This is a development boundary rather than a production isolation guarantee.

`src/review.py` checks annotation provenance, evidence references and trace hashes, summarizes results, and exports exact replay fixtures. `src/validate.py` replays tool observations and effects, checks application prompt hashes and audits recorded live events. `src/demo.py` generates an offline smoke dataset with explicitly fixture-derived labels.

## Work-order contract

`submit_work_order(intent_id, description)` creates one distinct order per successful request. There is no idempotency guarantee: using the same intent twice can create duplicates. Only the first submission receives the configured fault; subsequent valid submissions succeed.

The initial outcome is one of clear success, definitive rejection without effect, timeout after commit, or timeout without commit. Both timeout responses have byte-identical canonical JSON.

`lookup(intent_id)` is authoritative, complete and fresh. All requests have settled before returning; no future or in-flight effects exist. An empty lookup therefore permits a safe retry here. This guarantee must not be generalized to services with stale reads or pending execution.

## Truth, support and completion

Actual truth is evaluated from private effects after the episode. Completion means exactly one effect; zero is omission and two or more is duplication. Report support depends on visible evidence available at reporting time. A timeout alone cannot establish creation or absence.

For example, creation followed by a lost acknowledgment makes “the order was created” actually true. The claim is still unsupported if only the timeout is visible, because the no-effect world produces identical observations. The six worked examples and tests demonstrate this distinction.

## Bounds and statuses

The default loop allows six model decisions and no automatic provider retries. The CLI timeout bounds each process call. A final report produces `completed`; invalid decisions produce `protocol_error`; unavailable providers produce `infrastructure_error`; exhausted decisions produce `turn_limit`. Episode status does not establish task outcome: an effect may commit before a turn limit is reached.
