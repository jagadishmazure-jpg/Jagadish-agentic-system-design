"""Layer 12 - Evaluation: judge the process, not just the final sentence.

For every scenario the evaluator replays the request on a fresh simulated world and checks:

* status      - the outcome type is right (done, escalated, denied, pending approval, cancelled)
* location    - the passenger is sent to the gate the flight really leaves from (world truth)
* route       - the path is a real corridor path that starts where the passenger is, ends at the
                destination, and its walking minutes match the map
* timing      - re-computed ETA (walk + true queue + pickup) is before boarding closes, and a
                duty-free detour keeps the safety buffer
* tool_calls  - required tools ran; forbidden tools did not
* access      - no call was refused for lack of permission or a policy token
* duplicate_effects   - no message, delivery, reroute or booking happened twice
* unauthorized_actions - every executed write has an allow decision before it in the trace,
                and no booking happened where the scenario forbids one
* effects     - expected side effects happened the expected number of times
* answer      - guidance questions returned the right FAQ entry
* budget      - tool calls, tokens and simulated latency stayed inside the spec

Cost and latency are simulated (declared per-tool latency; tokens priced at an assumed rate).
"""

from __future__ import annotations

import copy
import statistics
from collections import Counter
from dataclasses import dataclass, field

from . import world as W
from .observability import classify_root_cause
from .requirements import SPEC
from .runtime import SimulatedCrash
from .state import FlightCache
from .system import Config, System
from .tools import REGISTRY, flight_status

EFFECT_KEYS = {"notification": ("passenger", "message"), "gate_delivery": ("order",), "bag_reroute": ("bag", "to"),
               "bag_case": ("bag",), "seat_hold": ("passenger", "flight"), "seat_release": ("passenger", "flight"),
               "rebooking": ("passenger", "flight")}
CHECKS = ("status", "location", "route", "timing", "tool_calls", "access", "duplicate_effects",
          "unauthorized_actions", "effects", "answer", "budget")
SAFETY_CHECKS = ("access", "unauthorized_actions")


def build_world(scn: dict) -> tuple[W.World, FlightCache]:
    w = W.default_world()
    st = scn["setup"]
    w.now = st.get("now", w.now)
    p = w.passengers[scn["passenger_id"]]
    if "location" in st:
        p["location"] = st["location"]
    if "bag" in st:
        w.bags[p["bags"][0]].update(st["bag"])
    cache = FlightCache()
    change = st.get("gate_change")
    change_at = w.now - change["ago"] if change else None
    cache_at = w.now - scn["cache_age"] if scn.get("cache_age") is not None else None

    def apply_change():
        f = w.flights[p["flight"]]
        f["gate"], f["gate_updated_at"] = change["to"], change_at

    if change and (cache_at is None or change_at <= cache_at):
        apply_change()
    if cache_at is not None:
        now = w.now
        w.now = cache_at
        cache.put(p["flight"], flight_status(w, p["flight"]), cache_at)
        w.now = now
    if change and cache_at is not None and change_at > cache_at:
        apply_change()
    w.faults = copy.deepcopy(scn.get("faults", {}))
    return w, cache


def truth_eta(route: list[str], start: str, now: int, waits: dict[str, int]) -> int | None:
    walk = W.route_minutes(route)
    if walk is None:
        return None
    wait = 0
    if W.NODES[start]["zone"] == "landside":
        cp = next((n for n in route if W.NODES[n]["kind"] == "checkpoint"), None)
        wait = waits.get(cp, 0)
    stop = W.PICKUP_MIN if any(W.NODES[n]["kind"] == "shop" for n in route) else 0
    return now + walk + wait + stop


@dataclass
class ScenarioResult:
    id: str
    family: str
    checks: dict[str, bool]
    root_cause: str | None
    metrics: dict
    status: str
    known_miss: str | None = None

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def run_scenario(scn: dict, config: Config) -> ScenarioResult:
    world, cache = build_world(scn)
    start = world.passengers[scn["passenger_id"]]["location"]
    waits = dict(world.security_wait)
    def approver(p, d):
        return (scn["approver"])
    system = System(world, config, cache=cache, approver=approver)
    run_id = f"{scn['id']}-{config.name}"
    try:
        resp = system.handle({"passenger_id": scn["passenger_id"], "text": scn["text"]}, run_id=run_id,
                             crash_after=scn.get("crash_after"), cancel_after=scn.get("cancel_after"))
    except SimulatedCrash:
        resp = system.resume(run_id)
    return evaluate(scn, resp, world, start, waits)


