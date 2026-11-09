"""Layer 2 - Orchestration: a fixed, inspectable workflow chosen by a router.

The model only turns free text into intents and identifiers. From there a deterministic router
picks workflows, merges them in a fixed priority order and removes repeated steps. Each step is
owned by one agent. Ordering encodes business rules: a gate change is resolved before a duty-free
plan (so the plan uses the new gate), and the duty-free plan checks time-to-boarding before it
suggests any detour.
"""

from __future__ import annotations

WORKFLOWS: dict[str, list[str]] = {
    "rebook": ["journey.refresh_flight", "flight_planning.find_alternatives", "flight_planning.rebook"],
    "gate_change": ["journey.refresh_flight", "journey.route_to_gate", "baggage.check_bags", "journey.check_timing",
                    "flight_planning.find_alternatives", "flight_planning.rebook"],
    "flight_status": ["journey.refresh_flight", "journey.answer_status"],
    "duty_free": ["journey.refresh_flight", "journey.plan_duty_free", "journey.act_duty_free"],
    "lost_bag": ["baggage.investigate", "baggage.act_on_finding"],
    "faq": ["airport_info.answer"],
}
PRIORITY = ("rebook", "gate_change", "flight_status", "duty_free", "lost_bag", "faq")
FINAL_STEP = "journey.notify"


def route(intents: list[str]) -> list[str]:
    """Deterministic plan for a set of intents: priority order, no repeated steps, one final message."""
    unknown = set(intents) - set(WORKFLOWS)
    if unknown:
        raise ValueError(f"unknown intents {sorted(unknown)}")
    plan: list[str] = []
    for intent in PRIORITY:
        if intent in intents:
            plan += [s for s in WORKFLOWS[intent] if s not in plan]
    return plan + [FINAL_STEP]


def owner(step: str) -> str:
    return step.split(".", 1)[0]


def check_order(plan: list[str]) -> list[str]:
    """Business-order rules every plan must satisfy (used in tests and at start-up)."""
    problems = []
    if "journey.plan_duty_free" in plan and plan.index("journey.refresh_flight") > plan.index("journey.plan_duty_free"):
        problems.append("duty-free plan must use a refreshed flight")
    if "baggage.check_bags" in plan and plan.index("journey.route_to_gate") > plan.index("baggage.check_bags"):
        problems.append("bag check must follow the gate resolution")
    if "flight_planning.rebook" in plan and \
            plan.index("flight_planning.find_alternatives") > plan.index("flight_planning.rebook"):
        problems.append("alternatives before rebooking")
    if plan[-1] != FINAL_STEP:
        problems.append("plan must end with the passenger message")
    return problems
