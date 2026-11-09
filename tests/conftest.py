import pytest

from harrowgate import world as W
from harrowgate.evaluation import build_world
from harrowgate.system import Config, System


@pytest.fixture
def world():
    return W.default_world()


def scenario(pid="P-1001", now=520, **kw):
    return {"id": "T", "family": "t", "passenger_id": pid, "text": kw.pop("text", ""),
            "setup": {"now": now, **kw.pop("setup", {})}, "cache_age": kw.pop("cache_age", None),
            "faults": kw.pop("faults", {}), "expect": kw.pop("expect", {"status": "done"}), **kw}


def ask(text, pid="P-1001", now=520, config=None, approver=None, run_id="t1", **kw):
    w, cache = build_world(scenario(pid, now, **kw))
    system = System(w, config or Config(), cache=cache, approver=approver)
    return system.handle({"passenger_id": pid, "text": text}, run_id=run_id), w, system


@pytest.fixture
def run():
    return ask
