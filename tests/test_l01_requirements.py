from dataclasses import replace

from harrowgate.requirements import SPEC, Authority, AuthorityRule, Constraint, validate_spec
from harrowgate.tools import REGISTRY


def test_spec_matches_tool_catalogue():
    assert validate_spec(SPEC, set(REGISTRY)) == []


def test_tool_without_authority_rule_is_reported():
    problems = validate_spec(SPEC, set(REGISTRY) | {"delete_booking"})
    assert "tool 'delete_booking' has no authority rule" in problems


def test_human_rule_needs_an_approver_role():
    bad = replace(SPEC, authority=SPEC.authority + (AuthorityRule("x", Authority.HUMAN),))
    assert any("names no approver role" in p for p in validate_spec(bad, set(REGISTRY) | {"x"}))


def test_constraints_must_be_positive():
    bad = replace(SPEC, constraints=SPEC.constraints + (Constraint("C99", "broken", 0, "x"),))
    assert any("C99" in p for p in validate_spec(bad, set(REGISTRY)))


def test_rebooking_needs_a_human_and_refunds_are_out_of_scope():
    assert SPEC.authority_for("rebook_passenger").authority is Authority.HUMAN
    assert SPEC.authority_for("issue_refund").authority is Authority.NEVER


def test_every_read_tool_is_agent_authority():
    for name, spec in REGISTRY.items():
        if spec.action_class == "read":
            assert SPEC.authority_for(name).authority is Authority.AGENT


def test_constraint_lookup():
    assert SPEC.constraint("C4") == 5 and SPEC.constraint("C1") == 25
