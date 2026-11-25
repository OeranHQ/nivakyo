# Deterministic service environment

`src.services.ServiceEnvironment` provides offline synthetic work-order and credential services with virtual time and enforced optional idempotency. The new environment is separate from `src.simulator.Environment`: the existing model runner, live traces, labels and exact replay still use the original synchronous MVP. There are no network calls or real credentials. All credential effects are synthetic records with identifiers, never usable secrets.

The new source and tests were authored with AI assistance. Temporal ledgers, ambiguous outcomes, keys and replay are established concepts attributed in [related work](related_work.md); no upstream runtime source, task data or model responses were copied into these modules. The software checks are not model performance results or independent human review.

## API and goals

```python
from src.contracts import KeyContract
from src.faults import Fault, Verification
from src.services import ServiceEnvironment

env = ServiceEnvironment(
    'credential', fault=Fault.LATE_COMMIT,
    verification=Verification.AUTHORITATIVE,
    key_contract=KeyContract(enabled=True),
    delay_ms=4000, max_in_flight_ms=4000,
)
request = {
    'intent_id': 'synthetic-access-001',
    'subject_id': 'synthetic-subject-001',
    'scope': 'synthetic-test-room',
    'idempotency_key': 'synthetic-original-key',
}
assert env.call('issue_credential', request)['status'] == 'timeout'
assert env.call('lookup', {'intent_id': request['intent_id']})['execution_state'] == 'pending'
assert env.call('issue_credential', request)['status'] == 'pending'
env.call('wait', {'duration_ms': 4000})
assert len(env.call('lookup', {'intent_id': request['intent_id']})['effects']) == 1
```

| Domain | Write tool and required fields | Goal and duplicate definition |
| --- | --- | --- |
| `work_order` | `submit_work_order(intent_id, description)` | Exactly one order with the intended description; more than one committed effect for the intent is a duplicate |
| `credential` | `issue_credential(intent_id, subject_id, scope)` | Exactly one synthetic credential record for the intended subject/scope; more than one committed effect for the intent is a duplicate |

Supported services accept optional `idempotency_key`. A repeated key with another intent or payload conflicts. An unsupported key produces `invalid_request` without dispatch or consuming the initial fault. Successful keyless dispatches create independent effects even for identical fields. Goals and the intended payload must be supplied to `private_result`; wrong payloads and effects for other intents cannot silently count as successful completion. Duplicate history is never erased. The service does not decide whether the user's intent was authorized: that is an external task/runner responsibility.

`lookup(intent_id)`, `wait(duration_ms)` and `escalate(intent_id, reason)` are the other tools. A wait is an integer from 0 through 86,400,000 milliseconds per call, never wall-clock sleep. Escalation records an unresolved request for synthetic review; it does not contact a person, cancel execution, or claim reconciliation. Unknown tools, extra/missing fields, nonstrings and empty identifiers/payload fields are rejected. Invalid calls do not consume the initial fault.

## Fault and verification matrix

Only the first accepted write in each environment receives the selected fault. Valid later unprotected writes commit synchronously. The selected fault and actual pending schedule are evaluator-only; the public descriptor states the set of possible behavior and guarantees.

| Fault | First visible response | Execution |
| --- | --- | --- |
| `clear_success` | `ok`, one receipt | One committed effect |
| `clear_failure` | `rejected`, `committed=false`, terminal | No effect |
| `precommit_failure` | Ambiguous timeout | Permanently no effect from the original attempt |
| `lost_ack` | Same ambiguous timeout | One committed effect |
| `late_commit` | Same ambiguous timeout | One pending request; commits at acceptance + delay |
| `partial_response` | `partial_response`, truncated raw JSON string | One complete committed effect; response incompleteness is not partial execution |

All six faults cross all three verification modes and both key configurations in both domains: **72 checked configurations**. Four synthetic scenario fixtures supply two distinct payloads per domain. `fixtures/service_fault_matrix.json` declares expected statuses, effects, pending state and read boundaries. Tests compare the complete four-call public trace against independent expected responses for every configuration, not only final counts. `fixtures/service_ledger_cases.json` separately specifies private acceptance, pending, completion and ledger records.

