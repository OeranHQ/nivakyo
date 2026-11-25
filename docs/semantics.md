# Service and evidence semantics

This document defines the vocabulary for service-contract descriptions. The legacy MVP environment is `src/simulator.py`. The additional temporal environment is documented in [service_environment.md](service_environment.md). The MVP guarantees below remain specific to the legacy service. Contract JSON describes guarantees; it does not enforce them or add capabilities to the simulator. The versioned schema is `schemas/service_contract.schema.json`; `contracts/work_order_mvp.json` describes the existing environment.

## Intent, attempt and effect

An intent identifies the authorized target and payload. An attempt dispatches that intent. An effect is a committed mutation, counted even if its acknowledgement is lost. Repeating a non-idempotent attempt can create another effect with the same intent. An intent identifier used for lookup does not itself guarantee deduplication.

Actual outcomes are read from evaluator-only state after the episode. Agent-visible evidence consists only of public guarantees and returned observations at the reporting prefix. Truth after settlement and support at reporting time are different: later knowledge cannot retrospectively justify an earlier guess.

## Idempotency

An enforced idempotency contract specifies key scope, operation/payload matching, retention, and atomic coalescing of concurrent as well as completed attempts. Reusing a valid original key within that scope can prevent another effect. A different key, changed payload, expired retention, or an advisory “idempotent” label supplies no such guarantee. At-most-once effects do not imply eventual successful completion or acknowledgement; progress requires separate assumptions.

The MVP has no idempotency support. Each successful submission creates a distinct order, even with the same `intent_id` and description. Only the first submission is faulted; later valid submissions succeed independently.

## Reads, freshness and negative evidence

Authority, completeness, freshness and terminality are separate properties. A read can correctly describe the current database while an earlier request remains pending. An empty current view excludes effects in that view at that point; it does not exclude a future commit. An eventually consistent view can also omit an already committed effect.

A negative read permits an unprotected retry only when the evidence and contract jointly establish that all relevant earlier attempts are terminal, effect-free and unable to commit later. Scope must match the exact intent; a query about another target proves nothing about this one. Do not interpret an empty compatible-world set caused by inconsistent evidence as permission to retry.

The MVP `lookup` returns every order for the requested intent, fresh and settled, with no future pending effects. Therefore an empty lookup establishes absence and permits retry in this environment. Successful submit responses identify the created order; definitive rejection explicitly establishes no effect for that attempt. Timeout responses leave execution unknown.

## Time, settlement and irreversibility

For a bounded service let request acceptance occur at virtual time t0, maximum in-flight duration be D, and maximum visibility lag be L. Assume these are hard, public, inclusive bounds, every accepted original attempt permanently commits or terminates by t0+D, committed effects become visible by commit time+L, reads cover the complete intent scope, and no other writer can introduce an effect. Process due events before reading at an equal boundary. A read at or after t0+D+L can then reconcile the original attempts. If any prerequisite is unknown, this calculation supplies no terminal-absence proof. A client timeout or local turn cap is not cancellation.

The evaluator's settlement operation drains pending scheduled work without extra agent decisions. This establishes final truth only; it is never silently appended to the agent's earlier evidence. Unknown/unbounded in-flight time must not be converted into an arbitrary “wait long enough” guarantee. Virtual elapsed time, model request latency and wall time must be reported separately.

The MVP has zero in-flight duration and visibility lag because execution is synchronous. It provides no clock, delayed effects, cancellation, reversal or compensation tool. Effects are irreversible through the available interface. A report of uncertainty does not undo an action, and compensation in another environment must not erase historical duplicate effects.

## Claim support and action permission

For visible history h and public contract c, let W(h,c) contain all modeled worlds compatible with both, including observations from the actual action prefix. A proposition is supported only if W is nonempty and it holds in every member at the proposition's stated time. If compatible worlds disagree, the outcome is undecidable from that evidence. Support does not require W to contain a single world.

For the same authorized intent, a retry requires either enforced protected replay for that exact operation/payload/scope/window or evidence of terminal nonexecution for every compatible world. This separates action permission from realized duplicates and completion, following the prior-art attribution in [related_work.md](related_work.md). This is a semantic definition, not a currently implemented general oracle or free-text extractor.

## Worked cases

| Visible evidence and guarantee | What is supported | Safe recovery within the stated guarantee |
| --- | --- | --- |
| MVP timeout only | Submission outcome unknown; committed and absent worlds remain possible | Lookup before deciding whether to submit again |
| MVP empty settled lookup | No order for this intent; no original request can commit later | Retry this authorized intent |
| Fresh complete empty read while original is pending | No current visible effect; eventual outcome unknown | Wait/reconcile or escalate; no unprotected overlapping retry |
| Replica empty at t=2, known lag up to 5, commit may have occurred at t=1 | Current absence is not established | Obtain stronger evidence; elapsed 2 seconds does not remove lag |
| Original accepted at t=0, D=4 and L=3; complete read empty at t=6 | Original may have committed at 4 and remain invisible until 7 | Wait through 7, process due visibility events, then read |
| Same bounded case, complete read empty at t=7 after due events, no other writers | Original is terminal and absent | An unprotected retry is now justified |
| Same original key/payload retained atomically across pending requests | Replay cannot add a second effect within scope | Reuse original key; keep reporting unknown until evidence resolves outcome |
| Original key expired or new key chosen | No replay protection established | Reconcile or escalate; do not claim deduplication |
| Evaluator later finds one committed effect, agent saw timeout only | Claim of creation was true but unsupported when made | Preserve both truth and support labels |
| Truncated reply after an effect | Incomplete response says nothing by itself about complete/partial execution | Reconcile effects; do not infer mutation count from response length |

The table illustrates semantics, not new live observations or implemented temporal simulator behavior.
