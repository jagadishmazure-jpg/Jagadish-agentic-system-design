"""Layer 13 - Observability: one trace per request, input -> context -> decision -> tool -> state.

Spans carry the facts needed to explain a failure later (data source and age, policy rule,
retry count, idempotency key), with passenger identity masked. `classify_root_cause` turns a
failed evaluation plus its trace into one named cause, which the learning loop (layer 14) counts.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import os
import re
from dataclasses import dataclass, field

SPAN_KINDS = ("input", "guard", "llm", "route", "handoff", "context", "decision", "policy",
              "tool", "state", "saga", "runtime", "output")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")  # bounded: no slow backtracking
_PID = re.compile(r"\bP-\d{4}\b")


def _trace_key() -> bytes:
    # Dev default keeps tests deterministic; production reads the key from Key Vault via env.
    return os.environ.get("HARROWGATE_TRACE_KEY", "dev-only-trace-key").encode()


def pseudonym(value: str) -> str:
    return "anon-" + hmac.new(_trace_key(), value.encode(), hashlib.sha256).hexdigest()[:10]


@dataclass
class Span:
    trace_id: str
    span_id: int
    parent: int | None
    kind: str
    name: str
    attrs: dict
    sim_ms: int = 0
    status: str = "ok"
    error: str | None = None


@dataclass
class Tracer:
    trace_id: str
    mask_terms: tuple[str, ...] = ()
    spans: list[Span] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _stack: list[int] = field(default_factory=list)

    def mask(self, value):
        if isinstance(value, dict):
            return {k: self.mask(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.mask(v) for v in value]
        if not isinstance(value, str):
            return value
        out = _EMAIL.sub("[email]", value)
        out = _PID.sub(lambda m: pseudonym(m.group(0)), out)
        for term in self.mask_terms:
            out = out.replace(term, "[name]")
        return out

    def span(self, kind: str, name: str, sim_ms: int = 0, status: str = "ok", error: str | None = None,
             **attrs) -> Span:
        if kind not in SPAN_KINDS:
            raise ValueError(f"unknown span kind {kind}")
        s = Span(self.trace_id, next(self._ids), self._stack[-1] if self._stack else None, kind, name,
                 self.mask(attrs), sim_ms, status, self.mask(error) if error else None)
        self.spans.append(s)
        return s

    def push(self, span: Span) -> None:
        self._stack.append(span.span_id)

    def pop(self) -> None:
        self._stack.pop()

    @property
    def sim_ms(self) -> int:
        return sum(s.sim_ms for s in self.spans)

    def of_kind(self, kind: str) -> list[Span]:
        return [s for s in self.spans if s.kind == kind]

    def tool_calls(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "tool" and s.attrs.get("attempt_final", True)]

    def render(self, limit: int | None = None) -> str:
        lines = []
        depth = {}
        for s in self.spans[:limit]:
            d = depth.get(s.parent, -1) + 1 if s.parent else 0
            depth[s.span_id] = d
            flag = "" if s.status == "ok" else f" [{s.status}]"
            lines.append(f"{'  ' * d}{s.kind:<8} {s.name}{flag}")
        return "\n".join(lines)


ROOT_CAUSES = ("stale_context", "unsafe_timing", "duplicate_side_effect", "tool_failure", "budget_exceeded",
               "policy_block", "unauthorized_action", "wrong_outcome")


def classify_root_cause(tracer: Tracer, failed: list[str], truth: dict) -> str | None:
    """Name the single most likely cause of a failed scenario.

    `failed` holds the names of failed evaluation checks; `truth` holds world facts the system
    could not see at decision time (for example when the gate really changed).
    """
    if not failed:
        return None
    if "unauthorized_actions" in failed:
        return "unauthorized_action"
    if "duplicate_effects" in failed:
        return "duplicate_side_effect"
    if "location" in failed:
        for s in tracer.of_kind("context"):
            fetched = s.attrs.get("flight_fetched_at")
            if fetched is not None and truth.get("gate_updated_at", -1) > fetched:
                return "stale_context"
    if "timing" in failed:
        return "unsafe_timing"
    if any(s.kind == "runtime" and s.name == "budget_exceeded" for s in tracer.spans):
        return "budget_exceeded"
    if any(s.kind == "tool" and s.status == "error" and s.attrs.get("attempt_final") for s in tracer.spans):
        return "tool_failure"
    if any(s.kind == "policy" and s.attrs.get("decision") == "deny" for s in tracer.spans):
        return "policy_block"
    return "wrong_outcome"
