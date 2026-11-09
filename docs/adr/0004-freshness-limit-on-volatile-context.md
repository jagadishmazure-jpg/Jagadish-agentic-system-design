# ADR 0004: Freshness limit on volatile context

**Status:** accepted (released as v1)

**Context.** Cached flight records sent passengers to old gates.

**Decision.** Context fields carry source and age. Gate and status older than 5 minutes are refetched.

**Consequences.** Fixes most stale cases at the cost of a few extra reads. Changes inside the window
were still missed; change events fixed them in v4 (ADR 0007, layer 18).
