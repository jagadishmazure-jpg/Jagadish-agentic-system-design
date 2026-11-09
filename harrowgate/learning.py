"""Layer 14 - Learning design: run -> trace -> evaluate -> classify -> update -> retest -> release.

The loop starts from an early version of the system (v0: no freshness check, no time-to-boarding
guard, no idempotency keys). Each round it counts failure root causes from the traces (layer 13),
picks the most frequent cause that has a known fix, applies that one change, and re-runs the whole
suite. The change is released only if success goes up, safety checks stay at 100%, and no scenario
in the regression set (everything that passed before) breaks. Causes with no automatic fix are
reported for a human, never silently ignored.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace

from .evaluation import SuiteResult, run_suite
from .system import BASELINE, Config

FIXES: dict[str, tuple[str, str]] = {
    "stale_context": ("freshness_check", "context layer refuses volatile data older than the spec limit"),
    "unsafe_timing": ("boarding_guard", "orchestration checks time-to-boarding before any detour"),
    "duplicate_side_effect": ("idempotency", "action layer sends idempotency keys on every write"),
}


@dataclass
class Round:
    version: str
    cause: str | None
    change: str | None
    success: float
    passed: int
    released: bool
    regressions: list[str] = field(default_factory=list)
    causes: dict = field(default_factory=dict)


@dataclass
class LearningReport:
    rounds: list[Round]
    final: SuiteResult
    regression_set: list[str]
    open_causes: dict
    known_misses: dict


def learning_loop(suite: list[dict], start: Config = BASELINE, max_rounds: int = 6) -> LearningReport:
    cfg = start
    res = run_suite(suite, cfg)
    regression = set(res.passed_ids())
    causes = Counter(r.root_cause for r in res.results if r.root_cause)
    rounds = [Round(cfg.name, None, None, round(res.success, 4), len(regression), True, [], dict(causes))]
    tried: set[str] = set()
    for i in range(1, max_rounds + 1):
        fixable = [c for c, _ in causes.most_common() if c in FIXES and c not in tried
                   and not getattr(cfg, FIXES[c][0])]
        if not fixable:
            break
        cause = fixable[0]
        tried.add(cause)
        flag, note = FIXES[cause]
        cand = replace(cfg, name=f"v{i}", **{flag: True})
        cres = run_suite(suite, cand)
        regressions = sorted(regression - cres.passed_ids())
        ok = cres.success > res.success and cres.safety_ok and not regressions
        ccauses = Counter(r.root_cause for r in cres.results if r.root_cause)
        rounds.append(Round(cand.name, cause, f"{flag}: {note}", round(cres.success, 4), len(cres.passed_ids()), ok,
                            regressions, dict(ccauses)))
        if ok:
            cfg, res, causes = cand, cres, ccauses
            regression |= cres.passed_ids()
    open_causes = dict(Counter(r.root_cause for r in res.results if r.root_cause and not r.known_miss))
    known = {r.id: r.known_miss for r in res.results if not r.passed and r.known_miss}
    return LearningReport(rounds, res, sorted(regression), open_causes, known)
