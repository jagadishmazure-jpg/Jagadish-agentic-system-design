"""Layer 6 - Knowledge design: pick the store by the shape of the question.

* Relational questions ("my gate changed - what happens to my bag?") need a walk across linked
  facts, so they go to a small knowledge graph.
* Single facts about one record ("what gate is SK204?") go to the database tool.
* Open policy questions ("can I take liquids?") go to retrieval over written guidance.

The retriever is a hybrid of BM25 keyword scores and a hashed character-trigram vector, so it
runs offline with no embedding model.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import world as W

FAQ_PATH = Path(__file__).resolve().parent.parent / "data" / "faq.json"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an the is are to of in on at for my i me can do does what how where when it and or be with "
                  "from this that you your will if as by".split())


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


# ---------------------------------------------------------------- knowledge graph
class KnowledgeGraph:
    """Triples (subject, relation, object) built from the live world plus static airport facts."""

    def __init__(self) -> None:
        self.out: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def add(self, s: str, rel: str, o: str) -> None:
        self.out[s].append((rel, o))

    def objects(self, s: str, rel: str) -> list[str]:
        return [o for r, o in self.out.get(s, []) if r == rel]

    def one(self, s: str, rel: str) -> str | None:
        objs = self.objects(s, rel)
        return objs[0] if objs else None

    def walk(self, start: str, relations: list[str]) -> list[str]:
        """Follow a chain of relations; returns the path of nodes or stops where the chain breaks."""
        path, node = [start], start
        for rel in relations:
            node = self.one(node, rel)
            if node is None:
                break
            path.append(node)
        return path

    @property
    def size(self) -> int:
        return sum(len(v) for v in self.out.values())

    @classmethod
    def from_world(cls, world: W.World, flights: dict[str, dict] | None = None) -> KnowledgeGraph:
        kg = cls()
        flights = flights if flights is not None else world.flights
        for pier in W.PIER_GATES:
            kg.add(f"PIER-{pier}", "SERVED_BY", f"MU-{pier}")
        for node, meta in W.NODES.items():
            if meta["kind"] == "gate":
                kg.add(node, "IN_PIER", f"PIER-{meta['pier']}")
        for fid, f in flights.items():
            kg.add(fid, "DEPARTS_FROM", f["gate"])
            kg.add(fid, "FLIES_TO", f["dest"])
        for pid, p in world.passengers.items():
            kg.add(pid, "BOOKED_ON", p["flight"])
            for b in p["bags"]:
                kg.add(pid, "OWNS_BAG", b)
            for o in p["orders"]:
                kg.add(pid, "HAS_ORDER", o)
        for bid, b in world.bags.items():
            kg.add(bid, "CHECKED_ON", b["flight"])
            kg.add(bid, "LOCATED_IN", b["area"])
        for oid, o in world.orders.items():
            kg.add(oid, "HELD_AT", o["shop"])
        return kg


def gate_change_impact(kg: KnowledgeGraph, passenger_id: str, now: int, dep: int) -> list[dict]:
    """For each bag: is it in the make-up area that serves the flight's (new) gate, and can it move in time?"""
    flight = kg.one(passenger_id, "BOOKED_ON")
    chain = kg.walk(flight, ["DEPARTS_FROM", "IN_PIER", "SERVED_BY"])
    needed_area = chain[-1] if len(chain) == 4 else None
    out = []
    for bag in kg.objects(passenger_id, "OWNS_BAG"):
        area = kg.one(bag, "LOCATED_IN")
        if needed_area is None or area is None:
            out.append({"bag": bag, "status": "unknown", "chain": chain})
            continue
        move = W.bag_transfer_minutes(area, needed_area)
        cutoff = dep - W.BAG_CUTOFF_BEFORE_DEP
        status = "ok" if move == 0 else ("move" if now + move <= cutoff else "too_late")
        out.append({"bag": bag, "from": area, "to": needed_area, "move_min": move, "status": status,
                    "chain": chain})
    return out


# ---------------------------------------------------------------- hybrid retrieval
def _trigram_vec(text: str, dim: int = 512) -> dict[int, float]:
    import zlib
    t = f"  {text.lower()}  "
    counts = Counter(zlib.crc32(t[i:i + 3].encode()) % dim for i in range(len(t) - 2))
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


class FaqRetriever:
    def __init__(self, docs: list[dict] | None = None, k1: float = 1.4, b: float = 0.75, alpha: float = 0.7):
        self.docs = docs if docs is not None else json.loads(FAQ_PATH.read_text())
        self.k1, self.b, self.alpha = k1, b, alpha
        self.doc_tokens = [tokens(d["title"] + " " + d["title"] + " " + d["text"]) for d in self.docs]
        self.avgdl = sum(len(t) for t in self.doc_tokens) / len(self.doc_tokens)
        df = Counter(t for toks in self.doc_tokens for t in set(toks))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.vecs = [_trigram_vec(d["title"] + " " + d["text"]) for d in self.docs]

    def _bm25(self, q: list[str], i: int) -> float:
        tf = Counter(self.doc_tokens[i])
        dl = len(self.doc_tokens[i])
        s = 0.0
        for t in q:
            if t in tf:
                s += self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: str, k: int = 3) -> list[dict]:
        q = tokens(query)
        bm = [self._bm25(q, i) for i in range(len(self.docs))]
        top = max(bm) or 1.0
        qv = _trigram_vec(query)
        scored = []
        for i, d in enumerate(self.docs):
            cos = sum(qv.get(k_, 0.0) * v for k_, v in self.vecs[i].items())
            scored.append((self.alpha * bm[i] / top + (1 - self.alpha) * cos, d))
        scored.sort(key=lambda x: -x[0])
        return [{"id": d["id"], "title": d["title"], "text": d["text"], "score": round(s, 4)} for s, d in scored[:k]]


# ---------------------------------------------------------------- choose the store
_ENTITY_WORDS = {
    "gate": "gate", "bag": "bag", "bags": "bag", "luggage": "bag", "suitcase": "bag", "flight": "flight",
    "order": "order", "duty": "order", "pier": "gate", "connection": "flight",
}
_RELATIONAL_CUES = ("what about", "what happens", "affect", "still", "because", "now that", "will my", "after")
_RECORD = re.compile(r"\b([A-Z]{2}\d{3}|BG-\d{4}|DF-\d{4})\b")


def choose_store(question: str) -> tuple[str, str]:
    """Return (store, reason) where store is 'graph', 'database' or 'retrieval'."""
    low = question.lower()
    kinds = {_ENTITY_WORDS[t] for t in _TOKEN.findall(low) if t in _ENTITY_WORDS}
    if len(kinds) >= 2 and any(c in low for c in _RELATIONAL_CUES):
        return "graph", f"links {sorted(kinds)} - needs a multi-hop walk"
    if _RECORD.search(question) or (kinds and re.search(r"\b(which|what time|status|delayed|on time)\b", low)):
        return "database", "one fact about one record"
    return "retrieval", "open guidance question"
