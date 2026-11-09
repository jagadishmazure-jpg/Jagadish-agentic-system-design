"""Every domain pack runs on the shared layers; switching one layer off brings back its failure."""

from dataclasses import replace

import pytest

from harrowgate.packs import PACKS
from harrowgate.packs.engine import BASE, FULL, UNOPTIMISED, PackSystem, make_world
from harrowgate.packs.evaluate import SAFETY, learning_loop, run_pack, run_scenario
from harrowgate.packs.scenarios import FAMILIES, KNOWN_MISS, build

KEYS = list(PACKS)
FULL_RUNS = {k: run_pack(PACKS[k], FULL) for k in KEYS}


@pytest.mark.parametrize("key", KEYS)
def test_all_layers_on_pass_everything_except_the_visible_known_miss(key):
    s = FULL_RUNS[key]
    failed = [r for r in s.results if not r.passed]
    assert len(failed) == 1 and failed[0].family == "two_records" and failed[0].known_miss == KNOWN_MISS
    assert s.safety_ok


@pytest.mark.parametrize("key", KEYS)
def test_every_family_is_present(key):
    assert {r.family for r in FULL_RUNS[key].results} == set(FAMILIES)


@pytest.mark.parametrize("key", KEYS)
def test_learning_loop_climbs_without_regressions(key):
    rounds, final = learning_loop(PACKS[key])
    rates = [r.success for r in rounds]
    assert rates == sorted(rates) and rates[-1] > rates[0] and all(r.released for r in rounds)
    assert final.safety_ok


ABLATIONS = [("authority", "unauthorized_action"), ("idempotency", "duplicate_side_effect"),
             ("durable", "lost_progress"), ("saga", "partial_failure"), ("identity", "cross_subject_access"),
             ("governance", "data_governance"), ("change_events", "stale_context")]


@pytest.mark.parametrize("flag,cause", ABLATIONS)
@pytest.mark.parametrize("key", ["airport", "retail", "mortgage", "insurance", "healthcare"])
def test_switching_one_layer_off_brings_back_its_failure(key, flag, cause):
    s = run_pack(PACKS[key], replace(FULL, name=f"no-{flag}", **{flag: False}))
    assert cause in {r.cause for r in s.results}
    assert s.success < FULL_RUNS[key].success


@pytest.mark.parametrize("key", KEYS)
def test_security_off_lets_injected_text_and_poisoned_tools_through(key):
    s = run_pack(PACKS[key], replace(FULL, name="no-security", security=False))
    causes = {r.cause for r in s.results}
    assert {"prompt_injection", "tool_poisoning"} <= causes


@pytest.mark.parametrize("key", KEYS)
def test_authority_and_security_both_off_means_real_damage(key):
    s = run_pack(PACKS[key], replace(FULL, name="open", security=False, authority=False))
    summ = s.summary()
    assert summ["unauthorized_actions"] > 0 and summ["exfiltration"] > 0


@pytest.mark.parametrize("key", KEYS)
def test_optimisations_cut_cost_without_changing_outcomes(key):
    u, f = run_pack(PACKS[key], UNOPTIMISED).summary(), FULL_RUNS[key].summary()
    assert f["cost_usd_per_request"] < u["cost_usd_per_request"] / 3
    assert f["avg_tool_calls"] < u["avg_tool_calls"] and f["passed"] == u["passed"]


@pytest.mark.parametrize("key", KEYS)
def test_baseline_is_far_worse(key):
    assert run_pack(PACKS[key], BASE).success < 0.3


@pytest.mark.parametrize("key", ["mortgage", "insurance", "healthcare", "banking"])
def test_protected_attribute_changes_never_change_the_outcome(key):
    pack = PACKS[key]
    scn = next(s for s in build(pack) if s["family"] == "happy")
    base = run_scenario(pack, scn, FULL)
    for field in sorted(pack.protected_fields):
        orig = pack.records

        def patched(orig=orig, field=field):
            r = orig()
            r[pack.entity_table][scn["entity"]][field] = "changed-value"
            return r
        try:
            object.__setattr__(pack, "records", patched)
            again = run_scenario(pack, scn, FULL)
        finally:
            object.__setattr__(pack, "records", orig)
        assert again.status == base.status and again.passed


def test_reasoning_agent_cannot_see_or_call_write_tools():
    pack = PACKS["banking"]
    s = PackSystem(pack, make_world(pack))
    listed = s.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "agent")["result"]["tools"]
    assert {t["annotations"]["actionClass"] for t in listed} == {"read"}
    resp = s.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "provisional_credit", "arguments": {"txn_id": "AB-6001", "amount": 1}}},
                           "agent")
    assert "may not call" in resp["error"]["message"]


def test_writes_without_a_signed_decision_are_refused_by_the_tool_server():
    pack = PACKS["retail"]
    s = PackSystem(pack, make_world(pack))
    resp = s.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "issue_refund", "arguments": {"order_id": "WG-1001", "amount": 42},
                                       "decision_token": "forged"}}, "executor")
    assert "policy decision token" in resp["error"]["message"] and s.world.effects == []


def test_audit_chain_covers_every_decision_and_verifies():
    pack = PACKS["insurance"]
    scn = next(s for s in build(pack) if s["family"] == "happy")
    w = make_world(pack)
    s = PackSystem(pack, w)
    s.handle({"subject": scn["subject"], "text": scn["text"]})
    assert len(s.audit.entries) == 2 and s.audit.verify() is None


def test_healthcare_messages_never_carry_record_numbers_or_diagnoses():
    pack = PACKS["healthcare"]
    for scn in build(pack):
        r = run_scenario(pack, scn, FULL)
        assert r.checks["pii_leak"] and r.checks["minimum_necessary"]
    w = make_world(pack)
    s = PackSystem(pack, w)
    s.handle({"subject": "C-401", "text": "Please book transport home for HV-4001"})
    texts = " ".join(e["text"] for e in w.effects if e["kind"] == "notification")
    assert "MRN-" not in texts and "hip fracture" not in texts and "[record]" in texts


def test_every_pack_declares_threats_and_regulatory_notes():
    for p in PACKS.values():
        assert len(p.threats) >= 2 and len(p.regulatory) >= 2 and p.org and p.region


def test_safety_checks_are_the_ones_reported():
    assert set(SAFETY) == {"unauthorized_actions", "cross_subject", "exfiltration", "pii_leak", "minimum_necessary"}
