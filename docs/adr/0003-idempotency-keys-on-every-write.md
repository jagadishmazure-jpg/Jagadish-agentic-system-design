# ADR 0003: Idempotency keys on every write

**Status:** accepted (released by the learning loop as v3)

**Context.** Retries after lost replies and resumes after crashes repeated messages and bag moves in v0.

**Decision.** Key = run id + step + tool + hash of arguments, sent with every write. The tool server
stores results by key and replays them.

**Consequences.** Duplicate side effects went to zero on the suite. Providers must store keys with an
expiry.
