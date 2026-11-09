"""Layer 8 - Authority design: the agent proposes, a separate policy layer decides.

An agent never calls a side-effecting tool. It hands a `Proposal` to `PolicyEngine.decide`, which
returns allow, deny or needs-human-approval with the rule that fired. Only an allow (or an approval
recorded by a human) carries a signed token, and the tool server refuses write calls without one.

The policy reads facts (fares, seat counts, notification counts) from its own sources and never
trusts numbers written by the agent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from .requirements import SPEC, Authority, ProductSpec


class Verdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_APPROVAL = "needs_approval"


@dataclass(frozen=True)
class Proposal:
    agent: str
    tool: str
    arguments: dict
    reason: str
    passenger_id: str

    def call(self) -> dict:
        return {"tool": self.tool, "arguments": self.arguments}


@dataclass
class Decision:
    verdict: Verdict
    rule: str
    reason: str
    token: str | None = None
    approver: str | None = None


# Which agent may *propose* which side effect (reads are governed by the tool allowlist).
PROPOSERS: dict[str, set[str]] = {
    "send_notification": {"journey", "baggage", "flight_planning"},
    "schedule_gate_delivery": {"journey"},
    "reroute_bag": {"baggage"},
    "open_bag_case": {"baggage"},
    "hold_seat": {"flight_planning"},
    "release_seat": {"flight_planning"},
    "rebook_passenger": {"flight_planning"},
}


@dataclass
class PolicyEngine:
    facts: Callable[[str, dict], dict]  # (question, args) -> facts from systems of record
    spec: ProductSpec = SPEC
    key: bytes = field(default_factory=lambda: os.environ.get("HARROWGATE_POLICY_KEY", "").encode()
                       or secrets.token_bytes(32))
    untrusted_input: bool = False  # set per request by the input guard
    _sent: dict[str, int] = field(default_factory=dict)
    log: list[dict] = field(default_factory=list)

    def _sign(self, call: dict) -> str:
        return hmac.new(self.key, json.dumps(call, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    def verify(self, token: str, call: dict) -> bool:
        return bool(token) and hmac.compare_digest(token, self._sign(call))

    def _out(self, p: Proposal, verdict: Verdict, rule: str, reason: str) -> Decision:
        d = Decision(verdict, rule, reason, self._sign(p.call()) if verdict is Verdict.ALLOW else None)
        self.log.append({"agent": p.agent, "tool": p.tool, "verdict": verdict.value, "rule": rule})
        return d

    def decide(self, p: Proposal) -> Decision:
        rule = self.spec.authority_for(p.tool)
        if rule is None or rule.authority is Authority.NEVER:
            return self._out(p, Verdict.DENY, "R0-out-of-scope", f"{p.tool} is outside the system's authority")
        if rule.authority is Authority.AGENT:
            return self._out(p, Verdict.DENY, "R0-not-a-write", "read tools are not proposed")
        if p.agent not in PROPOSERS.get(p.tool, set()):
            return self._out(p, Verdict.DENY, "R1-wrong-agent", f"{p.agent} may not propose {p.tool}")
        if self.untrusted_input and p.tool in {"rebook_passenger", "hold_seat"}:
            return self._out(p, Verdict.DENY, "R2-untrusted-input",
                             "request contained instructions aimed at the assistant; a human must handle it")
        if p.tool == "send_notification":
            n = self._sent.get(p.passenger_id, 0)
            if n >= self.spec.constraint("C7"):
                return self._out(p, Verdict.DENY, "R3-message-cap", "notification cap reached for this request")
            self._sent[p.passenger_id] = n + 1
        if p.tool == "rebook_passenger":
            f = self.facts("rebook", p.arguments)
            if f["cabin_change"]:
                return self._out(p, Verdict.DENY, "R5-cabin", "cabin changes are not offered by the assistant")
            if f["seats_free"] <= 0 and not f["seat_held"]:
                return self._out(p, Verdict.DENY, "R5-no-seat", "no seat on the target flight")
            if f["fare_diff"] == 0:
                return self._out(p, Verdict.ALLOW, "R6-same-fare", "same destination, no fare difference")
            return self._out(p, Verdict.NEEDS_APPROVAL, "R7-fare-diff",
                             f"fare difference {f['fare_diff']} needs the {rule.approver_role}")
        return self._out(p, Verdict.ALLOW, "R4-confirm-and-log", rule.note or "validated write")

    def record_approval(self, p: Proposal, decision: Decision, approver: str, approved: bool) -> Decision:
        if decision.verdict is not Verdict.NEEDS_APPROVAL:
            raise ValueError("only needs_approval decisions take a human answer")
        if approved:
            out = Decision(Verdict.ALLOW, decision.rule, f"approved by {approver}", self._sign(p.call()), approver)
        else:
            out = Decision(Verdict.DENY, decision.rule, f"declined by {approver}", None, approver)
        self.log.append({"agent": p.agent, "tool": p.tool, "verdict": out.verdict.value, "rule": decision.rule,
                         "approver": approver})
        return out
