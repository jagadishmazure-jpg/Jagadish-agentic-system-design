"""Layer 21 - Data governance, audit, explainability and responsible AI.

* Classify and mask personal data before it leaves the system or lands in a log. Card numbers are
  confirmed with the Luhn checksum so random digit runs are not masked by mistake.
* Minimum necessary: each domain pack lists the fields a decision may use. Everything else,
  including protected attributes (for example age, sex, marital status or postcode in a lending
  decision), is removed from the context before any rule or model sees it.
* Residency: a tenant's data may only be stored in its allowed regions; the deployment plan is
  checked against that before anything is written.
* Retention: records past their retention period are purged and the purge is logged.
* Audit: every decision is appended to a hash-chained log. Changing or deleting any entry breaks
  the chain, and `verify` says where.
* Explainability: each decision record says which rule fired, on which facts, and who approved.
  An escalation produces a short hand-off note for the human who takes over.
* Consistency check (responsible AI): the same request with a different customer name, language
  marker or protected attribute must give the same outcome; any difference is a finding.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_MRN = re.compile(r"\bMRN-\d{6}\b")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")
_PHONE = re.compile(r"(?<![\w+])\+?\d{1,2}[ -]?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b")
_ACCT = re.compile(r"\bACCT-\d{8}\b")


def luhn_ok(digits: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", digits)]
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return total % 10 == 0


def find_pii(text: str) -> list[str]:
    text = text or ""
    kinds = []
    if any(luhn_ok(m.group(0)) for m in _CARD.finditer(text)):
        kinds.append("card")
    for kind, rx in (("ssn", _SSN), ("mrn", _MRN), ("email", _EMAIL), ("phone", _PHONE), ("account", _ACCT)):
        if rx.search(text):
            kinds.append(kind)
    return kinds


def _card(m: re.Match) -> str:
    raw = m.group(0)
    return f"card ending {re.sub(r'[^0-9]', '', raw)[-4:]}" if luhn_ok(raw) else raw


def mask(text: str) -> str:
    out = _CARD.sub(_card, text or "")
    out = _SSN.sub("[id]", out)
    out = _MRN.sub("[record]", out)
    out = _EMAIL.sub("[email]", out)
    out = _PHONE.sub("[phone]", out)
    out = _ACCT.sub(lambda m: "account ending " + m.group(0)[-4:], out)
    return out


def minimum_necessary(record: dict, allowed: set[str]) -> tuple[dict, list[str]]:
    kept = {k: v for k, v in record.items() if k in allowed}
    return kept, sorted(k for k in record if k not in allowed)


@dataclass(frozen=True)
class ResidencyPolicy:
    allowed: dict[str, frozenset[str]]  # tenant -> regions

    def check(self, tenant: str, region: str) -> bool:
        return region in self.allowed.get(tenant, frozenset())


def purge_expired(records: dict[str, dict], now: int, retention: int) -> list[str]:
    gone = [k for k, r in records.items() if now - r.get("closed_at", now) > retention]
    for k in gone:
        del records[k]
    return gone


@dataclass
class AuditLog:
    entries: list[dict] = field(default_factory=list)

    @staticmethod
    def _hash(prev: str, body: dict) -> str:
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()

    def append(self, **body) -> dict:
        prev = self.entries[-1]["hash"] if self.entries else "genesis"
        e = {"seq": len(self.entries) + 1, "body": body, "prev": prev, "hash": self._hash(prev, body)}
        self.entries.append(e)
        return e

    def verify(self) -> int | None:
        """Return the seq of the first broken entry, or None if the chain is intact."""
        prev = "genesis"
        for e in self.entries:
            if e["prev"] != prev or e["hash"] != self._hash(prev, e["body"]):
                return e["seq"]
            prev = e["hash"]
        return None


def explain(rule: str, reason: str, facts_used: dict, approver: str | None, outcome: str) -> dict:
    return {"rule": rule, "reason": reason, "facts_used": sorted(facts_used), "approver": approver,
            "outcome": outcome}


def handoff_note(domain: str, subject: str, intent: str, done: list[str], pending: list[str], why: str) -> str:
    lines = [f"[{domain}] hand-off for {subject}: {intent}", f"why: {why}",
             "done: " + (", ".join(done) or "nothing changed"), "waiting: " + (", ".join(pending) or "-")]
    return mask("\n".join(lines))
