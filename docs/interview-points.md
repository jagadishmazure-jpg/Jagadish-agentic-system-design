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
95.3%<!-- m:final.success.rate -->, with zero duplicate side effects and zero unauthorized actions. The rest are known
misses I kept visible.

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
**Q: How sure are you of 95.3%?** Wilson interval 90.2%<!-- m:final.success.wilson95.0 --> to 97.9%<!-- m:final.success.wilson95.1 --> on a self-written suite: a regression check, not a benchmark.

## 13. Observability
**Q: How do you find root cause?** Context spans store data age; compare with when the gate really changed: that is stale context.
**Q: Privacy in traces?** Masked names and emails, keyed pseudonyms for IDs.

## 14. Learning
**Q: How do you avoid fixing one thing and breaking another?** Retest the whole suite; release only if success rises, safety stays 100% and no regression-set scenario breaks.
**Q: What is still failing?** A gate change inside the freshness window, a parser word clash, and a tokenisation miss. All kept as tests.
