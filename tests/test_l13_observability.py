import pytest

from harrowgate.observability import Tracer, classify_root_cause, pseudonym


def test_trace_follows_input_context_decision_tool_state(run):
    resp, _, _ = run("Can I collect my duty free order?", now=565)
    kinds = [s.kind for s in resp.trace.spans]
    last = {k: i for i, k in enumerate(kinds)}
    for a, b in [("input", "context"), ("context", "decision"), ("decision", "tool"), ("tool", "state")]:
        assert kinds.index(a) < last[b]
    assert kinds[-1] == "output"


def test_trace_masks_names_emails_and_passenger_ids():
    t = Tracer("t", mask_terms=("Asha Verlin",))
    s = t.span("input", "x", text="I am Asha Verlin, asha@example.net, P-1001")
    assert "Asha" not in s.attrs["text"] and "@" not in s.attrs["text"] and "P-1001" not in s.attrs["text"]
    assert pseudonym("P-1001") in s.attrs["text"]


def test_pseudonym_is_stable_and_keyed(monkeypatch):
    a = pseudonym("P-1001")
    assert a == pseudonym("P-1001")
    monkeypatch.setenv("HARROWGATE_TRACE_KEY", "rotated")
    assert pseudonym("P-1001") != a


def test_unknown_span_kind_rejected():
    with pytest.raises(ValueError):
        Tracer("t").span("magic", "x")


def test_end_to_end_trace_holds_no_raw_identity(run):
    resp, w, _ = run("I am Asha Verlin, my gate changed", setup={"gate_change": {"to": "C2", "ago": 6}})
    blob = repr([s.attrs for s in resp.trace.spans])
    assert "Asha Verlin" not in blob and "P-1001" not in blob and "example.net" not in blob


def test_root_cause_stale_context():
    t = Tracer("t")
    t.span("context", "gate_route", flight_fetched_at=500)
    assert classify_root_cause(t, ["location"], {"gate_updated_at": 510}) == "stale_context"


@pytest.mark.parametrize("failed,expected", [
    (["duplicate_effects", "effects"], "duplicate_side_effect"),
    (["timing"], "unsafe_timing"),
    (["unauthorized_actions"], "unauthorized_action"),
    (["status"], "wrong_outcome"),
    ([], None),
])
def test_root_cause_mapping(failed, expected):
    assert classify_root_cause(Tracer("t"), failed, {}) == expected


def test_root_cause_tool_failure_and_budget():
    t = Tracer("t")
    t.span("tool", "flight_status", status="error", attempt_final=True)
    assert classify_root_cause(t, ["status"], {}) == "tool_failure"
    t.span("runtime", "budget_exceeded")
    assert classify_root_cause(t, ["status"], {}) == "budget_exceeded"


def test_render_lists_every_span(run):
    resp, _, _ = run("Which gate is SK204?")
    assert len(resp.trace.render().splitlines()) == len(resp.trace.spans)
