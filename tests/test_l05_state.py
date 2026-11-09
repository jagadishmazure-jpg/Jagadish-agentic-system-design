from harrowgate.state import FlightCache, StateStore


def test_checkpoint_roundtrip():
    s = StateStore()
    s.checkpoint("r", ["a", "b"], 1, {"x": 1})
    assert s.load("r") == {"plan": ["a", "b"], "step": 1, "data": {"x": 1}, "status": "running"}
    assert s.load("missing") is None


def test_checkpoints_survive_a_new_connection(tmp_path):
    db = str(tmp_path / "state.db")
    StateStore(db).checkpoint("r", ["a"], 1, {"y": 2}, status="done")
    assert StateStore(db).load("r")["data"] == {"y": 2}


def test_memory_needs_consent_and_expires():
    s = StateStore()
    assert s.remember("P-1", "lang", "en", now=100, consent=False) is False
    s.remember("P-1", "lang", "en", now=100, consent=True, ttl_min=10)
    assert s.recall("P-1", now=105) == {"lang": "en"}
    assert s.recall("P-1", now=111) == {}


def test_forget_removes_all_memory():
    s = StateStore()
    s.remember("P-1", "a", 1, now=0, consent=True)
    s.forget("P-1")
    assert s.recall("P-1", now=1) == {}


def test_journey_phase_is_tracked(run):
    _, _, system = run("Which gate is SK204?")
    assert system.store.phase("P-1001") == "done"


def test_flight_cache_keeps_fetch_time():
    c = FlightCache()
    c.put("SK204", {"gate": "B4"}, 500)
    assert c.get("SK204").fetched_at == 500 and c.get("XX1") is None


def test_knowledge_and_memory_are_separate_stores(run):
    resp, w, system = run("Which gate is SK204?")
    system.store.remember("P-1001", "gate", "Z9", w.now, consent=True)  # a "memory" must never override a fact
    resp2 = system.handle({"passenger_id": "P-1001", "text": "Which gate is SK204?"}, run_id="t2")
    assert resp2.destination == "B4"
