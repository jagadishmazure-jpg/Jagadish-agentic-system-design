# ADR 0008: Use cases as domain packs on one engine

**Status:** accepted

**Context.** The design should be shown to carry over to other industries without eight copies of the
risky code.

**Decision.** A pack is records, write tools with compensations, a `plan()` that proposes writes and an
`authority()` that decides them. The shared engine owns understanding, identity-checked reads,
freshness, authorisation, idempotent execution, sagas, masking and audit. Each pack is evaluated on
35 scenarios from shared families, with per-layer ablations. Priority order: retail, mortgage,
insurance, healthcare (the same fictional organisations as the agentic data layer repo), then banking,
IT service desk and logistics.

**Consequences.** A new domain is one file. Because the families are shared, per-layer numbers are
identical across packs by design: they show what each layer prevents, not how hard each industry is.
One known miss per pack stays visible.
