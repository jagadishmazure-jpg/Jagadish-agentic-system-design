"""Simulated airport world (synthetic data).

Times are whole minutes after midnight on one simulated day, so every run is deterministic.
The terminal is a weighted graph: nodes are entrances, security checkpoints, the airside plaza,
shops, a pier train and gates; edge weights are walking minutes.
"""

from __future__ import annotations

import copy
import heapq
from dataclasses import dataclass, field

# ---------------------------------------------------------------- terminal graph
NODES: dict[str, dict] = {
    "ENTRANCE": {"kind": "entrance", "zone": "landside", "name": "Main entrance"},
    "CHECKIN": {"kind": "checkin", "zone": "landside", "name": "Check-in hall"},
    "SEC-1": {"kind": "checkpoint", "zone": "landside", "name": "Security north"},
    "SEC-2": {"kind": "checkpoint", "zone": "landside", "name": "Security south"},
    "PLAZA": {"kind": "hub", "zone": "airside", "name": "Central plaza"},
    "DF-CENTRAL": {"kind": "shop", "zone": "airside", "name": "Plaza duty-free"},
    "DF-PIERC": {"kind": "shop", "zone": "airside", "name": "Pier C duty-free"},
    "TRAIN-PLAZA": {"kind": "train", "zone": "airside", "name": "Pier train (plaza stop)"},
    "TRAIN-C": {"kind": "train", "zone": "airside", "name": "Pier train (pier C stop)"},
    "PIER-A": {"kind": "pier", "zone": "airside", "name": "Pier A entry"},
    "PIER-B": {"kind": "pier", "zone": "airside", "name": "Pier B entry"},
    "PIER-C": {"kind": "pier", "zone": "airside", "name": "Pier C entry"},
}
EDGES: list[tuple[str, str, int]] = [
    ("ENTRANCE", "CHECKIN", 3),
    ("CHECKIN", "SEC-1", 4),
    ("CHECKIN", "SEC-2", 6),
    ("SEC-1", "PLAZA", 3),
    ("SEC-2", "PLAZA", 2),
    ("PLAZA", "DF-CENTRAL", 1),
    ("PLAZA", "PIER-A", 4),
    ("PLAZA", "PIER-B", 6),
    ("PLAZA", "TRAIN-PLAZA", 2),
    ("TRAIN-PLAZA", "TRAIN-C", 5),
    ("TRAIN-C", "PIER-C", 1),
    ("PIER-C", "DF-PIERC", 1),
    ("PIER-B", "PIER-C", 9),
]
PIER_GATES = {"A": 4, "B": 6, "C": 6}
for _pier, _count in PIER_GATES.items():
    _prev = f"PIER-{_pier}"
    for _i in range(1, _count + 1):
        _gate = f"{_pier}{_i}"
        NODES[_gate] = {"kind": "gate", "zone": "airside", "name": f"Gate {_gate}", "pier": _pier}
        EDGES.append((_prev, _gate, 2))
        _prev = _gate

# Baggage side: each pier has its own make-up area; moving a bag between areas takes minutes.
BAG_AREAS = {"MU-A": "A", "MU-B": "B", "MU-C": "C"}
BAG_TRANSFER_MIN = {("MU-A", "MU-B"): 12, ("MU-A", "MU-C"): 18, ("MU-B", "MU-C"): 14}
BAG_CUTOFF_BEFORE_DEP = 25  # a bag must be in the right make-up area 25 min before departure
BOARDING_CLOSES_BEFORE_DEP = 15
PICKUP_MIN = 4  # minutes to collect a duty-free order at the counter
SAFETY_BUFFER_MIN = 5


def graph() -> dict[str, list[tuple[str, int]]]:
    adj: dict[str, list[tuple[str, int]]] = {n: [] for n in NODES}
    for a, b, w in EDGES:
        adj[a].append((b, w))
        adj[b].append((a, w))
    return adj


_ADJ = graph()


def shortest_route(src: str, dst: str) -> tuple[list[str], int]:
    """Dijkstra over walking minutes. Raises KeyError for unknown nodes, ValueError if unreachable."""
    if src not in NODES or dst not in NODES:
        raise KeyError(f"unknown node {src if src not in NODES else dst}")
    dist = {src: 0}
    prev: dict[str, str] = {}
    heap = [(0, src)]
    while heap:
        d, node = heapq.heappop(heap)
        if node == dst:
            break
        if d > dist.get(node, 1 << 30):
            continue
        for nxt, w in _ADJ[node]:
            nd = d + w
            if nd < dist.get(nxt, 1 << 30):
                dist[nxt], prev[nxt] = nd, node
                heapq.heappush(heap, (nd, nxt))
    if dst not in dist:
        raise ValueError(f"no route {src} -> {dst}")
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    return path[::-1], dist[dst]