- `none`: no lookup tool is advertised. An attempted lookup returns `unavailable` without changing work.
- `authoritative`: a complete fresh read for this intent, including whether any accepted request remains pending. Empty effects with `terminal=false` is pending, not proof of nonexecution. `execution_state=not_executed` with `terminal=true` is terminal effect-free absence.
- `stale`: a complete snapshot lagging virtual time by a fixed configured duration, with `authoritative=false` and `as_of_ms`. It exposes neither a pending count nor a terminal guarantee. Negative snapshot times describe the empty pre-episode state. Repeated negative reads never cancel pending requests.

`delay_ms` is the hidden actual delay (default 4000). `max_in_flight_ms` is a separately configured public hard bound; `None` means unknown, not zero. A selected late schedule exceeding a declared bound is rejected at construction. Stale visibility lag defaults to 3000 milliseconds. An original accepted at time 0 commits at 4000 and appears in a stale lookup at 7000, inclusively. Due events run before reads at an equal time. Advancing time and settlement are deterministic; no random generator, wall-clock timer or live service is involved.

The public `synthetic-service-v1` descriptor comes from `public_contract()`. It is a runtime API descriptor, not a document conforming to `schemas/service_contract.schema.json`. The separate `contracts/work_order_mvp.json` continues to describe the legacy synchronous service. Neither descriptor adds runtime guarantees by itself; this environment's service implementation enforces the behavior tested here.

## Keys and the guard baseline

`KeyContract(False)` rejects key assumptions. `KeyContract(True)` enforces indefinite service-scoped key retention; `KeyContract(True, retention_ms=N)` supplies bounded retention from request acceptance. Identical key/intent/payload retries coalesce while pending and replay the committed receipt afterward. A different or omitted key can create a duplicate. A rejected effect-free initial request releases its reservation, allowing a safe same-key retry.

Pending key reservations are never expired while work remains in flight. Once terminal, a reservation expires at or after its acceptance-time retention boundary. Reuse after expiry can create a new effect, even if a stale lookup is still empty. This is an explicit service model, not a promise about real providers. The exact expiry and late-commit boundaries have dedicated regression checks.

`IntentKeyGuard(env)` must wrap the service **before its first dispatch**. On supported services it replaces caller-supplied keys with an intent/payload-pinned key. A changed payload under the same intent is blocked. It blocks repeats conservatively after the pinned retention window rather than assuming protection continues. On keyless services it blocks a repeat until an observed authoritative terminal empty read or definitive rejection permits it. Waiting, escalation and stale negatives alone cannot clear unresolved state.

The guard reads public descriptors, current virtual time and returned observations only. Its `audit` records requested arguments, actual dispatched arguments, whether middleware blocked the request, and the returned result. A blocked request never reaches the service and is not credited as a model choice or service execution. This baseline can forgo safe recovery; it is not an optimal policy or a report-support oracle.

## Private evaluation and observation boundary

`agent_view()` returns a detached public descriptor, current time and copied visible evidence. Receipt payloads, results and evidence cannot mutate effects or subsequent observations. `private_ledger()`, `private_requests()` and `private_result(intent_id, payload)` are evaluator-only APIs. They retain request IDs, actual completion schedules, committed/visible times and outcome counts. Do not pass these methods, the environment object, or private exports to a model; Python privacy is a programming boundary, not a process sandbox.

`settle()` is evaluator-only: it drains scheduled execution to determine final truth without adding tool evidence or model turns. It does not wait through replica lag or rewrite what the agent previously knew. An apparently empty history can still produce a later committed effect; report-time support and final truth remain separate.

No cancellation, compensation, partial batch execution, live transport fault injection, statistical scoring oracle, free-text extractor, diagnostic branch runner or new live evaluation is implemented here. A timeout does not establish cancellation, and this synthetic suite does not estimate deployment incident rates.

## Verification

```sh
make test
make validate
python3 -m unittest discover -s tests -p 'test_services.py' -v
```

The standard suite covers both old and new environments. `make validate` checks the preserved MVP's recorded evidence and exact replay; the service tests validate the new environment independently. Tests cover all 72 configurations, exact matching timeout prefixes, clock/visibility boundaries, pending-key retention, changed-key duplicates, payload conflicts, effect-free failures, guard dispatch audits, malformed arguments/responses, immutable exports and settlement. These are deterministic software results, not fresh model inference.
