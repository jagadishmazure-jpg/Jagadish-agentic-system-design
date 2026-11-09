# Layer 12 - Evaluation

**Question:** how do we know the system did the right thing, the right way?

## Why it matters

A friendly final sentence can hide a wrong gate, an impossible route, a duplicate message or an
unauthorized booking. Judge the **process**: where it sent the passenger, how, when, with which tools,
and with whose permission.

## How Harrowgate does it

[`harrowgate/evaluation.py`](../../harrowgate/evaluation.py) replays each synthetic scenario
([`harrowgate/scenarios.py`](../../harrowgate/scenarios.py)) on a fresh simulated world, then checks
the response against world truth and the trace.

```mermaid
flowchart LR
    S[Scenario<br/>setup + faults + expectations] --> W[Fresh simulated world]
    W --> SYS[System under test]
    SYS --> RESP[Response + trace + side effects]
    RESP --> CK[11 checks]
    W --> CK
    CK --> RC[Root cause if failed]
```

| Check | Passes when |
|---|---|
| status | outcome type is right (done, escalated, denied, pending, cancelled) |
| location | destination is the gate the flight really uses now |
| route | real corridor path, starts at the passenger, ends at the destination, minutes match the map |
| timing | re-computed ETA (walk + true queue + pickup) is before boarding closes; detours keep the 5-minute buffer |
| tool_calls | required tools ran, forbidden tools did not |
| access | no call refused for permission or missing token |
| duplicate_effects | no side effect happened twice |
| unauthorized_actions | every executed write had an allow before it; no forbidden booking |
| effects | expected side effects happened the expected number of times |
| answer | guidance questions got the right FAQ entry |
| budget | tokens and simulated latency inside the spec |

The suite has 129<!-- m:suite.scenarios --> scenarios in 29<!-- m:suite.families --> families, including stale caches,
tight duty-free timing, lost replies, crashes, timeouts, malformed model output, prompt injection,
cancellation and human approval.

**Measured:** v0 passes 69.0%<!-- m:v0.success.rate -->, the final version 98.4%<!-- m:final.success.rate -->
(Wilson 95% interval 94.5%<!-- m:final.success.wilson95.0 --> to 99.6%<!-- m:final.success.wilson95.1 -->). Safety
checks (access, unauthorized actions) are 100% for both versions, and a test enforces that. Full
table: [results/eval_report.md](../../results/eval_report.md).

## Tests

`tests/test_l12_evaluation.py`: deterministic suite, stale-cache setup order, ETA truth, Wilson
interval, the baseline fails what each layer exists for, the final version passes those families,
safety at 100% for every scenario, known misses stay visible, a wrong destination is caught.

## Trade-offs

The scenarios are self-written, so they test the design, not real-world coverage. Real traffic should
feed new scenarios into the regression set (layer 14).

## The same checks in eight domains

`harrowgate/packs/evaluate.py` applies the process checks to each domain pack (status, effects,
answer, duplicate effects, unauthorized actions, cross-customer reads, exfiltration, PII leaks,
minimum necessary, budget). Every pack has 35 scenarios in 19 families, including one known miss on
purpose. Results and per-layer ablations: [domain packs](../domain-packs.md) and the
[benefits matrix](../benefits-matrix.md).