def route_minutes(path: list[str]) -> int | None:
    """Walking minutes along an explicit path, or None if any hop is not a real corridor."""
    total = 0
    for a, b in zip(path, path[1:]):
        w = next((w for n, w in _ADJ.get(a, []) if n == b), None)
        if w is None:
            return None
        total += w
    return total


def pier_of(gate: str) -> str:
    return NODES[gate]["pier"]


def bag_transfer_minutes(src: str, dst: str) -> int:
    if src == dst:
        return 0
    return BAG_TRANSFER_MIN.get((src, dst)) or BAG_TRANSFER_MIN[(dst, src)]


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


# ---------------------------------------------------------------- mutable world state
@dataclass
class World:
    now: int
    flights: dict[str, dict]
    passengers: dict[str, dict]
    bags: dict[str, dict]
    orders: dict[str, dict]
    security_wait: dict[str, int]
    faults: dict = field(default_factory=dict)
    effects: list[dict] = field(default_factory=list)  # every real side effect, for evaluation

    def copy(self) -> World:
        return copy.deepcopy(self)

    def boarding_close(self, flight_id: str) -> int:
        return self.flights[flight_id]["dep"] - BOARDING_CLOSES_BEFORE_DEP

    def record(self, kind: str, **data) -> None:
        self.effects.append({"kind": kind, "at": self.now, **data})


def default_world() -> World:
    """The morning schedule used by the demo and as the base of every synthetic scenario."""
    flights = {
        "SK204": {"fare": 180, "airline": "Skylark Regional", "dest": "Port Ellery", "dep": 600, "gate": "B4",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 6},
        "SK208": {"fare": 180, "airline": "Skylark Regional", "dest": "Port Ellery", "dep": 780, "gate": "B2",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 14},
        "BF117": {"fare": 210, "airline": "Bluefen Airways", "dest": "Calder Bay", "dep": 615, "gate": "C3",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 3},
        "BF121": {"fare": 210, "airline": "Bluefen Airways", "dest": "Calder Bay", "dep": 720, "gate": "C5",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 0},
        "BF125": {"fare": 260, "airline": "Bluefen Airways", "dest": "Calder Bay", "dep": 840, "gate": "C1",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 9},
        "NL330": {"fare": 150, "airline": "Northloft Air", "dest": "Ravensmoor", "dep": 630, "gate": "A2",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 11},
        "NL334": {"fare": 150, "airline": "Northloft Air", "dest": "Ravensmoor", "dep": 900, "gate": "A3",
                  "status": "on_time", "gate_updated_at": 420, "fare_class": "economy", "seats_free": 20},
    }
    passengers = {
        "P-1001": {"name": "Asha Verlin", "flight": "SK204", "location": "PLAZA", "cabin": "economy",
                   "email": "asha.verlin@example.net", "prefs": {"language": "en", "step_free": False},
                   "bags": ["BG-5001"], "orders": ["DF-9001"]},
        "P-1002": {"name": "Tomas Brack", "flight": "BF117", "location": "SEC-2", "cabin": "economy",
                   "email": "t.brack@example.net", "prefs": {"language": "en", "step_free": True},
                   "bags": ["BG-5002"], "orders": []},
        "P-1003": {"name": "Mira Okonde", "flight": "NL330", "location": "CHECKIN", "cabin": "economy",
                   "email": "mira.o@example.net", "prefs": {"language": "en", "step_free": False},
                   "bags": ["BG-5003"], "orders": ["DF-9003"]},
    }
    bags = {
        "BG-5001": {"passenger": "P-1001", "flight": "SK204", "area": "MU-B", "last_scan": 470, "status": "sorted"},
        "BG-5002": {"passenger": "P-1002", "flight": "BF117", "area": "MU-C", "last_scan": 480, "status": "sorted"},
        "BG-5003": {"passenger": "P-1003", "flight": "NL330", "area": "MU-A", "last_scan": 500, "status": "sorted"},
    }
    orders = {
        "DF-9001": {"passenger": "P-1001", "shop": "DF-CENTRAL", "status": "ready", "paid": True,
                    "gate_delivery": True, "items": 2},
        "DF-9003": {"passenger": "P-1003", "shop": "DF-PIERC", "status": "ready", "paid": True,
                    "gate_delivery": False, "items": 1},
    }
    return World(now=520, flights=flights, passengers=passengers, bags=bags, orders=orders,
                 security_wait={"SEC-1": 8, "SEC-2": 4})
