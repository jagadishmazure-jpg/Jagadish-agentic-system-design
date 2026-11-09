# ADR 0001: Fixed workflows over model planning

**Status:** accepted

**Context.** Airport requests follow a small number of known paths. Ordering carries business rules
(gate before duty-free; time check before detour).

**Decision.** The model only extracts intents into a schema. A deterministic router builds the plan
from fixed workflows.

**Consequences.** Plans are testable and cheap. Unplanned requests fall back to FAQ or a human. New
paths need code and tests.
