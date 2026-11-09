"""Layer 7 - Action design: three classes of action, three levels of ceremony.

| Class  | Examples                               | What must happen before it runs                         |
|--------|----------------------------------------|---------------------------------------------------------|
| read   | flight status, route, bag trace         | nothing - free to call, still traced                    |
| write  | message, gate delivery, bag reroute     | validate -> policy allow -> execute -> log              |
| commit | rebooking                               | validate -> policy (often a human) -> idempotent execute|

`ActionExecutor` is the only principal allowed to run writes and commits. It refuses anything that
has no allow decision, attaches an idempotency key so a retry can never act twice, and appends an
audit record with masked identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .observability import Tracer
from .policy import Decision, PolicyEngine, Proposal, Verdict
from .runtime import ToolClient, idempotency_key
from .tools import REGISTRY, validate_args


class NotAuthorized(Exception):
    pass


@dataclass
class ActionResult:
    status: str  # done | denied | pending_approval | rejected
    result: dict | None
    decision: Decision


@dataclass
class ActionExecutor:
    client: ToolClient
    policy: PolicyEngine
    tracer: Tracer
    use_idempotency: bool = True
    audit: list[dict] = field(default_factory=list)

    def execute(self, p: Proposal, decision: Decision, run_id: str, step: str) -> dict:
        spec = REGISTRY[p.tool]
        if decision.verdict is not Verdict.ALLOW or not self.policy.verify(decision.token or "", p.call()):
            raise NotAuthorized(f"{p.tool} has no valid allow decision")
        if spec.action_class == "read":
            raise NotAuthorized("reads are not executed through the action layer")
        key = idempotency_key(run_id, step, p.tool, p.arguments) if self.use_idempotency else None
        result = self.client.call("executor", p.tool, p.arguments, token=decision.token, idem_key=key)
        self.audit.append({"tool": p.tool, "class": spec.action_class, "agent": p.agent, "rule": decision.rule,
                           "approver": decision.approver, "idem_key": key})
        self.tracer.span("state", f"audit:{p.tool}", rule=decision.rule, approver=decision.approver)
        return result

    def propose(self, p: Proposal, run_id: str, step: str, approver=None) -> ActionResult:
        """Validate, ask policy, ask a human if required, then execute."""
        problems = validate_args(REGISTRY[p.tool], p.arguments)
        if problems:
            d = Decision(Verdict.DENY, "V0-invalid", "; ".join(problems))
            self.tracer.span("policy", p.tool, decision="deny", rule=d.rule)
            return ActionResult("rejected", None, d)
        d = self.policy.decide(p)
        self.tracer.span("policy", p.tool, decision=d.verdict.value, rule=d.rule, agent=p.agent, reason=d.reason)
        if d.verdict is Verdict.NEEDS_APPROVAL:
            answer = approver(p, d) if approver else None
            if answer is None:
                return ActionResult("pending_approval", None, d)
            d = self.policy.record_approval(p, d, "duty-manager", answer == "approve")
            self.tracer.span("policy", p.tool, decision=d.verdict.value, rule=d.rule, approver="duty-manager")
        if d.verdict is Verdict.DENY:
            return ActionResult("denied", None, d)
        return ActionResult("done", self.execute(p, d, run_id, step), d)

    def propose_only(self, p: Proposal, approver=None) -> ActionResult:
        """Get a decision (and a human answer if needed) without executing - used before a saga starts."""
        problems = validate_args(REGISTRY[p.tool], p.arguments)
        if problems:
            return ActionResult("rejected", None, Decision(Verdict.DENY, "V0-invalid", "; ".join(problems)))
        d = self.policy.decide(p)
        self.tracer.span("policy", p.tool, decision=d.verdict.value, rule=d.rule, agent=p.agent, reason=d.reason)
        if d.verdict is Verdict.NEEDS_APPROVAL:
            answer = approver(p, d) if approver else None
            if answer is None:
                return ActionResult("pending_approval", None, d)
            d = self.policy.record_approval(p, d, "duty-manager", answer == "approve")
            self.tracer.span("policy", p.tool, decision=d.verdict.value, rule=d.rule, approver="duty-manager")
        return ActionResult("allowed" if d.verdict is Verdict.ALLOW else "denied", None, d)

    def run_allowed(self, p: Proposal, run_id: str, step: str) -> dict:
        """Decide and execute; raise if policy does not allow (lets a saga treat it as a failed step)."""
        res = self.propose(p, run_id, step)
        if res.status != "done":
            raise NotAuthorized(f"{p.tool}: {res.status} ({res.decision.rule})")
        return res.result
