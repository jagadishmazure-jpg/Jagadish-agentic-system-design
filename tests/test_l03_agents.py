from harrowgate.agents import ALLOWLIST, CARDS, WRITE_TOOLS
from harrowgate.policy import PROPOSERS
from harrowgate.tools import REGISTRY


def test_four_agents_with_single_purpose():
    assert set(CARDS) == {"journey", "baggage", "flight_planning", "airport_info"}
    assert all(c.purpose for c in CARDS.values())


def test_agents_can_only_read():
    for name, card in CARDS.items():
        assert all(REGISTRY[t].action_class == "read" for t in card.read_tools), name


def test_only_executor_holds_write_tools():
    assert ALLOWLIST["executor"] == WRITE_TOOLS
    assert all(not (tools & WRITE_TOOLS) for n, tools in ALLOWLIST.items() if n != "executor")


def test_airport_info_agent_cannot_propose_anything():
    assert all("airport_info" not in agents for agents in PROPOSERS.values())


def test_every_write_tool_has_a_proposer_agent():
    assert set(PROPOSERS) == WRITE_TOOLS
    for agents in PROPOSERS.values():
        assert agents <= set(CARDS)


def test_lost_bag_investigation_is_the_model_loop(run):
    resp, _, _ = run("I can't find my bag on the tracker", setup={"bag": {"area": "MU-A"}})
    investigate = [s for s in resp.trace.spans if s.kind == "llm" and s.name == "investigate_next"]
    assert len(investigate) >= 3 and resp.data["finding"] == "wrong_area"


def test_bag_in_transit_hits_step_limit_and_escalates(run):
    resp, _, _ = run("Is my suitcase lost?", setup={"bag": {"status": "in_transit"}})
    assert resp.data["finding"] == "step_limit" and resp.status == "escalated"
    assert sum(1 for s in resp.trace.of_kind("tool") if s.name == "bag_trace") == 6


def test_missing_bag_opens_case_and_escalates(run):
    resp, w, _ = run("my luggage is missing", setup={"bag": {"status": "missing"}})
    assert resp.status == "escalated" and any(e["kind"] == "bag_case" for e in w.effects)
