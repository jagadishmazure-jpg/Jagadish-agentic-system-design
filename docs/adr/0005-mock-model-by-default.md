# ADR 0005: Deterministic mock model by default

**Status:** accepted

**Context.** Tests and evaluation must be exact, free and offline.

**Decision.** `MockLLM` fills the same schemas a real model would. `FoundryLLM` sits behind
`HARROWGATE_LLM=foundry`, uses Entra ID tokens and the same validation.

**Consequences.** Results measure the system design, not model quality. Real-model numbers are not
reported until it is run.
