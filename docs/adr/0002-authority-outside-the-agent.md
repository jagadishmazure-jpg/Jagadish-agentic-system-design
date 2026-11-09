# ADR 0002: Authority sits outside the agent

**Status:** accepted

**Context.** An agent that both decides and acts can be steered by one bad parse or injected sentence.

**Decision.** Agents get read tools only and submit proposals. A policy engine decides with its own
facts and signs allows; an executor runs only signed calls; the tool server verifies the signature.

**Consequences.** Every write has a rule and an audit record. Policy changes need a release.
