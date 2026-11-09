# Threat model

Scope: the assistant, its tool server, policy layer, executor and the Azure hosting in
`infra/`. Data is synthetic. Method: STRIDE per component, then the OWASP Top 10 for LLM applications.

```mermaid
flowchart LR
    U([Passenger]) -->|Entra ID| API[API / Container App]
    API --> AG[Agents]
    AG --> TS[Tool server]
    AG -->|proposal| POL[Policy]
    POL -->|signed allow| EX[Executor] --> TS
    TS --> SOR[(Systems of record)]
    API --> M[Microsoft Foundry model]
    subgraph Trust boundary: model output is untrusted
        M
    end
```

## STRIDE

| Threat | Example | Control | Where |
|---|---|---|---|
| Spoofing | caller pretends to be another passenger | Entra ID on the API; passenger id validated; orders checked against the profile | `infra/`, `api.py`, `context.py` |
| Tampering | agent edits a proposal after approval | token is an HMAC over the exact tool + arguments | `policy.py`, `tools.py` |
| Repudiation | "the system rebooked me without asking" | audit record with rule and approver for every write; trace spans | `actions.py`, `observability.py` |
| Information disclosure | traces or replies leak names, emails, other passengers | masking, keyed pseudonyms, own-orders only, replies carry no PII | `observability.py`, `context.py`, `api.py` |
| Denial of service | runaway agent loop or retry storm | budgets (calls, tokens, latency), 6-step investigation cap, bounded retries, body size limit | `runtime.py`, `agents.py`, `api.py` |
| Elevation of privilege | agent calls the booking tool directly | agents hold read tools only; tool server refuses writes without a policy token | `agents.py`, `tools.py` |

## OWASP LLM Top 10 (2025)

| Risk | Control |
|---|---|
| LLM01 Prompt injection | input guard flags instruction-like text; policy denies bookings for flagged requests; tests in `test_l08_policy.py` |
| LLM02 Sensitive information disclosure | masked traces, own-orders boundary, no PII in replies |
| LLM03 Supply chain | standard library only at run time; pinned dev tools; Dependabot; SHA-pinned actions |
| LLM04 Data and model poisoning | the model only extracts intents into a schema; facts come from systems of record |
| LLM05 Improper output handling | strict schema (enums, no extra keys, no NaN), one repair, then escalate |
| LLM06 Excessive agency | read-only agents, external policy, human approval for fare differences, refunds out of scope |
| LLM07 System prompt leakage | no secrets in prompts; guard flags "system prompt" requests |
| LLM08 Vector and embedding weaknesses | retrieval only over a fixed, reviewed FAQ set |
| LLM09 Misinformation | answers about gates and bags come from tools, not the model; process evaluation |
| LLM10 Unbounded consumption | token, call and latency budgets; small model capacity cap in IaC |

## Residual risks

- The input guard is pattern based and can be evaded; the real protection is that policy, not the
  model, controls actions.
- Time-based freshness misses changes inside the window (known miss, Planned fix).
- Container-local SQLite loses journey state if the replica is replaced (Planned: managed database).
