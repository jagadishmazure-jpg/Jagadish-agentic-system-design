"""Layer 10 + 11: the process dies right after sending the message; a new process resumes.

v0 has no idempotency keys, so the resumed step sends the message again. v3 replays the stored
result for the same key, so the passenger gets one message.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from a fresh clone without installing

from harrowgate.evaluation import build_world  # noqa: E402
from harrowgate.runtime import SimulatedCrash  # noqa: E402
from harrowgate.system import BASELINE, Config, System  # noqa: E402

SCN = {"passenger_id": "P-1002", "setup": {"now": 520}, "cache_age": None, "faults": {}}
for config in (BASELINE, Config()):
    world, cache = build_world(SCN)
    system = System(world, config, cache=cache)
    try:
        system.handle({"passenger_id": "P-1002", "text": "Which gate is BF117?"}, run_id="r1",
                      crash_after="journey.notify")
    except SimulatedCrash as e:
        print(f"[{config.name}] crashed after step {e}")
    resp = system.resume("r1")
    sent = sum(1 for e in world.effects if e["kind"] == "notification")
    replayed = sum(1 for s in resp.trace.of_kind("tool") if s.attrs.get("replayed"))
    print(f"[{config.name}] resumed -> status {resp.status}; messages delivered: {sent}; replayed by key: {replayed}")
