# ADR 0007: Seven production layers added (15-21)

**Status:** accepted

**Context.** Layers 1-14 cover how one agent decides and recovers. Reviewing what production agent
systems need beyond that gave twelve candidate topics: security threats, identity and access, cost and
model routing, guardrails and content safety, data governance and residency, human hand-off,
versioning and release, multi-tenancy, rate limits and backpressure, caching and freshness,
compliance and audit, and responsible AI. Twelve new layers would repeat each other.

**Decision.** Add seven layers, merging topics that share one control point:

| Layer | Covers | Why it is separate |
|---|---|---|
| 15 Security | prompt injection (direct and in records), tool poisoning, exfiltration, content guardrails, grounding | threats come from what the agent reads and sends |
| 16 Identity | on-behalf-of tokens, narrowing delegation, ownership checks, confused deputy | "who for" is a different question from "is it allowed" (layer 8) |
| 17 Routing and budgets | model tiers, cascade, per-tenant budgets | cost is a design input, not an afterthought |
| 18 Freshness | change events, versioned caches, answer cache keyed by document version | fixes the S025-S028 miss that age rules cannot |
| 19 Release | manifests, release gate, canary, rollback, pinned runs | the learning loop (14) needs a safe way out |
| 20 Tenancy | tenant keys, rate limits, queue caps, fair share, kill switch | rate limits and backpressure only matter per tenant |
| 21 Governance | PII, minimum necessary, residency, retention, hash-chained audit, explanations, responsible-AI parity, human hand-off notes | all are "prove what data was used and why" |

**Consequences.** Each layer has a module, tests, a page and an ablation in every domain pack, so its
value is measured rather than claimed. Content safety is pattern-based here; a classifier is Planned.
