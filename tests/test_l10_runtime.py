import pytest

from harrowgate.agents import ALLOWLIST
from harrowgate.observability import Tracer
from harrowgate.runtime import (
    Budget,
    BudgetExceeded,
    Cancelled,
    DurableRunner,
    RetryPolicy,
    SimulatedCrash,
    ToolClient,
    ToolFailed,
    ToolRejected,
    idempotency_key,
)
from harrowgate.state import StateStore
from harrowgate.tools import ToolServer


def client(world, **budget):
    b = Budget(budget.get("calls", 25), budget.get("tokens", 6000), budget.get("ms", 99999))
    return ToolClient(ToolServer(world, ALLOWLIST), Tracer("t"), b)


def test_retry_recovers_from_transient_timeout(world):
    world.faults = {"timeout": {"flight_status": 2}}
    c = client(world)
    assert c.call("journey", "flight_status", {"flight_id": "SK204"})["gate"] == "B4"
    assert [s.status for s in c.tracer.of_kind("tool")] == ["timeout", "timeout", "ok"]


def test_retries_are_bounded(world):
    world.faults = {"timeout": {"flight_status": 5}}
    with pytest.raises(ToolFailed):
        client(world).call("journey", "flight_status", {"flight_id": "SK204"})


def test_backoff_is_exponential():
    r = RetryPolicy(base_backoff_ms=100)
    assert [r.backoff(i) for i in (1, 2, 3)] == [100, 200, 400]


def test_business_errors_are_not_retried(world):
    c = client(world)
    with pytest.raises(ToolRejected) as e:
        c.call("journey", "flight_status", {"flight_id": "ZZ999"})
    assert e.value.code == "not_found" and len(c.tracer.of_kind("tool")) == 1


def test_tool_call_budget(world):
    c = client(world, calls=2)
    c.call("journey", "flight_status", {"flight_id": "SK204"})
    c.call("journey", "flight_status", {"flight_id": "SK204"})
    with pytest.raises(BudgetExceeded):
        c.call("journey", "flight_status", {"flight_id": "SK204"})


def test_latency_budget(world):
    with pytest.raises(BudgetExceeded):
        client(world, ms=50).call("journey", "flight_status", {"flight_id": "SK204"})


def test_token_budget():
    b = Budget(1, 100, 1)
    b.charge_tokens(90)
    with pytest.raises(BudgetExceeded):
        b.charge_tokens(20)


def test_idempotency_key_is_stable_and_argument_sensitive():
    k1 = idempotency_key("r", "s", "t", {"a": 1, "b": 2})
    assert k1 == idempotency_key("r", "s", "t", {"b": 2, "a": 1})
    assert k1 != idempotency_key("r", "s", "t", {"a": 2, "b": 2})


def _steps(log):
    return {n: (lambda d, n=n: log.append(n)) for n in ("a", "b", "c")}


def test_crash_then_resume_continues_from_checkpoint():
    store, log = StateStore(), []
    runner = DurableRunner(store, Tracer("t"), crash_after="b")
    with pytest.raises(SimulatedCrash):
        runner.run("r", ["a", "b", "c"], _steps(log), {})
    DurableRunner(store, Tracer("t2")).resume("r", _steps(log))
    assert log == ["a", "b", "b", "c"]  # b re-runs: its checkpoint was never written
    assert store.load("r")["status"] == "done"


def test_resume_of_finished_run_does_nothing():
    store, log = StateStore(), []
    DurableRunner(store, Tracer("t")).run("r", ["a"], _steps(log), {})
    DurableRunner(store, Tracer("t")).resume("r", _steps(log))
    assert log == ["a"]


def test_cancellation_between_steps():
    from harrowgate.runtime import CancelToken
    store, log = StateStore(), []
    runner = DurableRunner(store, Tracer("t"), cancel=CancelToken(after_step="a"))
    with pytest.raises(Cancelled):
        runner.run("r", ["a", "b", "c"], _steps(log), {})
    assert log == ["a"] and store.load("r")["status"] == "cancelled"


def test_cancel_mid_request_leaves_no_bag_move(run):
    from harrowgate.evaluation import build_world
    from harrowgate.system import System
    from tests.conftest import scenario
    w, cache = build_world(scenario(setup={"gate_change": {"to": "C5", "ago": 6}}))
    resp = System(w, cache=cache).handle({"passenger_id": "P-1001", "text": "my gate changed"}, run_id="c",
                                         cancel_after="journey.route_to_gate")
    assert resp.status == "cancelled" and not any(e["kind"] == "bag_reroute" for e in w.effects)


def test_tool_outage_escalates(run):
    resp, _, _ = run("Which gate is BF117?", pid="P-1002", faults={"timeout": {"flight_status": 3}})
    assert resp.status == "escalated"
