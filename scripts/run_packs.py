"""Run every domain pack through the shared layers; write results and the generated business docs.

    python scripts/run_packs.py          # rewrite results/packs.json and the generated docs
    python scripts/run_packs.py --check  # recompute and fail if anything committed differs (CI)

Generated files (do not edit by hand):
    results/packs.json, docs/domain-packs.md, docs/benefits-matrix.md, docs/optimization-and-cost.md,
    docs/business-roi.md, docs/executive-summary.md, docs/cloud-options.md

Every scenario, organisation and person is fictional. Latency and cost are simulated; token and
hosting prices are dated assumptions; business inputs in the ROI model are assumptions.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harrowgate import cloud, roi  # noqa: E402
from harrowgate.packs import PACKS  # noqa: E402
from harrowgate.packs.engine import (  # noqa: E402
    BASE,
    COST_FLAGS,
    FLAGS,
    FULL,
    LAYER_OF_FLAG,
    LIMITS,
    UNOPTIMISED,
    PackSystem,
    make_world,
)
from harrowgate.packs.evaluate import CHECKS, SAFETY, learning_loop, run_pack  # noqa: E402
from harrowgate.packs.scenarios import build  # noqa: E402
from harrowgate.release import release_gate  # noqa: E402
from harrowgate.routing import PRICE_AS_OF  # noqa: E402
from harrowgate.tenancy import Tenant, TokenBucket, simulate  # noqa: E402

ORDER = list(PACKS)
SUBJECT = {"airport": "passenger", "healthcare": "patient", "itsm": "employee", "mortgage": "applicant",
           "insurance": "policyholder"}
PORTFOLIO = ("airport", "retail", "mortgage", "insurance", "healthcare")
LAYERS = {1: "Requirements", 2: "Orchestration", 3: "Agent boundaries", 4: "Context", 5: "State and memory",
          6: "Knowledge", 7: "Action design", 8: "Authority", 9: "Tool protocol", 10: "Durable runtime",
          11: "Recovery (sagas)", 12: "Evaluation", 13: "Observability", 14: "Learning loop", 15: "Security",
          16: "Identity and access", 17: "Cost and model routing", 18: "Caching and freshness",
          19: "Versioning and release", 20: "Multi-tenancy and backpressure", 21: "Governance and audit"}


def compact(s: dict) -> dict:
    keep = ("scenarios", "passed", "success", "duplicate_effects", "unauthorized_actions", "cross_subject_reads",
            "exfiltration", "pii_leaks", "protected_exposed", "avg_tokens", "avg_tool_calls", "sim_latency_ms",
            "cost_usd_per_request", "cascades", "answer_cache_hits", "context", "escalation_rate", "containment",
            "intent_accuracy", "tokens_by_tier", "causes", "failed", "known_misses", "checks", "families")
    return {k: s[k] for k in keep}


def by_id(suite) -> dict:
    return {r.id: {"passed": r.passed, "checks": r.checks} for r in suite.results}


def tenancy() -> dict:
    arrivals = []
    for t in range(40):
        if 5 <= t < 25:
            arrivals += [(t, "retail", False)] * 12  # a flash-sale burst from one tenant, arriving first
        for i, key in enumerate(ORDER):
            if t % 2 == i % 2:
                arrivals.append((t, key, False))
        if t % 10 == 3:
            arrivals.append((t, "healthcare", True))  # urgent, time-critical requests
    out = {}
    for fair in (True, False):
        tenants = {k: Tenant(k, TokenBucket(rate=0.6, burst=4)) for k in ORDER}
        r = simulate(tenants, arrivals, workers=5, queue_cap=20, fair=fair)
        arrived = {k: sum(1 for a in arrivals if a[1] == k) for k in ORDER}
        out["fair" if fair else "unfair"] = {
            "served_share": {k: round(r.served[k] / arrived[k], 4) for k in ORDER}, "shed": r.shed,
            "rate_limited": r.rate_limited, "urgent_shed": r.urgent_shed, "p95_wait_ticks": r.p95_wait_ticks}
    out["arrivals"] = len(arrivals)
    return out


def compute() -> dict:
    res: dict = {"label": "synthetic scenarios, fictional organisations; latency and cost simulated",
                 "price_as_of": PRICE_AS_OF, "limits": LIMITS, "checks": list(CHECKS), "safety": list(SAFETY),
                 "packs": {}}
    all_small, all_large = [], []
    for key in ORDER:
        pack = PACKS[key]
        suite = build(pack)
        full = run_pack(pack, FULL, suite)
        fs = full.summary()
        base = run_pack(pack, BASE, suite).summary()
        rounds, _ = learning_loop(pack)
        off = {f: compact(run_pack(pack, replace(FULL, name=f"no-{f}", **{f: False}), suite).summary())
               for f in FLAGS}
        unopt = run_pack(pack, UNOPTIMISED, suite).summary()
        only = {f: compact(run_pack(pack, replace(UNOPTIMISED, name=f"only-{f}", **{f: True}), suite).summary())
                for f in COST_FLAGS}
        older = run_pack(pack, replace(FULL, name="current", change_events=False), suite)
        bad = run_pack(pack, replace(FULL, name="bad", idempotency=False), suite)
        good_gate = release_gate(by_id(older), by_id(full), 0.25, SAFETY)
        bad_gate = release_gate(by_id(full), by_id(bad), 0.25, SAFETY)
        kinds = {}
        for kind, fams in roi.KINDS.items():
            rs = [r for r in full.results if r.family in fams]
            kinds[kind] = round(sum(r.status in ("done", "denied") and r.passed for r in rs) / len(rs), 4)
        sys_ = PackSystem(pack, make_world(pack))
        listed = sys_.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "agent")["result"]["tools"]
        base_failed = base["scenarios"] - base["passed"]
        fixable = sum(v for c, v in base["causes"].items() if c != "wrong_outcome")
        all_small.append(fs["tokens_by_tier"]["small"])
        all_large.append(fs["tokens_by_tier"]["large"])
        res["packs"][key] = {
            "org": pack.org, "domain": pack.domain, "use_case": pack.use_case, "region": pack.region,
            "threats": list(pack.threats), "regulatory": list(pack.regulatory),
            "noun": next(w.effect for w in pack.writes if w.risk == "high").replace("_", " "),
            "first_step": pack.writes[0].effect.replace("_", " "), "entity": pack.entity_label,
            "second_step": pack.writes[1].effect.replace("_", " "),
            "subject_noun": SUBJECT.get(key, "customer"),
            "full": compact(fs), "v0": compact(base), "unoptimised": compact(unopt), "off": off, "only": only,
            "learning": [{"version": r.version, "cause": r.cause, "flag": r.flag, "success": r.success,
                          "released": r.released} for r in rounds],
            "release": {"good": {"promoted": good_gate.promoted, "canary_n": good_gate.canary_n,
                                 "from": good_gate.current_success, "to": good_gate.candidate_success},
                        "bad": {"promoted": bad_gate.promoted, "canary_n": bad_gate.canary_n,
                                "reasons": bad_gate.reasons}},
            "contained_by_kind": kinds,
            "agent_tools": {"listed": len(listed), "writes": sum(t["annotations"]["actionClass"] != "read"
                                                                  for t in listed),
                            "total_writes": sum(1 for t in sys_.registry.values() if t.action_class != "read")},
            "v0_failures": base_failed, "v0_fixable_share": round(fixable / base_failed, 4) if base_failed else 1.0,
        }
    P = res["packs"]
    cuts = [1 - P[k]["full"]["cost_usd_per_request"] / P[k]["unoptimised"]["cost_usd_per_request"] for k in ORDER]
    res["totals"] = {
        "domains": len(ORDER), "scenarios": sum(P[k]["full"]["scenarios"] for k in ORDER),
        "passed": sum(P[k]["full"]["passed"] for k in ORDER), "v0_passed": sum(P[k]["v0"]["passed"] for k in ORDER),
        "safety_incidents": sum(P[k]["full"][x] for k in ORDER for x in (
            "unauthorized_actions", "cross_subject_reads", "exfiltration", "pii_leaks", "protected_exposed")),
        "duplicates_without_idempotency": sum(P[k]["off"]["idempotency"]["duplicate_effects"] for k in ORDER),
        "unauthorized_without_authority": sum(P[k]["off"]["authority"]["unauthorized_actions"] for k in ORDER),
        "cross_reads_without_identity": sum(P[k]["off"]["identity"]["cross_subject_reads"] for k in ORDER),
        "pii_leaks_without_governance": sum(P[k]["off"]["governance"]["pii_leaks"] for k in ORDER),
        "cost_cut_min": round(min(cuts), 4), "cost_cut_max": round(max(cuts), 4),
    }
    res["totals"]["success"] = round(res["totals"]["passed"] / res["totals"]["scenarios"], 4)
    res["totals"]["v0_success"] = round(res["totals"]["v0_passed"] / res["totals"]["scenarios"], 4)
    res["tenancy"] = tenancy()
    small = round(sum(all_small) / len(all_small), 1)
    large = round(sum(all_large) / len(all_large), 1)
    res["cloud"] = {"as_of": cloud.AS_OF, "small_tokens": small, "large_tokens": large,
                    "rows": cloud.compare([10_000, 100_000, 1_000_000], small, large)}
    res["roi"] = {}
    for key in ORDER:
        p = res["packs"][key]
        cont = roi.containment(roi.MIX[key], p["contained_by_kind"])
        v0_fail = p["v0"]["scenarios"] - p["v0"]["passed"]
        full_fail = p["full"]["scenarios"] - p["full"]["passed"]
        m = roi.Measured(cont, round(1 - full_fail / v0_fail, 4), p["full"]["cost_usd_per_request"])
        a = roi.DOMAINS[key]
        res["roi"][key] = {"measured": {"containment": m.containment, "error_reduction": m.error_reduction,
                                        "model_cost_per_request": m.model_cost_per_request},
                           "cases": roi.sensitivity(a, m), "break_even_volume": roi.break_even_volume(a, m),
                           "unoptimised_model_month": round(a.monthly_volume * p["unoptimised"]["cost_usd_per_request"]),
                           "full_model_month": round(a.monthly_volume * p["full"]["cost_usd_per_request"], 1)}
    return res


# ------------------------------------------------------------------ generated documents
def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def pp(a: float, b: float) -> str:
    return f"{(a - b) * 100:+.1f} pp"


HEAD = ("<!-- Generated by scripts/run_packs.py from results/packs.json. Do not edit by hand; "
        "CI fails if this file differs from a fresh run. -->\n\n")


def doc_domains(r: dict) -> str:
    L = [HEAD + "# Domain packs: one design, eight fictional organisations", "",
         "Each pack is a small file: records, the writes it may make, a rule function that proposes them, and "
         "authority rules. Everything else is the shared engine. Every organisation, person and record is "
         "fictional; results are from synthetic scenarios.", "",
         "```mermaid", "flowchart LR", "  R[request] --> U[understand<br/>guard, scan, route model]",
         "  U --> G[gather<br/>identity-checked reads, freshness, minimum necessary]",
         "  G --> D[decide<br/>pack rules propose writes]", "  D --> A[authorise<br/>rules outside the agent, approval]",
         "  A --> X[act<br/>idempotent writes, saga]", "  X --> P[reply<br/>masked, audited]",
         "  subgraph pack[domain pack]", "    rec[(records)]", "    rules[rules + authority]", "  end",
         "  rec -.-> G", "  rules -.-> D", "  rules -.-> A", "```", "",
         "| Domain | Organisation | Use case | Scenarios | Passed (all on) | v0 (all off) | Safety incidents (all on) |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for k in ORDER:
        p = r["packs"][k]
        f = p["full"]
        inc = f["unauthorized_actions"] + f["cross_subject_reads"] + f["exfiltration"] + f["pii_leaks"] + \
            f["protected_exposed"]
        L.append(f"| {p['domain']} | {p['org']} | {p['use_case']} | {f['scenarios']} | {f['passed']} "
                 f"({pct(f['success']['rate'])}) | {p['v0']['passed']} ({pct(p['v0']['success']['rate'])}) | {inc} |")
    L += ["", "The one failure per pack is the same known miss on purpose: when a customer corrects a reference "
          "(\"not X, I meant Y\"), the parser still takes the first reference. It stays visible as a failing "
          "scenario.", ""]
    for k in ORDER:
        p = r["packs"][k]
        L += [f"## {p['org']} ({p['domain']}: {p['use_case']})", "", "Threats handled:", ""]
        L += [f"- {t}" for t in p["threats"]]
        L += ["", "Regulatory-style notes (design intent, not legal advice):", ""]
        L += [f"- {t}" for t in p["regulatory"]]
        L += ["", "Learning loop (each round switches on one layer for the most common failure cause):", "",
              "| Version | Cause | Layer switched on | Success |", "| --- | --- | --- | --- |"]
        for x in p["learning"]:
            lay = f"{x['flag']} (layer {LAYER_OF_FLAG[x['flag']]})" if x["flag"] else "-"
            L.append(f"| {x['version']} | {x['cause'] or 'baseline, all layers off'} | {lay} | {pct(x['success'])} |")
        L.append("")
    return "\n".join(L)


def cell(r: dict, k: str, layer: int) -> str:
    p = r["packs"][k]
    f, off = p["full"], p["off"]

    def drop(flag):
        return pp(off[flag]["success"]["rate"], f["success"]["rate"])
    if layer == 1:
        return f"limits held {round(f['checks']['budget'] * f['scenarios'])}/{f['scenarios']}"
    if layer == 2:
        return f"right workflow {f['intent_accuracy']['correct']}/{f['intent_accuracy']['n']}"
    if layer == 3:
        return f"writes visible to agent: {p['agent_tools']['writes']} of {p['agent_tools']['total_writes']}"
    if layer == 4:
        c = f["context"]
        return f"packet {c['avg_packet_tokens']} vs {c['avg_raw_tokens']} tokens"
    if layer == 5:
        return f"off: {drop('durable')}, lost progress {off['durable']['causes'].get('lost_progress', 0)}"
    if layer == 6:
        return f"answers right {_fam(p, ('info', 'info_repeat', 'doc_update'))}"
    if layer == 7:
        return f"off: tokens {f['avg_tokens']} -> {off['rules_not_model']['avg_tokens']}"
    if layer == 8:
        return f"off: {drop('authority')}, unauthorized {off['authority']['unauthorized_actions']} (e.g. {p['noun']} over the limit)"
    if layer == 9:
        return f"off: {drop('idempotency')}, duplicates {off['idempotency']['duplicate_effects']} (e.g. a second {p['noun']})"
    if layer == 10:
        return f"lost reply + crash: {_fam(p, ('lost_ack', 'crash'))} pass"
    if layer == 11:
        return f"off: {drop('saga')}, half-done {off['saga']['causes'].get('partial_failure', 0)} (e.g. {p['first_step']} left without {p['second_step']})"
    if layer == 12:
        return f"{len(r['checks'])} checks x {f['scenarios']} scenarios"
    if layer == 13:
        return f"v0 failures with a fixable cause: {pct(p['v0_fixable_share'])}"
    if layer == 14:
        return f"{pct(p['learning'][0]['success'])} -> {pct(p['learning'][-1]['success'])}"
    if layer == 15:
        o = off["security"]
        return f"off: {drop('security')}, attacks followed {o['causes'].get('prompt_injection', 0) + o['causes'].get('tool_poisoning', 0)}"
    if layer == 16:
        return f"off: {drop('identity')}, reads of another {p['subject_noun']}'s {p['entity']} {off['identity']['cross_subject_reads']}"
    if layer == 17:
        return f"off: cost x{off['routing']['cost_usd_per_request'] / f['cost_usd_per_request']:.2f}"
    if layer == 18:
        return f"events off: stale answers {off['change_events']['causes'].get('stale_context', 0)}"
    if layer == 19:
        g, b = p["release"]["good"], p["release"]["bad"]
        return f"good {'promoted' if g['promoted'] else 'held'}, bad {'rolled back' if not b['promoted'] else 'shipped'}"
    if layer == 20:
        fair, unfair = r["tenancy"]["fair"]["served_share"][k], r["tenancy"]["unfair"]["served_share"][k]
        return f"served {pct(fair)} fair vs {pct(unfair)} unfair"
    if layer == 21:
        o = off["governance"]
        return f"off: PII leaks {o['pii_leaks']}, protected fields seen {o['protected_exposed']}"
    raise KeyError(layer)


def _fam(p, fams) -> str:
    f = p["full"]["families"]
    return f"{sum(f[x]['passed'] for x in fams)}/{sum(f[x]['n'] for x in fams)}"


WHAT = {1: "turns goals into limits the code enforces", 2: "sends each request down a fixed workflow",
        3: "keeps write tools away from the reasoning step", 4: "sends only what the decision needs",
        5: "checkpoints every step so a crash resumes", 6: "answers policy questions from written sources",
        7: "uses rule code before any model call", 8: "decides writes outside the agent",
        9: "idempotency keys on every write", 10: "retries, budgets and resume",
        11: "undoes finished steps when a later one fails", 12: "judges the process, not the sentence",
        13: "traces name the root cause", 14: "fixes the most common cause, retests, releases",
        15: "blocks injected text, poisoned tools and exfiltration", 16: "acts only for the signed-in person",
        17: "small model for easy work", 18: "change events evict stale cache entries",
        19: "canary gate and automatic rollback", 20: "fair share and load shedding per tenant",
        21: "masks PII, removes protected fields, audits"}


def doc_matrix(r: dict) -> str:
    L = [HEAD + "# What each layer improves, per domain", "",
         "Each cell is measured on that domain's synthetic suite. \"off\" means the full system with only that "
         "layer switched off; pp = change in the share of scenarios passing every check. Layers 19 and 20 are "
         "measured with their own simulations (release gate on the same suites; a load simulation with one "
         "bursting tenant). The airport column is the airport services pack; the flagship airport assistant "
         "has its own results in `results/metrics.json`.", "",
         "```mermaid", "flowchart TB",
         "  subgraph core[shared layers 1-21]", "    L1[1-3 shape] --> L4[4-6 inform] --> L7[7-9 act safely]",
         "    L7 --> L10[10-11 survive failure] --> L12[12-14 learn] --> L15[15-21 production controls]", "  end",
         ]
    for k in ORDER:
        L.append(f"  core --> {k}[{r['packs'][k]['org']}]")
    L += ["```", ""]
    head = "| Layer | What it does | " + " | ".join(r["packs"][k]["domain"] for k in ORDER) + " |"
    L += [head, "| --- | --- | " + " | ".join("---" for _ in ORDER) + " |"]
    for n, name in LAYERS.items():
        L.append(f"| {n}. {name} | {WHAT[n]} | " + " | ".join(cell(r, k, n) for k in ORDER) + " |")
    L += ["", "## Reading the matrix", "",
          "- The same layer protects every domain in the same way because the scenario families are the same; "
          "what differs is what the failure costs (a duplicate refund, a double payout, a second rate-lock fee, "
          "a transport booked twice).",
          "- Layers 4 and 7 show their value in tokens rather than pass rate: with templates and rule code on, "
          "no model reads the context, so trimming matters most when a model does (see the optimisation page).",
          "- Freshness has two parts: the time limit (layer 4) and change events (layer 18). With events on, the "
          "time limit alone adds nothing on these suites; with events off, changes inside the time window are "
          "missed.", ""]
    return "\n".join(L)


def doc_opt(r: dict) -> str:
    L = [HEAD + "# Optimisation and cost", "",
         f"Token prices are assumptions for modelling ({r['price_as_of']}): small tier $0.0003 and large tier "
         "$0.0030 per 1K tokens, blended input and output. Latency is the sum of declared per-tool and per-model "
         "latencies (simulated). All numbers are averages per request over each domain's synthetic suite.", "",
         "## Cost drivers", "",
         "| Driver | Where it comes from | Control in this design |", "| --- | --- | --- |",
         "| Model tokens | parse, reply drafting, plan drafting, policy answers | rule code, templates, small context, "
         "answer cache |",
         "| Model tier | every model call | router: small tier for easy work, cascade on schema failure |",
         "| Tool calls | reads and writes | memoised reads, batched reads, idempotent replays |",
         "| Retries and repairs | timeouts, lost replies, malformed output | capped retries, one repair, then a person |",
         "| Latency | tools + model calls in sequence | fewer calls, small tier, batched reads |",
         f"| Runaway work | loops, large prompts | per-request caps: {r['limits']['tool_calls']} tool calls, "
         f"{r['limits']['tokens']} tokens, {r['limits']['sim_ms']} ms (simulated) |", "",
         "## Before and after, per domain", "",
         "Before = every cost optimisation off (full context to the model, model-written plans and replies, "
         "always the large tier, no answer cache, one read per call). After = all on. Safety layers are on in both.",
         "", "| Domain | Tokens before -> after | Tool calls | Cost per request (USD, simulated) | p50 / p95 ms "
             "before | p50 / p95 ms after | Pass rate before / after |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for k in ORDER:
        p = r["packs"][k]
        u, f = p["unoptimised"], p["full"]
        L.append(f"| {p['domain']} | {u['avg_tokens']} -> {f['avg_tokens']} | {u['avg_tool_calls']} -> "
                 f"{f['avg_tool_calls']} | {u['cost_usd_per_request']:.6f} -> {f['cost_usd_per_request']:.6f} "
                 f"({(1 - f['cost_usd_per_request'] / u['cost_usd_per_request']) * 100:.1f}% less) | "
                 f"{u['sim_latency_ms']['p50']} / {u['sim_latency_ms']['p95']} | {f['sim_latency_ms']['p50']} / "
                 f"{f['sim_latency_ms']['p95']} | {pct(u['success']['rate'])} / {pct(f['success']['rate'])} |")
    L += ["", "## One optimisation at a time (switched on alone, from the unoptimised build)", "",
          "| Domain | " + " | ".join(COST_FLAGS) + " |", "| --- | " + " | ".join("---" for _ in COST_FLAGS) + " |"]
    for k in ORDER:
        p = r["packs"][k]
        u = p["unoptimised"]["cost_usd_per_request"]
        L.append(f"| {p['domain']} | " + " | ".join(
            f"{(1 - p['only'][f]['cost_usd_per_request'] / u) * 100:.1f}% cost, "
            f"{p['only'][f]['avg_tool_calls']} calls" for f in COST_FLAGS) + " |")
    L += ["", "Notes:", "",
          "- `context_trim` alone saves money only because, in the unoptimised build, a model reads the context to "
          "draft plans and replies. Once rule code and templates replace those calls, it mainly protects privacy "
          "and the token cap.",
          "- `routing` can raise token counts slightly (a cascade re-asks the large tier when the small tier's "
          "answer fails validation) while cutting cost, because most requests are easy.",
          "- `batch_reads` saves tool calls and latency, not tokens.",
          "- The simulated model is assumed to be equally correct in both builds, which flatters the unoptimised "
          "build; in practice fewer model calls also means fewer chances to be wrong.", "",
          "## Model cost per month at the assumed volumes", "",
          "| Domain | Assumed requests / month | Model cost before (USD) | Model cost after (USD) |",
          "| --- | --- | --- | --- |"]
    for k in ORDER:
        a = roi.DOMAINS[k]
        L.append(f"| {r['packs'][k]['domain']} | {a.monthly_volume:,} | {r['roi'][k]['unoptimised_model_month']:,} "
                 f"| {r['roi'][k]['full_model_month']:,} |")
    L.append("")
    return "\n".join(L)


def doc_roi(r: dict) -> str:
    L = [HEAD + "# Business case: KPIs, ROI and payback (illustrative)", "",
         "**Read this first.** Business inputs below are assumptions for fictional organisations, chosen to be "
         "plausible for planning, and labelled as such. Rates such as containment and error reduction are measured "
         "on self-written synthetic suites that over-represent failures on purpose. Nothing here is a client result "
         "or a forecast. Replace every assumption with real figures before using it.", "",
         "```mermaid", "flowchart LR", "  M[measured on synthetic suites<br/>containment, error reduction, cost]",
         "  A[assumed inputs<br/>volume, minutes, staff cost, error cost, build effort]",
         "  M --> V[monthly value]", "  A --> V", "  A --> C[run cost + build cost]", "  M --> C",
         "  V --> N[net per month]", "  C --> N", "  N --> P[payback months, 12-month ROI]", "```", "",
         "## KPIs the system moves", "", "| Domain | Main KPI | How the layers move it |", "| --- | --- | --- |"]
    how = {"airport": "routine refunds finish in one step; duplicates and refunds to the wrong passenger are blocked",
           "retail": "refunds within the rules finish without a person; double refunds and refund fraud are blocked",
           "mortgage": "extensions inside the schedule finish at once; protected attributes never reach the decision",
           "insurance": "small clean claims pay out in one step; double payouts and oversized payouts are blocked",
           "healthcare": "transport is booked as soon as the discharge order is signed; no diagnoses in messages",
           "banking": "disputes open and small temporary credits post at once; card numbers never leave",
           "itsm": "standard access is granted at once; admin groups always need the system owner",
           "logistics": "missed slots are rebooked and credited at once; dangerous goods go to the compliance desk"}
    for k in ORDER:
        L.append(f"| {r['packs'][k]['domain']} | {roi.KPI_NAMES[k]} | {how[k]} |")
    L += ["", "## Assumptions (all ASSUMED)", "",
          "| Domain | Requests / month | Manual min | Assisted min | Review min | Staff USD/h | Rework rate | "
          "Rework USD | Platform USD/month | Build weeks |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k in ORDER:
        a = roi.DOMAINS[k]
        L.append(f"| {r['packs'][k]['domain']} | {a.monthly_volume:,} | {a.manual_minutes} | {a.assisted_minutes} | "
                 f"{a.review_minutes} | {a.hourly_cost} | {a.error_rate:.0%} | {a.error_cost} | {a.platform_month:,.0f} | "
                 f"{a.build_weeks} |")
    L += ["", f"Engineering week cost (assumed): USD {roi.DOMAINS['retail'].week_cost:,.0f}. Traffic mix per domain is "
          "assumed (see `harrowgate/roi.py`); the contained rate of each kind of request is measured.", "",
          "## Results: low / base / high", "",
          "Low: half the volume, 70% of the minutes saved, 80% of the containment, half the rework avoided. High: "
          "1.5x volume, 1.2x minutes, 1.05x containment, 1.5x rework avoided.", "",
          "| Domain | Containment (mix x measured) | Error reduction (measured) | Net USD / month low / base / high | "
          "Payback months low / base / high | 12-month ROI base |", "| --- | --- | --- | --- | --- | --- |"]
    for k in ORDER:
        x = r["roi"][k]
        c = x["cases"]
        pay = " / ".join("n/a" if c[s]["payback_months"] is None else str(c[s]["payback_months"])
                         for s in ("low", "base", "high"))
        L.append(f"| {r['packs'][k]['domain']} | {pct(x['measured']['containment'])} | "
                 f"{pct(x['measured']['error_reduction'])} | {c['low']['net_usd']:,} / {c['base']['net_usd']:,} / "
                 f"{c['high']['net_usd']:,} | {pay} | {c['base']['roi_12m']:.2f}x |")
    L += ["", "## Per-layer business view (synthetic suites)", "",
          "Incidents prevented by each safety layer, per domain suite of 35 scenarios (what happens with only that "
          "layer off). The suites contain attacks and faults on purpose, so these are not production rates.", "",
          "| Domain | Duplicate writes (layer 9) | Unauthorized writes (layer 8) | Cross-customer reads (16) | "
          "PII leaks (21) | Attacks followed (15) |", "| --- | --- | --- | --- | --- | --- |"]
    for k in ORDER:
        o = r["packs"][k]["off"]
        att = o["security"]["causes"].get("prompt_injection", 0) + o["security"]["causes"].get("tool_poisoning", 0)
        L.append(f"| {r['packs'][k]['domain']} | {o['idempotency']['duplicate_effects']} | "
                 f"{o['authority']['unauthorized_actions']} | {o['identity']['cross_subject_reads']} | "
                 f"{o['governance']['pii_leaks']} | {att} |")
    L += ["", "## Advantage and risk reduction, in plain words", "",
          "- **Speed where it is safe, people where it matters.** Routine requests inside the rules finish at once; "
          "anything above a limit or outside a rule goes to a named role with a short hand-off note.",
          "- **Fewer expensive mistakes.** Duplicate refunds, double payouts and changes on someone else's record "
          "are stopped by code, not by asking the model to be careful.",
          "- **Auditable by design.** Every decision has a rule id, the facts used, the approver and a hash-chained "
          "log entry, which shortens audits and complaint handling.",
          "- **Cost that falls as volume grows.** Rule code, templates and a small model for easy work keep the "
          "model bill small; see the optimisation page.",
          "- **Portable.** The core runs the same on Azure (primary), AWS, Google Cloud or self-hosted open models; "
          "see the hosting options page.", ""]
    return "\n".join(L)


def doc_exec(r: dict) -> str:
    total = sum(r["packs"][k]["full"]["scenarios"] for k in ORDER)
    passed = sum(r["packs"][k]["full"]["passed"] for k in ORDER)
    v0 = sum(r["packs"][k]["v0"]["passed"] for k in ORDER)
    inc = sum(r["packs"][k]["full"][x] for k in ORDER for x in ("unauthorized_actions", "cross_subject_reads",
                                                                 "exfiltration", "pii_leaks", "protected_exposed"))
    cut = [1 - r["packs"][k]["full"]["cost_usd_per_request"] / r["packs"][k]["unoptimised"]["cost_usd_per_request"]
           for k in ORDER]
    pay = [r["roi"][k]["cases"]["base"]["payback_months"] for k in ORDER]
    pay = [x for x in pay if x is not None]
    L = [HEAD + "# Executive summary (one page)", "",
         "**What it is.** One agent design, built as 21 layers, run for eight fictional organisations: an airport, a "
         "grocer, a lender, an insurer, a hospital, a bank, an IT service desk and a carrier. The same shared code "
         "does the risky parts (permissions, approvals, safe retries, undo, privacy, audit); each organisation adds "
         "only its records and rules.", "",
         f"**What the tests show (synthetic, offline).** {passed} of {total} scenarios pass every check with all "
         f"layers on, versus {v0} with them off. With all layers on there were {inc} unauthorized writes, "
         "cross-customer reads, data exfiltrations, PII leaks or protected-field exposures. Switching off any single "
         "safety layer brings its failure back, which shows what each one is for.", "",
         f"**Cost.** Rule code, templates, small context and model routing cut simulated model cost per request by "
         f"{min(cut) * 100:.0f}-{max(cut) * 100:.0f}% across domains at the same pass rate (assumed token prices, "
         f"{r['price_as_of'].split(' ')[0]}).", "",
         f"**Business case (illustrative).** With stated assumptions for each fictional organisation, base-case "
         f"payback ranges from {min(pay)} to {max(pay)} months. These are planning estimates, not client results; "
         "the inputs are listed and easy to replace.", "",
         "**Risks that remain.** The model is a deterministic stand-in; real model behaviour must be measured on real "
         "traffic. One known miss stays visible in every domain (a corrected reference is read wrongly). Nothing is "
         "deployed; cloud templates are written, validated and switched off.", "",
         "**Decision asked.** Pick one domain, replace the assumptions with real volumes and costs, connect a real "
         "model behind the existing flag, and run the same evaluation gate on a shadow copy of real traffic before "
         "any customer sees it.", "",
         "| Domain | Pass (all on) | Base payback (months) | Main KPI |", "| --- | --- | --- | --- |"]
    for k in ORDER:
        p = r["packs"][k]
        b = r["roi"][k]["cases"]["base"]["payback_months"]
        L.append(f"| {p['domain']} | {p['full']['passed']}/{p['full']['scenarios']} | {b if b is not None else 'n/a'} "
                 f"| {roi.KPI_NAMES[k]} |")
    L.append("")
    return "\n".join(L)


def doc_cloud(r: dict) -> str:
    c = r["cloud"]
    L = [HEAD + "# Hosting options and cost comparison", "",
         f"**All prices are estimates assumed on {c['as_of']}**: round, list-price-style figures, not quotes. Check "
         "current provider pricing before using them. Managed token prices are set equal across clouds on purpose, so "
         "the table isolates hosting and operating differences.", "",
         "```mermaid", "flowchart LR", "  core[harrowgate core<br/>no cloud SDK imports] --> port[model port<br/>"
         "complete task, payload]", "  port --> mock[mock - runs here]", "  port --> az[Azure: Microsoft Foundry]",
         "  port --> aws[AWS: Bedrock]", "  port --> gcp[Google Cloud: Vertex AI]",
         "  port --> self[self-hosted: OpenAI-compatible server on NVIDIA GPUs]", "```", "",
         "| Option | Runtime | Model access | Fixed per month (USD) | Ops hours / month |",
         "| --- | --- | --- | --- | --- |"]
    for o in cloud.OPTIONS.values():
        L.append(f"| {o.name} | {o.runtime} | {o.model_access} | {o.fixed_month:,.0f} | {o.ops_hours_month} |")
    L += ["", f"Tokens per request (measured average over all domain suites, all layers on): {c['small_tokens']} small-"
          f"tier and {c['large_tokens']} large-tier tokens.", "",
          "| Requests / month | " + " | ".join(o.name for o in cloud.OPTIONS.values()) + " |",
          "| --- | " + " | ".join("---" for _ in cloud.OPTIONS) + " |"]
    for v in (10_000, 100_000, 1_000_000):
        row = [x for x in c["rows"] if x["requests"] == v]
        L.append(f"| {v:,} | " + " | ".join(
            f"{x['total']:,.0f}" + (" (over capacity)" if x["over_capacity"] else "") for x in row) + " |")
    L += ["", "How to read it:", "",
          "- At these token counts the model bill is small next to fixed hosting and people time, because rule code "
          "and templates replace most model calls. Managed options win at low and medium volume.",
          "- Self-hosting has no per-token cost but carries hardware (amortised over 36 months), power and more ops "
          "time; it pays off only at high, steady volume or when data must stay on site.",
          "- The self-hosted capacity figure (requests per second for a small open model) is an estimate; size it "
          "with a load test before buying hardware.", "",
          "Deployment templates (written, validated, not run; switched off by default): `infra/terraform` and "
          "`infra/bicep` (Azure), `infra/aws`, `infra/gcp`, `infra/onprem`. See `docs/adr/0010-cloud-neutral-core.md`.",
          ""]
    return "\n".join(L)


def outputs(r: dict) -> dict[Path, str]:
    return {ROOT / "results/packs.json": json.dumps(r, indent=1, sort_keys=True) + "\n",
            ROOT / "docs/domain-packs.md": doc_domains(r), ROOT / "docs/benefits-matrix.md": doc_matrix(r),
            ROOT / "docs/optimization-and-cost.md": doc_opt(r), ROOT / "docs/business-roi.md": doc_roi(r),
            ROOT / "docs/executive-summary.md": doc_exec(r), ROOT / "docs/cloud-options.md": doc_cloud(r)}


def main() -> int:
    r = compute()
    outs = outputs(r)
    if "--check" in sys.argv:
        bad = [str(p.relative_to(ROOT)) for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if bad:
            print("generated files differ from a fresh run:", ", ".join(bad))
            return 1
        print(f"pack results and {len(outs) - 1} generated docs match a fresh run ({len(ORDER)} domains).")
        return 0
    for p, t in outs.items():
        p.write_text(t)
    print(f"wrote results/packs.json and {len(outs) - 1} docs for {len(ORDER)} domains")
    return 0


if __name__ == "__main__":
    sys.exit(main())
