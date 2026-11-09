"""Layer 9 (part 2) - Interaction design: use the cheapest thing that is reliably right.

| Task shape                                  | Mechanism         | Why                                   |
|---------------------------------------------|-------------------|---------------------------------------|
| look up one record (gate, bag scan, order)   | database tool     | exact, fast, auditable                |
| arithmetic on known facts (ETA, buffers)     | deterministic code| a model adds risk and cost, no value  |
| open guidance question                       | retrieval         | answers come from written policy      |
| investigation across several systems         | agent loop        | next step depends on what it finds    |

Route and timing maths below is plain code over the airport map. The only agent loop in the
system is the lost-bag investigation (layer 3, baggage agent).
"""

from __future__ import annotations

from enum import Enum

from . import world as W


class Mechanism(str, Enum):
    DATABASE_TOOL = "database_tool"
    DETERMINISTIC_CODE = "deterministic_code"
    RETRIEVAL = "retrieval"
    AGENT = "agent"


TASKS: dict[str, Mechanism] = {
    "gate_lookup": Mechanism.DATABASE_TOOL,
    "bag_scan_lookup": Mechanism.DATABASE_TOOL,
    "order_lookup": Mechanism.DATABASE_TOOL,
    "eta_calculation": Mechanism.DETERMINISTIC_CODE,
    "duty_free_feasibility": Mechanism.DETERMINISTIC_CODE,
    "fare_difference": Mechanism.DETERMINISTIC_CODE,
    "policy_question": Mechanism.RETRIEVAL,
    "lost_bag_investigation": Mechanism.AGENT,
    "request_understanding": Mechanism.AGENT,
}


def mechanism_for(task: str) -> Mechanism:
    return TASKS[task]


def plan_route(location: str, dst: str, security_wait: dict[str, int]) -> dict:
    """Best path from where the passenger is to dst, including a security queue if still landside."""
    if W.NODES[location]["zone"] == "airside":
        path, walk = W.shortest_route(location, dst)
        return {"path": path, "walk_min": walk, "wait_min": 0, "total_min": walk, "checkpoint": None}
    best = None
    for cp, wait in sorted(security_wait.items()):
        if location == cp:
            p1, w1 = [cp], 0
        else:
            p1, w1 = W.shortest_route(location, cp)
        p2, w2 = W.shortest_route(cp, dst)
        cand = {"path": p1 + p2[1:], "walk_min": w1 + w2, "wait_min": wait, "total_min": w1 + w2 + wait,
                "checkpoint": cp}
        if best is None or cand["total_min"] < best["total_min"]:
            best = cand
    return best


def plan_via(location: str, stop: str, dst: str, security_wait: dict[str, int], stop_min: int) -> dict:
    first = plan_route(location, stop, security_wait)
    p2, w2 = W.shortest_route(stop, dst)
    return {"path": first["path"] + p2[1:], "walk_min": first["walk_min"] + w2, "wait_min": first["wait_min"],
            "stop_min": stop_min, "total_min": first["total_min"] + w2 + stop_min, "checkpoint": first["checkpoint"]}


def duty_free_choice(now: int, boarding_close: int, dep: int, via_shop: dict, direct: dict, order: dict) -> str:
    """'pickup' if there is time with the safety buffer, else 'gate_delivery' if allowed, else 'skip'."""
    if now + via_shop["total_min"] + W.SAFETY_BUFFER_MIN <= boarding_close:
        return "pickup"
    if order["paid"] and order["gate_delivery"] and order["status"] == "ready" and now <= dep - 30 \
            and now + direct["total_min"] <= boarding_close:
        return "gate_delivery"
    return "skip"
