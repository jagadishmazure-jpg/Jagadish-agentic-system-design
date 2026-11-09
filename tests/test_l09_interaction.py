import pytest

from harrowgate import interaction as I
from harrowgate.a2a import Handoff, HandoffError, validate_handoff
from harrowgate.agents import ACCEPTS, ALLOWLIST
from harrowgate.tools import ToolServer, ToolTimeout


def rpc(method, **params):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def test_tools_list_shows_only_callers_tools(world):
    srv = ToolServer(world, ALLOWLIST)
    names = {t["name"] for t in srv.handle(rpc("tools/list"), "airport_info")["result"]["tools"]}
    assert names == {"faq_search"}


def test_tool_schema_rejects_extra_keys(world):
    srv = ToolServer(world, ALLOWLIST)
    out = srv.handle(rpc("tools/call", name="flight_status", arguments={"flight_id": "SK204", "x": 1}), "journey")
    assert "unexpected x" in out["error"]["message"]


def test_caller_outside_allowlist_is_refused(world):
    out = ToolServer(world, ALLOWLIST).handle(rpc("tools/call", name="bag_trace", arguments={"bag_id": "BG-5001"}),
                                              "airport_info")
    assert out["error"]["code"] == -32001


def test_write_without_policy_token_is_refused(world):
    srv = ToolServer(world, ALLOWLIST)
    out = srv.handle(rpc("tools/call", name="send_notification",
                         arguments={"passenger_id": "P-1001", "message": "x"}), "executor")
    assert out["error"]["code"] == -32002 and world.effects == []


def test_invalid_jsonrpc_and_unknown_method(world):
    srv = ToolServer(world, ALLOWLIST)
    assert srv.handle({"id": 1, "method": "tools/list"}, "journey")["error"]["code"] == -32600
    assert srv.handle(rpc("resources/list"), "journey")["error"]["code"] == -32601


def test_scripted_timeout_fault(world):
    world.faults = {"timeout": {"flight_status": 1}}
    srv = ToolServer(world, ALLOWLIST)
    with pytest.raises(ToolTimeout):
        srv.handle(rpc("tools/call", name="flight_status", arguments={"flight_id": "SK204"}), "journey")
    assert "result" in srv.handle(rpc("tools/call", name="flight_status", arguments={"flight_id": "SK204"}),
                                  "journey")


def test_mechanism_table():
    assert I.mechanism_for("eta_calculation") is I.Mechanism.DETERMINISTIC_CODE
    assert I.mechanism_for("lost_bag_investigation") is I.Mechanism.AGENT
    assert I.mechanism_for("policy_question") is I.Mechanism.RETRIEVAL
    assert I.mechanism_for("gate_lookup") is I.Mechanism.DATABASE_TOOL


def test_plan_route_picks_faster_checkpoint():
    plan = I.plan_route("CHECKIN", "B4", {"SEC-1": 30, "SEC-2": 2})
    assert plan["checkpoint"] == "SEC-2" and plan["wait_min"] == 2


def test_duty_free_choice_branches():
    via, direct = {"total_min": 20}, {"total_min": 14}
    order = {"paid": True, "gate_delivery": True, "status": "ready"}
    assert I.duty_free_choice(500, 585, 600, via, direct, order) == "pickup"
    assert I.duty_free_choice(565, 585, 600, via, direct, order) == "gate_delivery"
    assert I.duty_free_choice(571, 585, 600, via, direct, order) == "skip"


def test_handoff_validation():
    validate_handoff(Handoff("journey", "baggage", "bag_check_after_gate_change", {"passenger_id": "P-1"}, "x"),
                     ACCEPTS)
    with pytest.raises(HandoffError):
        validate_handoff(Handoff("journey", "baggage", "rebook", {}, "x"), ACCEPTS)
    with pytest.raises(HandoffError):
        validate_handoff(Handoff("journey", "baggage", "lost_bag", {"history": ["x"] * 100}, "x"), ACCEPTS)
    with pytest.raises(HandoffError):
        validate_handoff(Handoff("baggage", "baggage", "lost_bag", {}, "x"), ACCEPTS)


def test_handoff_message_shape():
    msg = Handoff("journey", "baggage", "lost_bag", {"passenger_id": "P-1"}, "why").to_message()
    assert msg["type"] == "task" and msg["status"] == "submitted" and msg["task_id"].startswith("task-")
