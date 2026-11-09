"""Layer 9 (part 1) - Deterministic tools and an MCP-style tool server.

Tools are plain functions over the simulated world. The server speaks JSON-RPC 2.0 with the
`tools/list` and `tools/call` methods, checks arguments against each tool's schema, enforces a
per-caller allowlist, honours idempotency keys for side-effecting tools, and injects scripted
faults (timeouts, lost acknowledgements) so the runtime and recovery layers can be tested.

Only the executor principal can call write or commit tools, and only with a decision token
signed by the policy layer (layer 8).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from . import world as W
from .knowledge import FaqRetriever, KnowledgeGraph, gate_change_impact


class ToolError(Exception):
    """Business-rule failure: retrying will not help."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ToolTimeout(Exception):
    """Transient failure: the caller may retry."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    action_class: str  # read | write | commit
    params: dict[str, type]
    fn: Callable
    latency_ms: int
    description: str
    effect_key: Callable[[dict], str] | None = None

    def schema(self) -> dict:
        names = {str: "string", int: "integer", bool: "boolean"}
        return {"type": "object", "additionalProperties": False, "required": sorted(self.params),
                "properties": {k: {"type": names[t]} for k, t in self.params.items()}}


def _flight(world: W.World, flight_id: str) -> dict:
    if flight_id not in world.flights:
        raise ToolError("not_found", f"unknown flight {flight_id}")
    return world.flights[flight_id]


# ------------------------------------------------------------------ read tools
def flight_status(world, flight_id):
    f = _flight(world, flight_id)
    return {"flight_id": flight_id, "gate": f["gate"], "status": f["status"], "dep": f["dep"],
            "boarding_close": world.boarding_close(flight_id), "gate_updated_at": f["gate_updated_at"],
            "fetched_at": world.now, "dest": f["dest"]}


def passenger_profile(world, passenger_id):
    p = world.passengers.get(passenger_id)
    if p is None:
        raise ToolError("not_found", "unknown passenger")
    return {"passenger_id": passenger_id, "flight": p["flight"], "location": p["location"], "cabin": p["cabin"],
            "prefs": dict(p["prefs"]), "bags": list(p["bags"]), "orders": list(p["orders"])}


def shortest_route(world, src, dst):
    try:
        path, minutes = W.shortest_route(src, dst)
    except (KeyError, ValueError) as e:
        raise ToolError("bad_route", str(e)) from None
    return {"path": path, "minutes": minutes}


def security_wait(world, checkpoint):
    if checkpoint not in world.security_wait:
        raise ToolError("not_found", f"unknown checkpoint {checkpoint}")
    return {"checkpoint": checkpoint, "minutes": world.security_wait[checkpoint]}


def bag_trace(world, bag_id):
    b = world.bags.get(bag_id)
    if b is None:
        raise ToolError("not_found", f"unknown bag {bag_id}")
    return {"bag_id": bag_id, "flight": b["flight"], "area": b["area"], "last_scan": b["last_scan"],
            "status": b["status"], "note": b.get("note", "")}


def order_status(world, order_id):
    o = world.orders.get(order_id)
    if o is None:
        raise ToolError("not_found", f"unknown order {order_id}")
    return {"order_id": order_id, **{k: o[k] for k in ("shop", "status", "paid", "gate_delivery", "items")}}


def find_alternatives(world, flight_id):
    f = _flight(world, flight_id)
    alts = []
    for fid, g in sorted(world.flights.items(), key=lambda kv: kv[1]["dep"]):
        if fid != flight_id and g["dest"] == f["dest"] and g["dep"] > world.now + W.BOARDING_CLOSES_BEFORE_DEP:
            alts.append({"flight_id": fid, "dep": g["dep"], "gate": g["gate"], "seats_free": g["seats_free"],
                         "fare_diff": max(0, g["fare"] - f["fare"]), "airline": g["airline"]})
    return {"from": flight_id, "alternatives": alts}


_FAQ: FaqRetriever | None = None


def faq_search(world, query):
    global _FAQ
    _FAQ = _FAQ or FaqRetriever()
    return {"query": query, "hits": _FAQ.search(query, 3)}


def kg_query(world, passenger_id):
    p = world.passengers.get(passenger_id)
    if p is None:
        raise ToolError("not_found", "unknown passenger")
    kg = KnowledgeGraph.from_world(world)
    return {"passenger_id": passenger_id,
            "impact": gate_change_impact(kg, passenger_id, world.now, world.flights[p["flight"]]["dep"])}


# ------------------------------------------------------------------ write / commit tools
def send_notification(world, passenger_id, message):
    if passenger_id not in world.passengers:
        raise ToolError("not_found", "unknown passenger")
    if not message.strip() or len(message) > 480:
        raise ToolError("invalid", "message must be 1-480 characters")
    world.record("notification", passenger=passenger_id, message=message)
    return {"sent": True}


def schedule_gate_delivery(world, order_id, gate):
    o = world.orders.get(order_id)
    if o is None:
        raise ToolError("not_found", f"unknown order {order_id}")
    if not o["paid"] or not o["gate_delivery"] or o["status"] != "ready":
        raise ToolError("not_allowed", "order is not eligible for gate delivery")
    if W.NODES.get(gate, {}).get("kind") != "gate":
        raise ToolError("invalid", f"{gate} is not a gate")
    dep = world.flights[world.passengers[o["passenger"]]["flight"]]["dep"]
    if world.now > dep - 30:
        raise ToolError("too_late", "gate delivery needs 30 minutes before departure")
    o["status"] = "gate_delivery"
    o["delivery_gate"] = gate
    world.record("gate_delivery", order=order_id, gate=gate)
    return {"scheduled": True, "gate": gate}


def reroute_bag(world, bag_id, to_area):
    b = world.bags.get(bag_id)
    if b is None:
        raise ToolError("not_found", f"unknown bag {bag_id}")
    if to_area not in W.BAG_AREAS:
        raise ToolError("invalid", f"unknown area {to_area}")
    dep = world.flights[b["flight"]]["dep"]
    move = W.bag_transfer_minutes(b["area"], to_area)
    if world.now + move > dep - W.BAG_CUTOFF_BEFORE_DEP:
        raise ToolError("too_late", "bag cannot reach the make-up area before cut-off")
    b["area"] = to_area
    world.record("bag_reroute", bag=bag_id, to=to_area)
    return {"rerouted": True, "to": to_area, "move_min": move}


def open_bag_case(world, bag_id, summary):
    if bag_id not in world.bags:
        raise ToolError("not_found", f"unknown bag {bag_id}")
    case = "CASE-" + bag_id.split("-")[1]
    world.record("bag_case", bag=bag_id, case=case)
    return {"case": case}


def hold_seat(world, passenger_id, flight_id):
    f = _flight(world, flight_id)
    if f["seats_free"] <= 0:
        raise ToolError("no_seats", f"{flight_id} is full")
    f["seats_free"] -= 1
    world.record("seat_hold", passenger=passenger_id, flight=flight_id)
    return {"held": True}


def release_seat(world, passenger_id, flight_id):
    _flight(world, flight_id)["seats_free"] += 1
    world.record("seat_release", passenger=passenger_id, flight=flight_id)
    return {"released": True}


def rebook_passenger(world, passenger_id, flight_id):
    p = world.passengers.get(passenger_id)
    if p is None:
        raise ToolError("not_found", "unknown passenger")
    _flight(world, flight_id)
    old = p["flight"]
    p["flight"] = flight_id
    for b in p["bags"]:
        world.bags[b]["flight"] = flight_id
    world.record("rebooking", passenger=passenger_id, flight=flight_id, old=old)
    return {"rebooked": True, "flight_id": flight_id, "old": old}


def _k(*fields):
    return lambda a: "|".join(str(a[f]) for f in fields)


REGISTRY: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("flight_status", "read", {"flight_id": str}, flight_status, 120, "Live gate, status and times"),
    ToolSpec("passenger_profile", "read", {"passenger_id": str}, passenger_profile, 80, "Booking and location"),
    ToolSpec("shortest_route", "read", {"src": str, "dst": str}, shortest_route, 40, "Walking route and minutes"),
    ToolSpec("security_wait", "read", {"checkpoint": str}, security_wait, 60, "Live queue minutes"),
    ToolSpec("bag_trace", "read", {"bag_id": str}, bag_trace, 150, "Last scan of a checked bag"),
    ToolSpec("order_status", "read", {"order_id": str}, order_status, 90, "Duty-free order state"),
    ToolSpec("find_alternatives", "read", {"flight_id": str}, find_alternatives, 200, "Later flights, same city"),
    ToolSpec("faq_search", "read", {"query": str}, faq_search, 70, "Search written guidance"),
    ToolSpec("kg_query", "read", {"passenger_id": str}, kg_query, 110, "Gate-change impact on bags"),
    ToolSpec("send_notification", "write", {"passenger_id": str, "message": str}, send_notification, 180,
             "Message the passenger", _k("passenger_id", "message")),
    ToolSpec("schedule_gate_delivery", "write", {"order_id": str, "gate": str}, schedule_gate_delivery, 220,
             "Send a paid order to the gate", _k("order_id")),
    ToolSpec("reroute_bag", "write", {"bag_id": str, "to_area": str}, reroute_bag, 250, "Move a bag",
             _k("bag_id", "to_area")),
    ToolSpec("open_bag_case", "write", {"bag_id": str, "summary": str}, open_bag_case, 200, "Open a bag case",
             _k("bag_id")),
    ToolSpec("hold_seat", "write", {"passenger_id": str, "flight_id": str}, hold_seat, 200, "Hold a seat",
             _k("passenger_id", "flight_id")),
    ToolSpec("release_seat", "write", {"passenger_id": str, "flight_id": str}, release_seat, 150,
             "Release a held seat", _k("passenger_id", "flight_id")),
    ToolSpec("rebook_passenger", "commit", {"passenger_id": str, "flight_id": str}, rebook_passenger, 400,
             "Move the booking", _k("passenger_id", "flight_id")),
]}


def validate_args(spec: ToolSpec, args: dict) -> list[str]:
    problems = [f"missing {k}" for k in spec.params if k not in args]
    problems += [f"unexpected {k}" for k in args if k not in spec.params]
    problems += [f"{k} must be {t.__name__}" for k, t in spec.params.items()
                 if k in args and not isinstance(args[k], t)]
    return problems


@dataclass
class ToolServer:
    """JSON-RPC 2.0 tool server (MCP-style method names). One instance per world."""

    world: W.World
    allowlist: dict[str, set[str]]
    verify_token: Callable[[str, dict], bool] = lambda token, call: False
    honour_idempotency: bool = True
    registry: dict[str, ToolSpec] = field(default_factory=lambda: REGISTRY)
    _done: dict[str, dict] = field(default_factory=dict)
    calls: int = 0

    def handle(self, request: dict, caller: str) -> dict:
        rid = request.get("id")
        if request.get("jsonrpc") != "2.0" or "method" not in request:
            return _err(rid, -32600, "invalid request")
        if request["method"] == "tools/list":
            names = sorted(self.allowlist.get(caller, set()))
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": n, "description": self.registry[n].description, "inputSchema": self.registry[n].schema(),
                 "annotations": {"actionClass": self.registry[n].action_class}} for n in names]}}
        if request["method"] != "tools/call":
            return _err(rid, -32601, "method not found")
        params = request.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        spec = self.registry.get(name)
        if spec is None:
            return _err(rid, -32602, f"unknown tool {name}")
        if name not in self.allowlist.get(caller, set()):
            return _err(rid, -32001, f"{caller} may not call {name}")
        if spec.action_class != "read":
            token = params.get("decision_token", "")
            if caller != "executor" or not self.verify_token(token, {"tool": name, "arguments": args}):
                return _err(rid, -32002, "side-effecting call needs a valid policy decision token")
        problems = validate_args(spec, args)
        if problems:
            return _err(rid, -32602, "; ".join(problems))
        key = params.get("idempotency_key")
        if key and self.honour_idempotency and key in self._done:
            return {"jsonrpc": "2.0", "id": rid, "result": {**self._done[key], "_replayed": True}}
        faults = self.world.faults
        if faults.get("timeout", {}).get(name, 0) > 0:
            faults["timeout"][name] -= 1
            raise ToolTimeout(f"{name} timed out")
        self.calls += 1
        try:
            result = spec.fn(self.world, **args)
        except ToolError as e:
            return _err(rid, -32010, str(e), {"code": e.code})
        if key and self.honour_idempotency:
            self._done[key] = result
        if faults.get("lost_ack", {}).get(name, 0) > 0:  # effect happened, reply lost
            faults["lost_ack"][name] -= 1
            raise ToolTimeout(f"{name} reply lost")
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code: int, message: str, data: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message, "data": data or {}}}


def call_hash(call: dict) -> str:
    import json
    return hashlib.sha256(json.dumps(call, sort_keys=True).encode()).hexdigest()
