# ADR 0006: SQLite checkpoints for durable execution

**Status:** accepted for the demo; superseded in production by a managed database (Planned)

**Context.** The runner must resume after a crash.

**Decision.** Store plan, step index, data and status per run in SQLite after every step.

**Consequences.** Simple and tested. A replaced container loses local state, so Azure needs a managed
store before real use.
