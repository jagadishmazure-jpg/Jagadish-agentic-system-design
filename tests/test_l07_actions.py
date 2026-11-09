import pytest

from harrowgate.actions import ActionExecutor, NotAuthorized
from harrowgate.agents import ALLOWLIST
from harrowgate.observability import Tracer
from harrowgate.policy import Decision, PolicyEngine, Proposal, Verdict
from harrowgate.runtime import Budget, ToolClient
from harrowgate.tools import ToolServer


def make(world, idem=True):
    policy = PolicyEngine(facts=lambda q, a: {"fare_diff": 0, "seats_free": 3, "cabin_change": False,
                                              "seat_held": False})
    tracer = Tracer("t")
    server = ToolServer(world, ALLOWLIST, verify_token=policy.verify)
    client = ToolClient(server, tracer, Budget(25, 6000, 99999))
    return ActionExecutor(client, policy, tracer, use_idempotency=idem), policy


def note(msg="hello"):
    return Proposal("journey", "send_notification", {"passenger_id": "P-1001", "message": msg}, "test", "P-1001")


def test_write_runs_after_allow_and_is_audited(world):
    ex, _ = make(world)
    res = ex.propose(note(), "r", "s")
    assert res.status == "done" and ex.audit[0]["rule"] == "R4-confirm-and-log"
    assert world.effects[-1]["kind"] == "notification"


def test_executor_refuses_without_allow(world):
    ex, _ = make(world)
    with pytest.raises(NotAuthorized):
        ex.execute(note(), Decision(Verdict.ALLOW, "fake", "no token"), "r", "s")


def test_forged_token_is_refused(world):
    ex, _ = make(world)
    with pytest.raises(NotAuthorized):
        ex.execute(note(), Decision(Verdict.ALLOW, "fake", "x", token="0" * 64), "r", "s")


def test_token_is_bound_to_the_exact_call(world):
    ex, policy = make(world)
    d = policy.decide(note("a"))
    with pytest.raises(NotAuthorized):
        ex.execute(note("b"), d, "r", "s")


def test_invalid_arguments_are_rejected_before_policy(world):
    ex, policy = make(world)
    bad = Proposal("journey", "send_notification", {"passenger_id": "P-1001"}, "x", "P-1001")
    assert ex.propose(bad, "r", "s").status == "rejected" and policy.log == []


def test_same_step_retry_is_replayed_not_repeated(world):
    ex, _ = make(world)
    ex.propose(note(), "r", "s")
    ex.propose(note(), "r", "s")
    assert sum(e["kind"] == "notification" for e in world.effects) == 1


def test_without_idempotency_a_repeat_acts_twice(world):
    ex, _ = make(world, idem=False)
    ex.propose(note(), "r", "s")
    ex.propose(note(), "r", "s")
    assert sum(e["kind"] == "notification" for e in world.effects) == 2


def test_commit_needs_human_and_waits_when_nobody_answers(world):
    ex, policy = make(world)
    policy.facts = lambda q, a: {"fare_diff": 50, "seats_free": 3, "cabin_change": False, "seat_held": False}
    p = Proposal("flight_planning", "rebook_passenger", {"passenger_id": "P-1001", "flight_id": "SK208"}, "x",
                 "P-1001")
    assert ex.propose(p, "r", "s").status == "pending_approval"
    assert ex.propose(p, "r", "s", approver=lambda p, d: "approve").status == "done"
    assert world.passengers["P-1001"]["flight"] == "SK208"
