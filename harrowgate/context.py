"""Layer 4 - Context design: raw information -> context builder -> one packet per decision.

Each decision type declares the few facts it needs. The builder fetches only those, records where
each came from and how old it is, and refuses to use volatile data (gate, status) older than the
spec's limit when freshness checks are on. The trace shows the packet size next to the size of
"everything we could have sent", which is the overload this layer avoids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import world as W
from .llm import count_tokens
from .observability import Tracer
from .runtime import ToolClient
from .state import FlightCache, StateStore

DECISIONS: dict[str, tuple[str, ...]] = {
    "gate_route": ("flight", "location", "security_wait", "prefs"),
    "duty_free": ("flight", "location", "security_wait", "order"),
    "bag_check": ("flight", "bags"),
    "rebook": ("flight", "alternatives", "cabin"),
    "status_answer": ("flight",),
    "faq": ("question",),
}


@dataclass
class ContextPacket:
    decision: str
    fields: dict
    provenance: dict
    tokens: int
    raw_tokens: int

    @property
    def reduction(self) -> float:
        return 1 - self.tokens / self.raw_tokens if self.raw_tokens else 0.0


class ContextBuilder:
    def __init__(self, client: ToolClient, cache: FlightCache, store: StateStore, tracer: Tracer, now: int,
                 *, freshness_check: bool, max_age: int, raw_tokens: int, feed=None):
        self.client, self.cache, self.store, self.tracer = client, cache, store, tracer
        self.now, self.freshness_check, self.max_age, self.raw_tokens = now, freshness_check, max_age, raw_tokens
        self.feed = feed  # layer 18: when set, cached flights are evicted as soon as they change
        self._memo: dict[tuple, dict] = {}

    def read(self, caller: str, tool: str, args: dict) -> dict:
        """Read once per request; repeated identical reads come from the memo (no duplicate calls)."""
        key = (tool, tuple(sorted(args.items())))
        if key not in self._memo:
            self._memo[key] = self.client.call(caller, tool, args)
        return self._memo[key]

    def flight(self, caller: str, flight_id: str) -> dict:
        if self.feed is not None:
            evicted = self.cache.sync(self.feed)
            if evicted:
                self.tracer.span("state", "cache_evicted", evicted=evicted)
        entry = self.cache.get(flight_id)
        if entry is not None:
            age = self.now - entry.fetched_at
            if not self.freshness_check or age <= self.max_age:
                return {**entry.data, "source": "cache", "fetched_at": entry.fetched_at, "age": age}
        live = self.read(caller, "flight_status", {"flight_id": flight_id})
        self.cache.put(flight_id, live, live["fetched_at"])
        return {**live, "source": "live", "age": 0}

    def build(self, decision: str, caller: str, passenger_id: str, **extra) -> ContextPacket:
        needs = DECISIONS[decision]
        fields, prov = {}, {}
        profile = self.read(caller, "passenger_profile", {"passenger_id": passenger_id}) \
            if decision != "faq" else None
        flight_id = extra.get("flight_id") or (profile or {}).get("flight")
        if "flight" in needs:
            f = self.flight(caller, flight_id)
            fields["flight"] = {k: f[k] for k in ("flight_id", "gate", "dep", "boarding_close", "status", "dest")}
            prov["flight"] = {"source": f["source"], "fetched_at": f["fetched_at"], "age": f["age"]}
        if "location" in needs:
            fields["location"] = profile["location"]
            prov["location"] = {"source": "passenger_profile"}
        if "security_wait" in needs:
            if W.NODES[profile["location"]]["zone"] == "landside":
                fields["security_wait"] = {cp: self.read(caller, "security_wait", {"checkpoint": cp})["minutes"]
                                           for cp in ("SEC-1", "SEC-2")}
            else:
                fields["security_wait"] = {}
            prov["security_wait"] = {"source": "security_wait"}
        if "prefs" in needs:
            fields["prefs"] = {**profile["prefs"], **self.store.recall(passenger_id, self.now)}
            prov["prefs"] = {"source": "profile+memory"}
        if "order" in needs:
            oid = extra.get("order_id") or (profile["orders"][0] if profile["orders"] else None)
            if oid not in profile["orders"]:  # boundary B3: never read another passenger's order
                oid = None
            fields["order"] = self.read(caller, "order_status", {"order_id": oid}) if oid else None
            prov["order"] = {"source": "order_status"}
        if "bags" in needs:
            fields["bags"] = list(profile["bags"])
        if "alternatives" in needs:
            fields["alternatives"] = self.read(caller, "find_alternatives", {"flight_id": flight_id})["alternatives"]
        if "cabin" in needs:
            fields["cabin"] = profile["cabin"]
        if "question" in needs:
            fields["question"] = extra.get("question", "")
        tokens = count_tokens(json.dumps(fields))
        pkt = ContextPacket(decision, fields, prov, tokens, self.raw_tokens)
        fl = prov.get("flight", {})
        self.tracer.span("context", decision, fields=sorted(fields), tokens=tokens, raw_tokens=self.raw_tokens,
                         flight_source=fl.get("source"), flight_fetched_at=fl.get("fetched_at"),
                         flight_age=fl.get("age"))
        return pkt
