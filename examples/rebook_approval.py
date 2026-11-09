"""Layers 7, 8, 11: a missed flight. The agent proposes; policy and a human decide; a saga executes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from a fresh clone without installing

from harrowgate.evaluation import build_world  # noqa: E402
from harrowgate.system import Config, System  # noqa: E402

for answer in ("approve", "deny", None):
    scn = {"passenger_id": "P-1002", "setup": {"now": 630, "location": "PLAZA"}, "cache_age": None, "faults": {}}
    world, cache = build_world(scn)
    system = System(world, Config(), cache=cache, approver=lambda p, d, a=answer: a)
    resp = system.handle({"passenger_id": "P-1002", "text": "I missed BF117. Can you rebook me on a later flight?"},
                         run_id="rb")
    rules = [f"{s.name}:{s.attrs['decision']}" for s in resp.trace.of_kind("policy")]
    print(f"human={answer!s:<7} status={resp.status:<16} policy={rules}")
    print(f"  effects={[e['kind'] for e in world.effects]}")

scn = {"passenger_id": "P-1001", "setup": {"now": 640, "location": "PLAZA"}, "cache_age": None,
       "faults": {"timeout": {"rebook_passenger": 3}}}
world, cache = build_world(scn)
resp = System(world, Config(), cache=cache).handle({"passenger_id": "P-1001", "text": "I missed SK204, rebook me"},
                                                   run_id="rb2")
print(f"booking system down -> status={resp.status}; saga={resp.data['saga']}")
print(f"  effects={[e['kind'] for e in world.effects]}")
