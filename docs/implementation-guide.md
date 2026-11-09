# Implementation guide

How to build your own agent with the same 21 layers. Work in this order; each step has a matching
module you can copy.

## 1. Write the spec first (layer 1)

Copy `harrowgate/requirements.py`. List outcomes with a metric, boundaries, numeric limits and an
authority level for **every** tool. Add `validate_spec` to your tests.

## 2. Model your world and tools (layers 6, 9)

- Put systems of record behind small, typed tool functions (`harrowgate/tools.py`).
- Mark each tool `read`, `write` or `commit`.
- Serve them through one tool server with per-caller allowlists and JSON schemas.
- Decide per question type: graph, database lookup or retrieval (`choose_store`).

## 3. Draw agent boundaries (layer 3)

Group tools by data ownership. Give agents read tools only. Keep maths and lookups as code. Allow a
model loop only where the next step truly depends on the last result, and cap it.

## 4. Fix the workflow (layer 2)

Have the model produce intents into a strict schema. Map intents to fixed step lists. Encode ordering
rules in `check_order` and test every combination.

## 5. Build the context layer (layer 4)

For each decision list the fields it needs. Record source and age. Set a freshness limit for volatile
data. Memoise reads per request.

## 6. Separate state (layer 5)

Knowledge read-only; memory with consent and expiry; journey state durable; context per decision.

## 7. Put authority outside the agent (layers 7, 8)

Agents create proposals. A policy engine returns allow / deny / needs-approval using its own facts and
signs allows. Only an executor calls write tools, with idempotency keys and an audit record.

## 8. Make it durable (layers 10, 11)

Checkpoint after each step. Retry transient errors with backoff and a cap. Add budgets and a cancel
token. Wrap multi-system changes in sagas with compensations.

## 9. Evaluate the process, trace everything, close the loop (layers 12-14)

- Write scenarios with expectations on status, location, tools, side effects and permissions.
- Trace input -> context -> decision -> tool -> state with masked identities.
- Name a root cause for each failure, fix the most common one, retest everything, and release only
  without regressions.

## Adapting to your domain

| Harrowgate | Your domain (examples) |
|---|---|
| gate change | address change, price change, schedule change |
| bag reroute | shipment reroute, ticket reassignment |
| duty-free time guard | any "is there time to do X before deadline Y" |
| rebooking with approval | refunds, credit limits, contract changes |

## Moving to Azure

See [deployment.md](deployment.md). Set `HARROWGATE_LLM=foundry`, keep key auth disabled on the
Microsoft Foundry resource, use a managed identity, and move journey state to a managed database.

## 10. Add the production layers (15-21)

Pin tool definitions by hash and allow-list egress (15); pass a delegated token on every read and
check ownership at the tool (16); route small model first with a per-tenant budget (17); evict caches
on change events (18); ship as a manifest through a release gate (19); rate limit and share fairly
between tenants (20); use minimum-necessary fields, mask PII and keep a hash-chained audit log (21).

## Adding a domain pack

1. Copy `harrowgate/packs/retail.py`. Set the organisation, reference prefix, records (fictional),
   the write tools and their compensations, and protected fields.
2. Write `plan()`: given the facts, propose writes. Write `authority()`: the rules that allow, deny
   or ask a named role, using only the system of record.
3. Register it in `harrowgate/packs/registry.py`. The 35 scenarios are generated from the shared
   families; add domain-specific ones if you need them.
4. Run `python scripts/run_packs.py`. The benefits matrix, cost, ROI and cloud pages regenerate.

## Choosing a cloud

Set `HARROWGATE_PROVIDER` and read [cloud-options.md](cloud-options.md). Keep the evaluation gate the
same on every provider: a new model or host is a release like any other (layer 19).
