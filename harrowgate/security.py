"""Layer 15 - Security: treat everything the model reads as untrusted, and check what leaves.

Three threats this layer handles in code, for every domain pack:

* Indirect prompt injection - instructions hidden in data the agent reads (a customer note, a
  document, a tool result). `scan_content` finds them; flagged text is removed from the context
  packet and the request is marked untrusted, so authority rules refuse risky writes.
* Tool poisoning and silent tool changes - a tool description or schema that changes after review.
  `ToolManifest` pins a hash of each reviewed tool definition (name, description, schema, action
  class); any drift blocks that tool until a person reviews it again.
* Data exfiltration - an agent tricked into sending data somewhere new. `EgressGuard` only lets
  messages go to the requester's own channel or allow-listed internal queues, and refuses outbound
  text that carries secrets or account numbers.

Pattern lists are deliberately small and visible; they are a tripwire, not the only defence. The
authority layer (8) and identity layer (16) still decide what may happen even if a scan misses.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

_INJECTION = [
    r"ignore (all |any |the )?(previous |prior |above )?(rules|instructions|policy|policies)",
    r"(you are|you're) now", r"system prompt", r"developer mode", r"disregard",
    r"approve (this|the|my)? ?(refund|claim|dispute|request|loan) (now|immediately|automatically)",
    r"without (any )?(approval|review|checks)", r"override (the )?(policy|rules|approval|limit)",
    r"(send|forward|email|copy) (all |the )?(account|card|patient|customer|policy)? ?(details|data|records|numbers)",
    r"<\s*(system|instructions?)\s*>", r"\bBEGIN (ADMIN|SYSTEM)\b",
]
_INJ_RX = re.compile("|".join(f"(?:{p})" for p in _INJECTION), re.I)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@([\w-]{1,63}(?:\.[\w-]{1,63}){1,8})")
_URL = re.compile(r"\bhttps?://([\w.-]{1,253})", re.I)
_SECRETISH = re.compile(r"\b(?:\d[ -]?){13,19}\b|\b(api[_-]?key|password|secret)\s*[:=]", re.I)


def scan_content(text: str) -> dict:
    """Look for instructions aimed at the assistant inside data. Returns a finding, never raises."""
    text = text or ""
    m = _INJ_RX.search(text)
    emails = [d.lower() for d in _EMAIL.findall(text)]
    urls = [d.lower() for d in _URL.findall(text)]
    return {"injection": bool(m), "match": m.group(0) if m else None, "emails": emails, "urls": urls}


def sanitize_fields(record: dict) -> tuple[dict, list[str]]:
    """Drop free-text fields that contain instructions; keep structured fields. Returns (clean, dropped)."""
    clean, dropped = {}, []
    for k, v in record.items():
        if isinstance(v, str) and scan_content(v)["injection"]:
            dropped.append(k)
            continue
        clean[k] = v
    return clean, dropped


def tool_fingerprint(spec) -> str:
    body = {"name": spec.name, "description": spec.description, "schema": spec.schema(),
            "class": spec.action_class}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


@dataclass
class ToolManifest:
    """Reviewed tool definitions, pinned by hash. A changed definition is blocked until re-reviewed."""

    pins: dict[str, str] = field(default_factory=dict)

    @classmethod
    def review(cls, registry: dict) -> ToolManifest:
        return cls({name: tool_fingerprint(spec) for name, spec in registry.items()})

    def drift(self, registry: dict) -> dict[str, str]:
        out = {}
        for name, spec in registry.items():
            if name not in self.pins:
                out[name] = "new tool, not reviewed"
            elif self.pins[name] != tool_fingerprint(spec):
                out[name] = "definition changed since review"
        for name in self.pins:
            if name not in registry:
                out[name] = "reviewed tool disappeared"
        return out

    def allowed(self, registry: dict) -> set[str]:
        bad = self.drift(registry)
        return {n for n in registry if n not in bad}


@dataclass
class EgressGuard:
    """Outbound messages may go only to the requester or to allow-listed internal queues."""

    internal_domains: frozenset[str] = frozenset()
    internal_queues: frozenset[str] = frozenset()
    blocked: list[dict] = field(default_factory=list)

    def check(self, recipient: str, requester: str, text: str) -> tuple[bool, str]:
        if recipient != requester and recipient not in self.internal_queues:
            dom = recipient.split("@")[-1].lower() if "@" in recipient else None
            if dom is None or dom not in self.internal_domains:
                self.blocked.append({"recipient": recipient, "reason": "recipient not allowed"})
                return False, "recipient is not the requester or an internal queue"
        if _SECRETISH.search(text or ""):
            self.blocked.append({"recipient": recipient, "reason": "secret or account number in text"})
            return False, "outbound text carries a secret or a full account number"
        found = scan_content(text)
        foreign = [d for d in found["emails"] + found["urls"] if d not in self.internal_domains]
        if foreign:
            self.blocked.append({"recipient": recipient, "reason": "outbound text links outside"})
            return False, "outbound text points to an outside address"
        return True, "ok"


def grounded(message: str, facts: dict) -> bool:
    """Output check: every number in a reply must appear in the facts it was built from."""
    nums = set(re.findall(r"\d+(?:\.\d+)?", message or ""))
    known = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(facts)))
    return nums <= known
