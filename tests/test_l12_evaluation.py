import pytest

from harrowgate.evaluation import CHECKS, SAFETY_CHECKS, build_world, run_scenario, truth_eta, wilson
from harrowgate.scenarios import build_suite
from harrowgate.system import BASELINE, Config

SUITE = build_suite()


def by_family(family):
    return [s for s in SUITE if s["family"] == family]


def test_suite_is_deterministic_and_sized():
    assert build_suite() == SUITE and len(SUITE) >= 120 and len({s["id"] for s in SUITE}) == len(SUITE)


def test_build_world_applies_stale_cache_order():
    scn = by_family("gate_change_stale_cache")[0]
    w, cache = build_world(scn)
    flight = w.passengers[scn["passenger_id"]]["flight"]
    assert cache.get(flight).data["gate"] != w.flights[flight]["gate"]


def test_truth_eta_adds_queue_and_pickup():
    route = ["CHECKIN", "SEC-2", "PLAZA", "DF-CENTRAL"]
    assert truth_eta(route, "CHECKIN", 500, {"SEC-2": 4}) == 500 + 9 + 4 + 4
    assert truth_eta(["PLAZA", "C3"], "PLAZA", 500, {}) is None


def test_wilson_interval():
    lo, hi = wilson(95, 100)
    assert lo < 0.95 < hi and wilson(0, 0) == (0.0, 0.0)


@pytest.mark.parametrize("family,check", [
    ("gate_change_stale_cache", "location"),
    ("duty_free_tight_time", "timing"),
    ("fault_lost_ack_notification", "duplicate_effects"),
])
def test_baseline_fails_the_check_each_layer_exists_for(family, check):
    res = run_scenario(by_family(family)[0], BASELINE)
    assert not res.checks[check]


@pytest.mark.parametrize("family", ["gate_change_stale_cache", "duty_free_tight_time", "fault_lost_ack_notification",
                                    "fault_crash_after_message", "rebook_fare_difference", "injection_rebook",
                                    "lost_bag_in_transit_forever", "cancel_mid_run"])
def test_final_version_passes_family(family):
    assert all(run_scenario(s, Config()).passed for s in by_family(family))


def test_safety_checks_are_perfect_on_whole_suite_for_both_versions():
    for cfg in (BASELINE, Config()):
        for s in SUITE:
            res = run_scenario(s, cfg)
            assert all(res.checks[c] for c in SAFETY_CHECKS), (cfg.name, s["id"])


def test_known_misses_stay_visible():
    known = [s for s in SUITE if s["known_miss"]]
    assert len(known) == 6
    inside_ttl = [s for s in known if s["family"] == "gate_change_inside_ttl"]
    others = [s for s in known if s["family"] != "gate_change_inside_ttl"]
    assert len(inside_ttl) == 4 and len(others) == 2
    assert all(not run_scenario(s, Config()).passed for s in others)  # still open, kept visible
    assert all(not run_scenario(s, Config(change_events=False)).passed for s in inside_ttl)  # time limit alone
    assert all(run_scenario(s, Config()).passed for s in inside_ttl)  # fixed by layer 18 change events


def test_all_checks_are_reported():
    res = run_scenario(SUITE[0], Config())
    assert set(res.checks) == set(CHECKS)


def test_evaluator_catches_a_wrong_destination():
    scn = dict(by_family("flight_status")[0])
    res = run_scenario({**scn, "setup": {**scn["setup"], "gate_change": {"to": "C6", "ago": 1}}, "cache_age": 4},
                       Config(change_events=False))
    assert not res.checks["location"] and res.root_cause == "stale_context"
    fixed = run_scenario({**scn, "setup": {**scn["setup"], "gate_change": {"to": "C6", "ago": 1}}, "cache_age": 4},
                         Config())
    assert fixed.checks["location"]  # layer 18: the change event evicted the cached gate
