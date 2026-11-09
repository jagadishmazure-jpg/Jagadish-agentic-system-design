# ADR 0009: Simulated cost model with assumed prices

**Status:** accepted

**Context.** Cost must be shown per layer and per domain without calling a paid model.

**Decision.** Count tokens per step from the simulated model, price them with two assumed tiers
(small $0.0003 and large $0.003 per 1K tokens, dated 2026-11-09), and compare a full build with an
unoptimised build that turns off context trimming, routing, the answer cache, templates, rules as code
and batched reads. Each optimisation is also switched on alone.

**Consequences.** Before/after numbers are measured on the suite but priced with assumptions; the
docs say so. The simulated model is equally right on both tiers, which flatters the unoptimised
build's accuracy and understates the real value of a cascade check.
