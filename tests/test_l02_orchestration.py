import pytest

from harrowgate.orchestrator import FINAL_STEP, WORKFLOWS, check_order, owner, route


def test_gate_change_comes_before_duty_free_and_steps_are_not_repeated():
    plan = route(["duty_free", "gate_change"])
    assert plan.index("journey.route_to_gate") < plan.index("journey.plan_duty_free")
    assert plan.count("journey.refresh_flight") == 1
    assert plan[-1] == FINAL_STEP


def test_route_is_deterministic_regardless_of_intent_order():
    assert route(["lost_bag", "faq", "duty_free"]) == route(["duty_free", "lost_bag", "faq"])


def test_every_possible_plan_satisfies_order_rules():
    import itertools
    intents = list(WORKFLOWS)
    for r in range(1, 4):
        for combo in itertools.combinations(intents, r):
            assert check_order(route(list(combo))) == []


def test_check_order_catches_a_bad_plan():
    bad = ["journey.plan_duty_free", "journey.refresh_flight", "journey.notify"]
    assert "duty-free plan must use a refreshed flight" in check_order(bad)


def test_unknown_intent_is_rejected():
    with pytest.raises(ValueError):
        route(["book_hotel"])


def test_each_step_has_one_owner_agent():
    from harrowgate.agents import AGENTS
    for wf in WORKFLOWS.values():
        for step in wf:
            agent, method = step.split(".")
            assert owner(step) == agent and hasattr(AGENTS[agent], method)


def test_duty_free_runs_time_to_boarding_guard_before_any_detour(run):
    resp, _, _ = run("Can I collect my duty free order?", now=565)
    names = [s.name for s in resp.trace.spans if s.kind == "decision"]
    assert names.index("boarding_time_guard") < names.index("duty_free_choice")


def test_handoff_to_flight_planning_when_passenger_cannot_make_it(run):
    resp, w, _ = run("My gate changed, can I still make it?", pid="P-1003", now=598,
                     setup={"gate_change": {"to": "C6", "ago": 10}})
    assert {"from": "journey", "to": "flight_planning", "intent": "cannot_make_flight"} in resp.data["handoffs"]
    assert w.passengers["P-1003"]["flight"] == "NL334"
