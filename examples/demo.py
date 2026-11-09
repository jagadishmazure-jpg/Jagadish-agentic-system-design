"""End-to-end demo: one passenger, one message, all 14 layers in play (simulated data, offline)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from a fresh clone without installing

from harrowgate import world as W  # noqa: E402
from harrowgate.evaluation import build_world, evaluate  # noqa: E402
from harrowgate.system import BASELINE, Config, System  # noqa: E402

SCENARIO = {
    "id": "DEMO", "family": "demo", "passenger_id": "P-1001",
    "text": "My gate changed and I still want to pick up my duty-free order. Will my bag make it?",
    "setup": {"now": 520, "gate_change": {"to": "C4", "ago": 5}}, "cache_age": 15, "faults": {},
    "expect": {"status": "done", "check_location": True, "must_call": ["flight_status", "kg_query", "order_status"]},
}


def run(config: Config):
    world, cache = build_world(SCENARIO)
    start, waits = world.passengers["P-1001"]["location"], dict(world.security_wait)
    resp = System(world, config, cache=cache).handle({"passenger_id": "P-1001", "text": SCENARIO["text"]},
                                                     run_id=f"demo-{config.name}")
    return resp, evaluate(SCENARIO, resp, world, start, waits), world


resp, result, world = run(Config())
print(f"Clock {W.hhmm(world.now)} | passenger P-1001 at the central plaza | flight SK204")
print(f"Request : {SCENARIO['text']}")
print(f"Intents : {', '.join(resp.intents)}")
print(f"Plan    : {' -> '.join(s for s in resp.trace.of_kind('route')[0].attrs['steps'])}")
ctx = resp.trace.of_kind("context")[0].attrs
print(f"Context : flight data from {ctx['flight_source']} (cached copy was 15 min old, limit 5) | "
      f"{ctx['tokens']} tokens instead of {ctx['raw_tokens']}")
print(f"Route   : {' > '.join(resp.route)} | ETA {W.hhmm(resp.eta)} | boarding closes "
      f"{W.hhmm(world.boarding_close('SK204'))}")
print("Policy  : " + "; ".join(f"{s.name}={s.attrs['decision']} ({s.attrs['rule']})"
                               for s in resp.trace.of_kind("policy")))
print("Effects : " + "; ".join(e["kind"] for e in world.effects))
print("Message :")
for m in resp.messages:
    print(f"  - {m}")
print(f"Checks  : {sum(result.checks.values())}/{len(result.checks)} passed | tool calls "
      f"{result.metrics['tool_calls']} | tokens {resp.tokens} | simulated latency {resp.trace.sim_ms} ms")
old, old_result, _ = run(BASELINE)
print(f"Same request on v0 (no freshness check): sent to {old.destination} -> root cause "
      f"{old_result.root_cause}")
