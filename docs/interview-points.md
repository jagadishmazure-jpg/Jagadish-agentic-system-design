# Interview points

Short questions and answers per layer, in plain words, with where to point in the code.

## Overall

**Q: Walk me through the system in one minute.**
A passenger message is checked by an input guard, turned into intents by a model with a strict schema,
and mapped to a fixed workflow. Four agents with read-only tools build small context packets and
propose actions. A policy layer decides allow, deny or ask a human; only an executor acts, with
idempotency keys. Every step is checkpointed and traced. Evaluation checks the process, and a learning
loop fixes the most common failure and releases only without regressions.

**Q: What result can you show?**
On 129<!-- m:suite.scenarios --> synthetic scenarios, the loop took v0 from 69.0%<!-- m:v0.success.rate --> to
98.4%<!-- m:final.success.rate -->, with zero duplicate side effects and zero unauthorized actions. The rest are known
misses I kept visible. The same engine runs eight fictional domains (airport, grocer, lender, insurer,
hospital, bank, IT desk, carrier): 272<!-- p:totals.passed --> of 280<!-- p:totals.scenarios --> scenarios pass with all 21 layers on,
48<!-- p:totals.v0_passed --> with them off.

## 1. Requirements
**Q: Why a typed spec?** So rules are checked, not just read. A test fails if a tool has no authority rule.
**Q: Who decides authority?** The business. The spec records it per tool: agent, confirm, human or never.

## 2. Orchestration
**Q: Why not let the model plan?** Known paths are cheaper and testable as code. The model only extracts intents.
**Q: Give an ordering rule.** Resolve a gate change before planning duty-free, and check time-to-boarding before any detour.

## 3. Agent boundaries
**Q: How did you pick four agents?** By data ownership and authority: journey, baggage, flight planning, airport info.
**Q: Where is the only agent loop and why?** Lost bags: the next step depends on what the last scan showed. Capped at 6 steps.

## 4. Context
**Q: What goes wrong with "send everything"?** Cost, latency and hidden stale data. Packets here are 96.2%<!-- m:final.context.reduction --> smaller.
**Q: How do you handle stale data?** Each field carries source and age; volatile data older than 5 minutes is refetched.

## 5. State and memory
**Q: Name the four kinds.** Knowledge, context, memory (preferences with consent and expiry), journey state (durable).
**Q: Can memory override a fact?** No, and a test proves it.

## 6. Knowledge
**Q: Graph or vectors?** By question shape: linked questions go to the graph, single facts to the database, policy to retrieval.
**Q: Example of a multi-hop question?** "My gate changed, what about my bag?" passenger -> flight -> gate -> pier -> bag area.

## 7. Actions
**Q: Read vs write vs commit?** Reads are free; writes are validated, allowed, keyed and logged; commits may need a human.
**Q: How do you stop double actions?** Idempotency keys built from run, step, tool and arguments.

## 8. Authority
**Q: Why can't the agent call the booking tool?** It only has read tools. Writes need a policy-signed token bound to the exact call.
**Q: What if the agent lies about the fare?** Policy reads fares from the system of record.
**Q: Prompt injection?** The guard marks the request; policy then denies bookings and seat holds.

## 9. Interaction
**Q: When do you use code instead of a model?** Any maths on known facts: ETAs, buffers, fare differences.
**Q: How do agents talk?** Typed handoff envelopes with references, not shared prompts.
**Q: Is it real MCP?** MCP-style: same method names and schemas over an in-process transport.

## 10. Runtime
**Q: What if a tool times out?** Up to 3 attempts with exponential backoff, then escalate.
**Q: And a crash?** A checkpoint after every step; a new process resumes from the last one.

## 11. Recovery
**Q: How do you undo a half-done rebooking?** A saga: hold seat, then rebook; if rebook fails, release the seat.
**Q: Lost reply from a tool?** Retry with the same key; the server replays the stored result.

## 12. Evaluation
**Q: Why process over outcome?** A correct-sounding answer can hide a wrong gate or a duplicate message. 11 checks look at both.
**Q: How sure are you of 98.4%?** Wilson interval 94.5%<!-- m:final.success.wilson95.0 --> to 99.6%<!-- m:final.success.wilson95.1 --> on a self-written suite: a regression check, not a benchmark.

## 13. Observability
**Q: How do you find root cause?** Context spans store data age; compare with when the gate really changed: that is stale context.
**Q: Privacy in traces?** Masked names and emails, keyed pseudonyms for IDs.

## 14. Learning
**Q: How do you avoid fixing one thing and breaking another?** Retest the whole suite; release only if success rises, safety stays 100% and no regression-set scenario breaks.
**Q: What is still failing?** A parser word clash and a tokenisation miss in the airport suite, and in every domain pack a corrected reference ("not X, I meant Y") read wrongly. All kept as tests. The gate change inside the freshness window is fixed by change events (v4).

## 15. Security
**Q: Your agent reads customer notes. What stops "ignore the rules" in a note?** Content is scanned and quoted as data, and more importantly the rules live outside the agent and read the system of record. Turning the security layer off shows attacks followed in every domain suite.
**Q: What is tool poisoning?** A tool's description changes after review. Tools are pinned by a hash of name, description and schema; drift makes the tool unavailable until re-reviewed.
**Q: How does data leave without a breach?** Through a normal email or link. An egress guard allows only internal domains and the requester's own channel, and refuses secrets and card numbers.

## 16. Identity
**Q: What is a confused deputy?** An agent with broad rights doing what a caller asks with them. Tokens carry the person, the agent and narrowed scopes; the tool server checks record ownership.
**Q: Can delegation widen access?** No: `delegate()` only narrows scope, and a test proves it.

## 17. Routing and budgets
**Q: How did you cut cost?** Rules as code, templates, small context, small model first with a cascade on schema failure: 87.5%<!-- p:totals.cost_cut_min --> to 93.7%<!-- p:totals.cost_cut_max --> lower simulated cost per request at the same pass rate, under assumed prices.
**Q: What stops a runaway bill?** A budget per tenant: degrade to the small tier, then stop and hand to a person.

## 18. Freshness
**Q: When is a cached answer wrong?** When the source changed after you cached it. Change events evict; the age limit is a backstop; answer caches key on document version.

## 19. Release
**Q: How do you ship a prompt change?** As a manifest with a content-hash id. The gate refuses any drop in success, any new safety failure, or any lost passing scenario; canary buckets are stable per customer; in-flight runs stay on their manifest.

## 20. Multi-tenancy
**Q: One tenant floods you. Then what?** Token bucket per tenant, queue cap, shed low priority first, fair share between tenants, kill switch per tenant. In the simulation quiet tenants stay fully served.

## 21. Governance and responsible AI
**Q: How do you prove the agent did not use protected data?** Minimum-necessary field lists remove protected fields before any decision, a parity test flips only protected fields and checks the decision does not change, and the audit log is hash-chained.
**Q: HIPAA-style or fair-lending concerns?** Design notes per domain in the domain packs page; they are engineering controls, not legal advice.

## Domains, cost, ROI, cloud
**Q: Why packs instead of eight agents?** The risky parts (permissions, idempotency, undo, privacy, audit) are shared and tested once; a pack adds only records, writes and rules.
**Q: Is the ROI real?** No. It is a transparent model with every input labelled ASSUMED and measured containment from the synthetic suite. It shows how to reason, not a client result.
**Q: Why cloud-neutral?** The core imports no cloud SDK; a model port has adapters for Microsoft Foundry (primary), AWS, Google Cloud and a self-hosted OpenAI-compatible server. Hosting is chosen by cost, data location and team skills.
