import pytest

from harrowgate.evaluation import build_world
from harrowgate.observability import Tracer
from harrowgate.runtime import SimulatedCrash
from harrowgate.saga import Saga
from harrowgate.system import BASELINE, Config, System
from tests.conftest import scenario


def test_saga_compensates_in_reverse_order():
    log = []
    saga = Saga("s", Tracer("t"))
    saga.add("a", lambda: log.append("a") or {}, lambda r: log.append("undo-a"))
    saga.add("b", lambda: log.append("b") or {}, lambda r: log.append("undo-b"))
    saga.add("c", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = saga.run()
    assert out.status == "compensated" and out.failed_step == "c" and log == ["a", "b", "undo-b", "undo-a"]


def test_saga_reports_failed_compensation():
    saga = Saga("s", Tracer("t"))
    saga.add("a", lambda: {}, lambda r: (_ for _ in ()).throw(RuntimeError("undo failed")))
    saga.add("b", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert saga.run().status == "compensation_failed"


def test_saga_completes():
    assert Saga("s", Tracer("t")).add("a", lambda: {"ok": 1}).run().status == "completed"


def test_booking_outage_releases_held_seat(run):
    resp, w, _ = run("I missed SK204, rebook me", now=640, setup={"location": "PLAZA"},
                     faults={"timeout": {"rebook_passenger": 3}})
    kinds = [e["kind"] for e in w.effects]
    assert resp.data["saga"]["status"] == "compensated" and "seat_release" in kinds and "rebooking" not in kinds
    assert w.flights["SK208"]["seats_free"] == 14


def _crash(config, crash_after="journey.notify", text="Which gate is BF117?", pid="P-1002", **kw):
    w, cache = build_world(scenario(pid, **kw))
    s = System(w, config, cache=cache)
    with pytest.raises(SimulatedCrash):
        s.handle({"passenger_id": pid, "text": text}, run_id="r", crash_after=crash_after)
    return s.resume("r"), w


def test_resume_with_keys_sends_one_message():
    resp, w = _crash(Config())
    assert sum(e["kind"] == "notification" for e in w.effects) == 1 and resp.status == "done"


def test_resume_without_keys_sends_two_messages():
    _, w = _crash(BASELINE)
    assert sum(e["kind"] == "notification" for e in w.effects) == 2


def test_lost_ack_retry_does_not_double_move_bag(run):
    resp, w, _ = run("my gate moved, what about my bag", setup={"gate_change": {"to": "C2", "ago": 6}},
                     faults={"lost_ack": {"reroute_bag": 1}})
    assert sum(e["kind"] == "bag_reroute" for e in w.effects) == 1
    assert any(s.attrs.get("replayed") for s in resp.trace.of_kind("tool"))


def test_lost_ack_without_keys_double_moves(run):
    _, w, _ = run("my gate moved, what about my bag", config=BASELINE, setup={"gate_change": {"to": "C2", "ago": 6}},
                  faults={"lost_ack": {"reroute_bag": 1}})
    assert sum(e["kind"] == "bag_reroute" for e in w.effects) == 2


def test_resume_after_gate_delivery_crash_delivers_once():
    resp, w = _crash(Config(), crash_after="journey.act_duty_free", text="collect my duty free order", pid="P-1001",
                     now=565)
    assert sum(e["kind"] == "gate_delivery" for e in w.effects) == 1
