from harrowgate.context import DECISIONS


def test_packets_are_much_smaller_than_everything(run):
    resp, _, _ = run("My gate changed", setup={"gate_change": {"to": "C2", "ago": 6}})
    ctx = resp.trace.of_kind("context")[0].attrs
    assert ctx["tokens"] * 10 < ctx["raw_tokens"]


def test_stale_cache_is_refetched_when_freshness_check_is_on(run):
    resp, _, _ = run("My gate changed", cache_age=15, setup={"gate_change": {"to": "C2", "ago": 6}})
    ctx = resp.trace.of_kind("context")[0].attrs
    assert ctx["flight_source"] == "live" and resp.destination == "C2"


def test_stale_cache_is_used_without_freshness_check(run):
    from harrowgate.system import BASELINE
    resp, _, _ = run("My gate changed", cache_age=15, config=BASELINE, setup={"gate_change": {"to": "C2", "ago": 6}})
    assert resp.trace.of_kind("context")[0].attrs["flight_source"] == "cache" and resp.destination == "B4"


def test_fresh_cache_is_trusted_and_saves_a_call(run):
    resp, _, _ = run("Which gate is SK204?", cache_age=2)
    assert "flight_status" not in {s.name for s in resp.trace.of_kind("tool")}


def test_each_decision_declares_a_small_field_list():
    assert all(1 <= len(v) <= 4 for v in DECISIONS.values())


def test_other_passengers_order_is_never_read(run):
    resp, _, _ = run("collect my duty free order DF-9003", pid="P-1001")
    calls = [s.attrs.get("args") for s in resp.trace.of_kind("tool") if s.name == "order_status"]
    assert {"order_id": "DF-9003"} not in calls


def test_memory_preferences_join_the_packet_only_with_consent(run):
    from harrowgate.evaluation import build_world
    from harrowgate.system import System
    from tests.conftest import scenario
    w, cache = build_world(scenario())
    s = System(w, cache=cache)
    s.store.remember("P-1001", "language", "fr", w.now, consent=True)
    s.store.remember("P-1001", "step_free", True, w.now, consent=False)
    resp = s.handle({"passenger_id": "P-1001", "text": "Which gate is SK204?"}, run_id="m")
    assert resp.data["prefs"]["language"] == "fr" and resp.data["prefs"]["step_free"] is False
