"""Business case calculator: value vs build and run cost, with every input labelled.

Two kinds of input, never mixed up:

* MEASURED (synthetic): rates taken from the evaluation runs in this repository - how often the
  system finishes a request without a person, how many failures the layers remove, model tokens
  and simulated cost per request. They come from self-written scenario suites that over-represent
  failures on purpose, so they describe the design, not a real deployment.
* ASSUMED: business inputs for a fictional organisation - volumes, handling minutes, staff cost,
  error cost, build effort. They are planning estimates for illustration and must be replaced with
  real figures before any decision. Nothing here is a client result.

    value per month  = staff hours saved x loaded hourly cost + rework avoided
    run cost / month = model cost + platform cost + human review of escalations
    payback (months) = build cost / (value - run cost)
"""

from __future__ import annotations

from dataclasses import dataclass, replace

LABEL = "ASSUMED business inputs (illustrative planning estimates, not client results) x MEASURED synthetic rates"


@dataclass(frozen=True)
class Assumptions:
    monthly_volume: int  # requests per month (assumed)
    manual_minutes: float  # staff minutes to handle one request without the system (assumed)
    assisted_minutes: float  # staff minutes when the system finishes it (checking, assumed)
    review_minutes: float  # staff minutes to finish an escalated or approval request (assumed)
    hourly_cost: float  # loaded staff cost per hour, USD (assumed)
    error_rate: float  # share of manual requests needing rework today (assumed)
    error_cost: float  # cost of one rework or wrong payout, USD (assumed)
    platform_month: float  # hosting, monitoring, support per month, USD (assumed)
    build_weeks: float  # engineering weeks to adapt the pack (assumed)
    week_cost: float = 4000.0  # loaded cost per engineering week, USD (assumed)


DOMAINS: dict[str, Assumptions] = {
    "airport": Assumptions(9000, 7, 1.0, 9, 38, 0.04, 30, 900, 10),
    "retail": Assumptions(20000, 6, 0.8, 8, 32, 0.05, 25, 900, 10),
    "mortgage": Assumptions(2500, 20, 3.0, 25, 55, 0.03, 400, 1100, 14),
    "insurance": Assumptions(6000, 25, 4.0, 30, 48, 0.04, 350, 1100, 14),
    "healthcare": Assumptions(3000, 15, 2.0, 15, 45, 0.03, 120, 1200, 16),
    "banking": Assumptions(8000, 18, 2.5, 20, 50, 0.03, 90, 1100, 14),
    "itsm": Assumptions(7000, 12, 1.5, 12, 45, 0.04, 60, 800, 8),
    "logistics": Assumptions(12000, 8, 1.0, 10, 35, 0.05, 40, 900, 10),
}
KPI_NAMES = {
    "airport": "service-refund handling time", "retail": "refund handling time",
    "mortgage": "rate-lock extension turnaround", "insurance": "small-claim cycle time",
    "healthcare": "discharge-to-transport wait", "banking": "dispute intake and provisional-credit time",
    "itsm": "access-request resolution time", "logistics": "delivery-exception resolution time",
}
# ASSUMED monthly traffic mix per domain (share of requests by kind); the contained rate of each kind
# is MEASURED on the synthetic suite.
KINDS = {"routine": ("happy", "lost_ack", "crash", "malformed", "hard", "negation", "two_records"),
         "approval": ("approval",), "rule_deny": ("rule_deny",), "status": ("status", "stale_inside_ttl",
                                                                           "stale_old_cache"),
         "info": ("info", "info_repeat", "doc_update"), "risky": ("injection", "poisoned_tool", "cross_subject",
                                                                  "partial_failure")}
MIX = {
    "airport": {"routine": 0.45, "approval": 0.05, "rule_deny": 0.10, "status": 0.15, "info": 0.23, "risky": 0.02},
    "retail": {"routine": 0.55, "approval": 0.05, "rule_deny": 0.08, "status": 0.17, "info": 0.13, "risky": 0.02},
    "mortgage": {"routine": 0.40, "approval": 0.20, "rule_deny": 0.05, "status": 0.20, "info": 0.13, "risky": 0.02},
    "insurance": {"routine": 0.40, "approval": 0.20, "rule_deny": 0.08, "status": 0.20, "info": 0.10, "risky": 0.02},
    "healthcare": {"routine": 0.50, "approval": 0.10, "rule_deny": 0.15, "status": 0.15, "info": 0.08, "risky": 0.02},
    "banking": {"routine": 0.45, "approval": 0.15, "rule_deny": 0.07, "status": 0.18, "info": 0.12, "risky": 0.03},
    "itsm": {"routine": 0.50, "approval": 0.15, "rule_deny": 0.05, "status": 0.15, "info": 0.13, "risky": 0.02},
    "logistics": {"routine": 0.55, "approval": 0.05, "rule_deny": 0.05, "status": 0.25, "info": 0.08, "risky": 0.02},
}


def containment(mix: dict[str, float], contained_by_kind: dict[str, float]) -> float:
    """Assumed mix x measured contained rate per kind."""
    return round(sum(share * contained_by_kind[k] for k, share in mix.items()), 4)


SCENARIOS = {"low": {"volume": 0.5, "minutes": 0.7, "containment": 0.8, "error": 0.5},
             "base": {"volume": 1.0, "minutes": 1.0, "containment": 1.0, "error": 1.0},
             "high": {"volume": 1.5, "minutes": 1.2, "containment": 1.05, "error": 1.5}}


@dataclass(frozen=True)
class Measured:
    containment: float  # share of requests finished without a person (synthetic suite, FULL config)
    error_reduction: float  # 1 - failures(full) / failures(v0), synthetic
    model_cost_per_request: float  # simulated, assumed token prices


def monthly(a: Assumptions, m: Measured, case: str = "base") -> dict:
    k = SCENARIOS[case]
    vol = a.monthly_volume * k["volume"]
    contained = vol * min(1.0, m.containment * k["containment"])
    escalated = vol - contained
    saved_min = contained * (a.manual_minutes - a.assisted_minutes) * k["minutes"]
    review_min = escalated * max(0.0, a.review_minutes - a.manual_minutes)  # extra time, if review is slower
    hours = (saved_min - review_min) / 60
    rework = vol * a.error_rate * a.error_cost * m.error_reduction * k["error"]
    value = hours * a.hourly_cost + rework
    run = vol * m.model_cost_per_request + a.platform_month
    net = value - run
    build = a.build_weeks * a.week_cost
    payback = build / net if net > 0 else None
    return {"case": case, "volume": round(vol), "staff_hours_saved": round(hours, 1), "value_usd": round(value),
            "run_cost_usd": round(run), "net_usd": round(net), "build_usd": round(build),
            "payback_months": round(payback, 1) if payback is not None else None,
            "roi_12m": round((12 * net - build) / build, 2)}


def sensitivity(a: Assumptions, m: Measured) -> dict:
    return {c: monthly(a, m, c) for c in SCENARIOS}


def break_even_volume(a: Assumptions, m: Measured) -> int | None:
    """Monthly volume at which value equals run cost (ignoring build). None if never."""
    per = monthly(replace(a, monthly_volume=1000, platform_month=0.0), m)
    per_req = per["net_usd"] / 1000
    if per_req <= 0:
        return None
    return int(a.platform_month / per_req) + 1
