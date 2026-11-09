"""Layer 3 - Agent boundaries: four agents, each owning one job, its tools and its state.

| Agent            | Owns                                   | Reads                                        | May propose            |
|------------------|----------------------------------------|----------------------------------------------|------------------------|
| journey          | getting the passenger to the gate      | flight, profile, security wait, order         | message, gate delivery |
| baggage          | where the checked bags are             | bag trace, flight, knowledge graph, profile   | bag reroute, bag case  |
| flight_planning  | alternatives when the flight is lost   | flight, alternatives, profile                 | seat hold, rebooking   |
| airport_info     | written guidance                       | FAQ retrieval                                 | nothing                |

Boundaries follow ownership of data and authority, not the number of features. Route maths, fee
maths and lookups stay as tools or plain code (layer 9); only the lost-bag investigation is a model
driven loop. Agents talk to each other through typed handoffs (a2a.py), never by sharing prompts.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import interaction as I
from . import world as W
from .a2a import Handoff, validate_handoff
from .llm import NEXT_STEP_SCHEMA, structured
from .policy import Proposal
from .runtime import BudgetExceeded, ToolFailed, ToolRejected
from .saga import Saga


@dataclass(frozen=True)
class AgentCard:
    name: str
    purpose: str
    read_tools: frozenset[str]
    accepts: frozenset[str]


CARDS: dict[str, AgentCard] = {c.name: c for c in [
    AgentCard("journey", "Get the passenger to the right gate on time",
              frozenset({"flight_status", "passenger_profile", "security_wait", "order_status"}),
              frozenset({"gate_change", "duty_free", "flight_status"})),
    AgentCard("baggage", "Know where checked bags are and fix misroutes",
              frozenset({"bag_trace", "flight_status", "kg_query", "passenger_profile"}),
              frozenset({"lost_bag", "bag_check_after_gate_change", "bag_follow_rebooking"})),
    AgentCard("flight_planning", "Find and propose a new flight when the old one is lost",
              frozenset({"flight_status", "find_alternatives", "passenger_profile"}),
              frozenset({"rebook", "cannot_make_flight"})),
    AgentCard("airport_info", "Answer guidance questions from written policy",
              frozenset({"faq_search"}), frozenset({"faq"})),
]}
WRITE_TOOLS = {"send_notification", "schedule_gate_delivery", "reroute_bag", "open_bag_case", "hold_seat",
               "release_seat", "rebook_passenger"}
ALLOWLIST: dict[str, set[str]] = {c.name: set(c.read_tools) for c in CARDS.values()}
ALLOWLIST["executor"] = set(WRITE_TOOLS)
ACCEPTS = {c.name: set(c.accepts) for c in CARDS.values()}

STATUS_RANK = {"done": 0, "pending_approval": 1, "escalated": 2, "denied": 3, "cancelled": 4}


def set_status(data: dict, status: str) -> None:
    if STATUS_RANK[status] > STATUS_RANK[data.get("status", "done")]:
        data["status"] = status


def handoff(rt, data: dict, frm: str, to: str, intent: str, reason: str, **refs) -> None:
    h = Handoff(frm, to, intent, refs, reason)
    validate_handoff(h, ACCEPTS)
    rt.tracer.span("handoff", f"{frm}->{to}", intent=intent, reason=reason, task_id=h.task_id)
    data.setdefault("handoffs", []).append({"from": frm, "to": to, "intent": intent})


def act(rt, data: dict, agent: str, tool: str, args: dict, reason: str):
    """Propose a side effect through policy; returns the ActionResult (never calls the tool directly)."""
    p = Proposal(agent, tool, args, reason, data["passenger_id"])
    try:
        res = rt.executor.propose(p, rt.run_id, data["_step"], approver=rt.approver)
    except ToolRejected as e:
        data.setdefault("actions", []).append({"tool": tool, "status": f"rejected:{e.code}"})
        return None
    data.setdefault("actions", []).append({"tool": tool, "status": res.status, "rule": res.decision.rule})
    return res


# ------------------------------------------------------------------ journey agent
class JourneyAgent:
    name = "journey"

    def refresh_flight(self, rt, data):
        pkt = rt.builder.build("gate_route", self.name, data["passenger_id"], flight_id=data.get("flight_id"))
        data["flight"] = pkt.fields["flight"]
        data["flight_prov"] = pkt.provenance["flight"]
        data["location"] = pkt.fields["location"]
        data["security_wait"] = pkt.fields["security_wait"]
        data["prefs"] = pkt.fields["prefs"]

    def route_to_gate(self, rt, data):
        f = data["flight"]
        plan = I.plan_route(data["location"], f["gate"], data["security_wait"])
        data.update(route=plan["path"], destination=f["gate"], eta=rt.now + plan["total_min"],
                    walk_min=plan["walk_min"], wait_min=plan["wait_min"], stop_min=0)
        moved = "Your gate is" if "gate_change" not in data["intents"] else "Your gate is now"
        data.setdefault("messages", []).append(
            f"{moved} {f['gate']} for {f['flight_id']}. About {plan['total_min']} min from you; "
            f"boarding closes {W.hhmm(f['boarding_close'])}.")

    def check_timing(self, rt, data):
        if data["eta"] + W.SAFETY_BUFFER_MIN > data["flight"]["boarding_close"]:
            data["needs_rebook"] = True
            data["messages"].append("You are unlikely to reach the gate before boarding closes.")
            handoff(rt, data, self.name, "flight_planning", "cannot_make_flight", "ETA after boarding close",
                    flight_id=data["flight"]["flight_id"], eta=data["eta"])

    def plan_duty_free(self, rt, data):
        pkt = rt.builder.build("duty_free", self.name, data["passenger_id"], order_id=data.get("order_id"),
                               flight_id=data.get("flight_id"))
        order, f = pkt.fields["order"], pkt.fields["flight"]
        if order is None:
            data["messages"].append("I could not find a duty-free order on your booking.")
            return
        loc, waits = pkt.fields["location"], pkt.fields["security_wait"]
        via = I.plan_via(loc, order["shop"], f["gate"], waits, W.PICKUP_MIN)
        direct = I.plan_route(loc, f["gate"], waits)
        if rt.config.boarding_guard:
            rt.tracer.span("decision", "boarding_time_guard", slack=f["boarding_close"] - rt.now - via["total_min"])
            choice = I.duty_free_choice(rt.now, f["boarding_close"], f["dep"], via, direct, order)
        else:
            choice = "pickup"
        rt.tracer.span("decision", "duty_free_choice", choice=choice)
        data["duty_free"] = {"choice": choice, "order_id": order["order_id"], "shop": order["shop"]}
        plan = via if choice == "pickup" else direct
        data.update(route=plan["path"], destination=f["gate"], eta=rt.now + plan["total_min"],
                    walk_min=plan["walk_min"], wait_min=plan["wait_min"], stop_min=plan.get("stop_min", 0))

    def act_duty_free(self, rt, data):
        df = data.get("duty_free")
        if not df:
            return
        f = data["flight"]
        if df["choice"] == "pickup":
            data["messages"].append(f"Collect order {df['order_id']} at {W.NODES[df['shop']]['name']}, then go to "
                                    f"gate {f['gate']} (about {data['eta'] - rt.now} min in total).")
        elif df["choice"] == "gate_delivery":
            res = act(rt, data, self.name, "schedule_gate_delivery", {"order_id": df["order_id"], "gate": f["gate"]},
                      "not enough time to collect before boarding")
            if res and res.status == "done":
                data["messages"].append(f"No time to collect safely, so order {df['order_id']} will be brought to "
                                        f"gate {f['gate']}. Go straight there.")
            else:
                data["messages"].append("Please go straight to your gate; the shop will keep your order.")
        else:
            data["messages"].append(f"There is not enough time to collect order {df['order_id']} safely. Please go "
                                    f"straight to gate {f['gate']}; the shop will keep it.")

    def answer_status(self, rt, data):
        f = data["flight"]
        data.setdefault("messages", []).append(
            f"{f['flight_id']} to {f['dest']} is {f['status'].replace('_', ' ')}, gate {f['gate']}, departs "
            f"{W.hhmm(f['dep'])}.")
        data["destination"] = f["gate"]

    def notify(self, rt, data):
        text = " ".join(data.get("messages", []))[:480] or "Your request was received."
        act(rt, data, self.name, "send_notification", {"passenger_id": data["passenger_id"], "message": text},
            "tell the passenger the outcome")
        rt.store.set_phase(data["passenger_id"], data.get("status", "done"), rt.now)


# ------------------------------------------------------------------ baggage agent
class BaggageAgent:
    name = "baggage"

    def check_bags(self, rt, data):
        handoff(rt, data, "journey", self.name, "bag_check_after_gate_change", "gate changed; bags may be in the "
                "wrong make-up area", passenger_id=data["passenger_id"])
        impact = rt.builder.read(self.name, "kg_query", {"passenger_id": data["passenger_id"]})["impact"]
        rt.tracer.span("decision", "bag_impact", impact=[{k: i.get(k) for k in ("bag", "status")} for i in impact])
        for item in impact:
            if item["status"] == "move":
                res = act(rt, data, self.name, "reroute_bag", {"bag_id": item["bag"], "to_area": item["to"]},
                          "bag must follow the new gate")
                if res and res.status == "done":
                    data["messages"].append(f"Your bag {item['bag']} is being moved to the new gate's loading area.")
            elif item["status"] == "too_late":
                act(rt, data, self.name, "open_bag_case", {"bag_id": item["bag"], "summary": "gate change after cut-off"},
                    "bag cannot follow in time")
                data["messages"].append(f"Your bag {item['bag']} may travel on a later flight; a bag case is open.")
            elif item["status"] == "ok":
                data["messages"].append(f"Your bag {item['bag']} is already in the right area.")

    def investigate(self, rt, data):
        """The only model-driven loop: next step depends on what the last tool said."""
        bag = data.get("bag_id") or rt.builder.read(self.name, "passenger_profile",
                                                    {"passenger_id": data["passenger_id"]})["bags"][0]
        data["bag_id"] = bag
        obs: list[dict] = []
        limit = int(rt.spec.constraint("C6"))
        for _ in range(limit):
            step, stats = structured(rt.llm, "investigate_next", {"observations": obs, "bag_id": bag},
                                     NEXT_STEP_SCHEMA)
            rt.charge_llm(stats, "investigate_next")
            if step is None:
                data["finding"] = "model_error"
                return
            if step["action"] == "finish":
                data["finding"] = step["finding"]
                rt.tracer.span("decision", "bag_finding", finding=step["finding"], steps=len(obs))
                return
            args = {k: (data["passenger_id"] if v == "__self__" else v) for k, v in step["args"].items()}
            if step["action"] not in CARDS[self.name].read_tools:
                data["finding"] = "model_error"
                return
            # bag scans are polled fresh; other reads come from the per-request memo (no duplicate calls)
            read = rt.client.call if step["action"] == "bag_trace" else rt.builder.read
            obs.append({"action": step["action"], "result": read(self.name, step["action"], args)})
        data["finding"] = "step_limit"
        rt.tracer.span("runtime", "budget_exceeded", what="investigation steps", limit=limit)

    def act_on_finding(self, rt, data):
        finding, bag = data.get("finding"), data["bag_id"]
        msgs = data.setdefault("messages", [])
        if finding == "on_track":
            msgs.append(f"Bag {bag} is in the right loading area for your flight.")
        elif finding == "wrong_area":
            impact = rt.builder.read(self.name, "kg_query", {"passenger_id": data["passenger_id"]})["impact"]
            item = next(i for i in impact if i["bag"] == bag)
            res = act(rt, data, self.name, "reroute_bag", {"bag_id": bag, "to_area": item["to"]}, "bag mis-sorted")
            msgs.append(f"Bag {bag} was in the wrong area and is being moved." if res and res.status == "done"
                        else f"Bag {bag} is in the wrong area; baggage staff have been told.")
        elif finding in ("wrong_area_late", "wrong_flight", "no_scan"):
            res = act(rt, data, self.name, "open_bag_case", {"bag_id": bag, "summary": finding}, "bag needs staff")
            case = res.result["case"] if res and res.result else "pending"
            msgs.append(f"Bag {bag} needs a person to find it. Case {case} is open and baggage services will update "
                        f"you.")
            set_status(data, "escalated")
        else:
            msgs.append(f"I could not trace bag {bag} reliably, so baggage services will contact you.")
            set_status(data, "escalated")


# ------------------------------------------------------------------ flight planning agent
class FlightPlanningAgent:
    name = "flight_planning"

    def find_alternatives(self, rt, data):
        if not (data.get("needs_rebook") or "rebook" in data["intents"]):
            return
        pkt = rt.builder.build("rebook", self.name, data["passenger_id"], flight_id=data.get("flight_id"))
        options = [a for a in pkt.fields["alternatives"] if a["seats_free"] > 0]
        data["alternative"] = options[0] if options else None
        data["old_flight"] = pkt.fields["flight"]["flight_id"]
        if not options:
            data.setdefault("messages", []).append("No later flight to your destination has seats today; an agent "
                                                   "at the transfer desk will help you.")
            set_status(data, "escalated")

    def rebook(self, rt, data):
        alt = data.get("alternative")
        if not alt or not (data.get("needs_rebook") or "rebook" in data["intents"]):
            return
        pid, msgs = data["passenger_id"], data.setdefault("messages", [])
        p = Proposal(self.name, "rebook_passenger", {"passenger_id": pid, "flight_id": alt["flight_id"]},
                     "passenger cannot travel on the booked flight", pid)
        res = rt.executor.propose_only(p, approver=rt.approver)
        data.setdefault("actions", []).append({"tool": "rebook_passenger", "status": res.status,
                                               "rule": res.decision.rule})
        if res.status == "pending_approval":
            msgs.append(f"{alt['flight_id']} at {W.hhmm(alt['dep'])} has seats. The fare difference needs a duty "
                        f"manager's approval; you will get a message when it is decided.")
            set_status(data, "pending_approval")
            return
        if res.status == "denied":
            msgs.append(f"I cannot change your booking here ({res.decision.reason}). Please see the transfer desk.")
            set_status(data, "denied")
            return
        saga = Saga("rebook", rt.tracer)
        hold = Proposal(self.name, "hold_seat", {"passenger_id": pid, "flight_id": alt["flight_id"]}, "hold", pid)
        release = Proposal(self.name, "release_seat", {"passenger_id": pid, "flight_id": alt["flight_id"]},
                           "compensate hold", pid)
        saga.add("hold_seat", lambda: rt.executor.run_allowed(hold, rt.run_id, data["_step"]),
                 lambda _r: rt.executor.run_allowed(release, rt.run_id, data["_step"]))
        saga.add("rebook_passenger", lambda: rt.executor.execute(p, res.decision, rt.run_id, data["_step"]))
        out = saga.run()
        data["saga"] = {"status": out.status, "compensated": out.compensated, "failed_step": out.failed_step}
        if out.status != "completed":
            msgs.append("The rebooking could not be finished, so the held seat was released. The transfer desk "
                        "will help you.")
            set_status(data, "escalated")
            return
        msgs.append(f"You are rebooked on {alt['flight_id']} at {W.hhmm(alt['dep'])}, gate {alt['gate']}.")
        data["destination"] = alt["gate"]
        handoff(rt, data, self.name, "baggage", "bag_follow_rebooking", "bag must move to the new flight",
                passenger_id=pid, flight_id=alt["flight_id"])
        impact = rt.client.call("baggage", "kg_query", {"passenger_id": pid})["impact"]
        for item in impact:
            if item["status"] == "move":
                act(rt, data, "baggage", "reroute_bag", {"bag_id": item["bag"], "to_area": item["to"]},
                    "bag follows the new flight")
        loc = rt.builder.read(self.name, "passenger_profile", {"passenger_id": pid})["location"]
        plan = I.plan_route(loc, alt["gate"], data["security_wait"])
        data.update(route=plan["path"], eta=rt.now + plan["total_min"], walk_min=plan["walk_min"],
                    wait_min=plan["wait_min"], stop_min=0, rebooked_to=alt["flight_id"])


# ------------------------------------------------------------------ airport info agent
class AirportInfoAgent:
    name = "airport_info"

    def answer(self, rt, data):
        from .knowledge import choose_store
        store, why = choose_store(data["text"])
        rt.tracer.span("decision", "knowledge_store", store=store, reason=why)
        pkt = rt.builder.build("faq", self.name, data["passenger_id"], question=data["text"])
        hits = rt.builder.read(self.name, "faq_search", {"query": pkt.fields["question"][:300]})["hits"]
        top = hits[0]
        data["faq_hit"] = top["id"]
        data.setdefault("messages", []).append(f"{top['title']}: {top['text']}")


AGENTS = {"journey": JourneyAgent(), "baggage": BaggageAgent(), "flight_planning": FlightPlanningAgent(),
          "airport_info": AirportInfoAgent()}

__all__ = ["AGENTS", "ALLOWLIST", "CARDS", "BudgetExceeded", "ToolFailed"]