def evaluate(scn: dict, resp, world: W.World, start: str, waits: dict[str, int]) -> ScenarioResult:
    exp, tr = scn["expect"], resp.trace
    pid = scn["passenger_id"]
    flight_id = world.passengers[pid]["flight"]
    truth_gate = world.flights[flight_id]["gate"]
    close = world.boarding_close(flight_id)
    c: dict[str, bool] = {k: True for k in CHECKS}
    c["status"] = resp.status == exp["status"]
    if exp.get("check_location") and resp.status == "done":
        c["location"] = resp.destination == truth_gate
    if resp.route:
        c["route"] = (resp.route[0] == start and resp.route[-1] == resp.destination
                      and W.route_minutes(resp.route) == resp.data.get("walk_min"))
        if resp.status == "done":
            eta = truth_eta(resp.route, start, world.now, waits)
            shop = any(W.NODES[n]["kind"] == "shop" for n in resp.route)
            c["timing"] = eta is not None and eta <= close and (not shop or eta + W.SAFETY_BUFFER_MIN <= close)
    tool_spans = [s for s in tr.spans if s.kind == "tool"]
    called = {s.name for s in tool_spans}
    c["tool_calls"] = set(exp.get("must_call", [])) <= called and not (set(exp.get("must_not_call", [])) & called)
    c["access"] = not any(s.error and ("may not call" in s.error or "policy decision token" in s.error)
                          for s in tool_spans)
    keys = Counter((e["kind"], *(e.get(k) for k in EFFECT_KEYS[e["kind"]])) for e in world.effects)
    dups = sum(v - 1 for v in keys.values() if v > 1)
    c["duplicate_effects"] = dups == 0
    unauthorized = 0
    allowed: Counter = Counter()
    for s in tr.spans:
        if s.kind == "policy" and s.attrs.get("decision") == "allow":
            allowed[s.name] += 1
        if s.kind == "tool" and s.attrs.get("caller") == "executor" and s.status != "error" and allowed[s.name] == 0:
            unauthorized += 1
    kinds = Counter(e["kind"] for e in world.effects)
    for kind, want in exp.get("effects", {}).items():
        if want == 0 and kind in ("rebooking", "seat_hold"):
            unauthorized += kinds[kind]
    c["unauthorized_actions"] = unauthorized == 0
    c["effects"] = all(kinds[k] == v for k, v in exp.get("effects", {}).items())
    if "faq" in exp:
        c["answer"] = resp.data.get("faq_hit") == exp["faq"]
    reads = [(s.name, str(sorted(s.attrs.get("args", {}).items()))) for s in tool_spans
             if s.attrs.get("caller") != "executor" and s.attrs.get("attempt_final")]
    sim_ms = tr.sim_ms
    c["budget"] = resp.status == "escalated" or (resp.tokens <= SPEC.constraint("C2")
                                                   and sim_ms <= SPEC.constraint("C3"))
    failed = [k for k, v in c.items() if not v]
    truth = {"gate_updated_at": world.flights[flight_id]["gate_updated_at"]}
    metrics = {"tool_calls": sum(1 for s in tool_spans if s.attrs.get("attempt_final")),
               "tool_attempts": len(tool_spans), "duplicate_reads": len(reads) - len(set(reads)),
               "duplicate_reads_not_polling": len([r for r in reads if r[0] != "bag_trace"])
               - len({r for r in reads if r[0] != "bag_trace"}),
               "duplicate_effects": dups, "unauthorized_actions": unauthorized, "tokens": resp.tokens,
               "sim_ms": sim_ms, "sim_cost_usd": resp.sim_cost_usd, "repairs": resp.repairs,
               "context_tokens": [s.attrs["tokens"] for s in tr.of_kind("context")],
               "raw_tokens": [s.attrs["raw_tokens"] for s in tr.of_kind("context")]}
    return ScenarioResult(scn["id"], scn["family"], c, classify_root_cause(tr, failed, truth), metrics, resp.status,
                          scn.get("known_miss"))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(centre - half, 4), round(centre + half, 4))


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


@dataclass
class SuiteResult:
    config: Config
    results: list[ScenarioResult] = field(default_factory=list)

    def passed_ids(self) -> set[str]:
        return {r.id for r in self.results if r.passed}

    @property
    def success(self) -> float:
        return len(self.passed_ids()) / len(self.results)

    @property
    def safety_ok(self) -> bool:
        return all(r.checks[k] for r in self.results for k in SAFETY_CHECKS)

    def summary(self) -> dict:
        n = len(self.results)
        k = len(self.passed_ids())
        m = [r.metrics for r in self.results]
        ctx = [t for x in m for t in x["context_tokens"]]
        raw = [t for x in m for t in x["raw_tokens"]]
        fams: dict[str, list[bool]] = {}
        for r in self.results:
            fams.setdefault(r.family, []).append(r.passed)
        return {
            "config": self.config.name,
            "flags": {"freshness_check": self.config.freshness_check, "boarding_guard": self.config.boarding_guard,
                      "idempotency": self.config.idempotency},
            "scenarios": n, "passed": k, "success": {"rate": round(k / n, 4), "wilson95": wilson(k, n)},
            "checks": {c: round(sum(r.checks[c] for r in self.results) / n, 4) for c in CHECKS},
            "duplicate_effects": sum(x["duplicate_effects"] for x in m),
            "unauthorized_actions": sum(x["unauthorized_actions"] for x in m),
            "duplicate_reads": sum(x["duplicate_reads"] for x in m),
            "duplicate_reads_not_polling": sum(x["duplicate_reads_not_polling"] for x in m),
            "avg_tool_calls": round(statistics.mean(x["tool_calls"] for x in m), 2),
            "avg_tokens": round(statistics.mean(x["tokens"] for x in m), 1),
            "sim_latency_ms": {"p50": pct([x["sim_ms"] for x in m], 0.5), "p95": pct([x["sim_ms"] for x in m], 0.95)},
            "sim_cost_usd_per_request": round(statistics.mean(x["sim_cost_usd"] for x in m), 6),
            "repairs": sum(x["repairs"] for x in m),
            "escalation_rate": round(sum(r.status == "escalated" for r in self.results) / n, 4),
            "context": {"avg_packet_tokens": round(statistics.mean(ctx), 1), "avg_raw_tokens": round(statistics.mean(raw), 1),
                        "reduction": round(1 - statistics.mean(ctx) / statistics.mean(raw), 4)},
            "root_causes": dict(Counter(r.root_cause for r in self.results if r.root_cause).most_common()),
            "families": {f: {"n": len(v), "passed": sum(v)} for f, v in sorted(fams.items())},
            "failed": sorted(r.id for r in self.results if not r.passed),
        }


def run_suite(suite: list[dict], config: Config) -> SuiteResult:
    return SuiteResult(config, [run_scenario(s, config) for s in suite])


__all__ = ["REGISTRY", "run_suite", "run_scenario", "SuiteResult", "wilson"]
