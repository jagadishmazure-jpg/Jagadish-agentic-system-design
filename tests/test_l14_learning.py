import json
from pathlib import Path

from harrowgate.learning import FIXES, learning_loop
from harrowgate.scenarios import build_suite
from harrowgate.system import BASELINE, Config

ROOT = Path(__file__).resolve().parents[1]
REPORT = learning_loop(build_suite())


def test_loop_fixes_most_frequent_cause_first_and_ends_at_default_config():
    causes = [r.cause for r in REPORT.rounds[1:]]
    assert causes == ["stale_context", "unsafe_timing", "duplicate_side_effect", "stale_context"]
    assert [r.change.split(":")[0] for r in REPORT.rounds[1:]] == ["freshness_check", "boarding_guard",
                                                                     "idempotency", "change_events"]
    final = REPORT.final.config
    flags = ("freshness_check", "boarding_guard", "idempotency", "change_events")
    assert all(getattr(final, f) for f in flags) and all(getattr(Config(), f) for f in flags)


def test_every_round_released_without_regressions_and_success_rises():
    rates = [r.success for r in REPORT.rounds]
    assert rates == sorted(rates) and all(r.released and not r.regressions for r in REPORT.rounds)


def test_no_open_causes_remain_outside_known_misses():
    assert REPORT.open_causes == {}


def test_regression_set_matches_committed_file():
    committed = json.loads((ROOT / "data/regression_set.json").read_text())["ids"]
    assert committed == REPORT.regression_set


def test_a_fix_that_breaks_a_passing_scenario_is_not_released(monkeypatch):
    from harrowgate import learning as L
    real = L.run_suite

    def sabotaged(suite, cfg):
        res = real(suite, cfg)
        if cfg.freshness_check:  # pretend the fix broke the first scenario
            res.results[0].checks["status"] = False
        return res

    monkeypatch.setattr(L, "run_suite", sabotaged)
    rep = L.learning_loop(build_suite()[:30], BASELINE, max_rounds=1)
    assert rep.rounds[1].released is False and rep.rounds[1].regressions == ["S001"]


def test_each_fix_maps_to_a_real_config_flag():
    for flag, _ in (f for fixes in FIXES.values() for f in fixes):
        assert hasattr(BASELINE, flag) and getattr(BASELINE, flag) is False
