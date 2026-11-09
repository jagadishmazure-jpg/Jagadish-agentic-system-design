"""Layer 16 - Identity and access for agents.

Each agent has its own workload identity with a fixed set of scopes. When a request arrives, the
platform (not the model) mints a short-lived delegated token that names three things: the agent
acting, the person it acts for (the subject), and the scopes it may use. Tokens are signed, expire,
carry an audience (the tool gateway), and can only be narrowed when one agent hands work to another.

The tool gateway checks the token on every call and asks the system of record who owns the record
being touched. A token for customer A can never read or change customer B's record, even if the
model asks for it - the classic confused-deputy case.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field


class AccessDenied(Exception):
    pass


@dataclass(frozen=True)
class AgentIdentity:
    name: str
    scopes: frozenset[str]


@dataclass
class TokenIssuer:
    key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    audience: str = "tool-gateway"
    issued: int = 0

    def _sign(self, body: bytes) -> str:
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def mint(self, agent: AgentIdentity, subject: str, scopes: set[str], now: int, ttl: int = 15,
             tenant: str = "default", chain: tuple[str, ...] = ()) -> str:
        granted = sorted(set(scopes) & agent.scopes)  # never more than the agent itself holds
        claims = {"act": agent.name, "sub": subject, "scp": granted, "aud": self.audience, "exp": now + ttl,
                  "ten": tenant, "chain": list(chain) + [agent.name]}
        body = json.dumps(claims, sort_keys=True).encode()
        self.issued += 1
        return base64.urlsafe_b64encode(body).decode() + "." + self._sign(body)

    def verify(self, token: str, *, scope: str, now: int, audience: str | None = None) -> dict:
        try:
            b64, sig = token.rsplit(".", 1)
            body = base64.urlsafe_b64decode(b64.encode())
        except (ValueError, AttributeError) as e:
            raise AccessDenied("malformed token") from e
        if not hmac.compare_digest(sig, self._sign(body)):
            raise AccessDenied("bad signature")
        claims = json.loads(body)
        if claims["aud"] != (audience or self.audience):
            raise AccessDenied("wrong audience")
        if now > claims["exp"]:
            raise AccessDenied("token expired")
        if scope not in claims["scp"]:
            raise AccessDenied(f"scope {scope} not granted")
        return claims

    def delegate(self, token: str, to: AgentIdentity, scopes: set[str], now: int) -> str:
        """Hand work to another agent with the same subject and no more scope than the parent token."""
        b64 = token.rsplit(".", 1)[0]
        claims = json.loads(base64.urlsafe_b64decode(b64.encode()))
        self.verify(token, scope=claims["scp"][0] if claims["scp"] else "", now=now)
        narrowed = set(scopes) & set(claims["scp"])
        return self.mint(to, claims["sub"], narrowed, now, ttl=max(0, claims["exp"] - now), tenant=claims["ten"],
                         chain=tuple(claims["chain"]))


def check_ownership(claims: dict, owner: str | None) -> None:
    """The record's owner (from the system of record) must be the token's subject."""
    if owner is not None and owner != claims["sub"]:
        raise AccessDenied("record belongs to someone else")
