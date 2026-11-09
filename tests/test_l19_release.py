from harrowgate.packs import PACKS
from harrowgate.packs.engine import FULL, PackConfig, build_registry
from harrowgate.packs.evaluate import SAFETY, run_pack
from harrowgate.release import ReleaseManifest, ReleaseTrack, canary_bucket, manifest_for, release_gate
from harrowgate.security import tool_fingerprint


def _ids(suite):
    return {r.id: {"passed": r.passed, "checks": r.checks} for r in suite.results}


def test_manifest_id_changes_when_anything_that_matters_changes():
    a = manifest_for(FULL, {"parse": "v3"}, {"easy": "small"}, "abc")
    assert a.id == manifest_for(FULL, {"parse": "v3"}, {"easy": "small"}, "abc").id
    assert a.id != manifest_for(FULL, {"parse": "v4"}, {"easy": "small"}, "abc").id
    assert a.id != manifest_for(PackConfig(saga=False), {"parse": "v3"}, {"easy": "small"}, "abc").id
    reg = build_registry(PACKS["retail"])
    h = "".join(tool_fingerprint(s) for s in reg.values())
    assert a.id != manifest_for(FULL, {"parse": "v3"}, {"easy": "small"}, h).id


def test_canary_bucket_is_stable_and_close_to_the_share():
    ids = [f"req-{i}" for i in range(4000)]
    share = sum(canary_bucket(i, 0.1) for i in ids) / len(ids)
    assert 0.08 < share < 0.12 and canary_bucket("req-7", 0.1) == canary_bucket("req-7", 0.1)


def test_gate_promotes_a_better_candidate_and_rolls_back_a_worse_one():
    pack = PACKS["insurance"]
    old = run_pack(pack, PackConfig(change_events=False))
    new = run_pack(pack, FULL)
    bad = run_pack(pack, PackConfig(idempotency=False))
    good = release_gate(_ids(old), _ids(new), 0.25, SAFETY)
    worse = release_gate(_ids(new), _ids(bad), 0.25, SAFETY)
    assert good.promoted and good.candidate_success > good.current_success
    assert not worse.promoted and worse.regressions and any("fail" in r for r in worse.reasons)


def test_runs_stay_pinned_to_the_manifest_they_started_on():
    m1 = ReleaseManifest({"p": 1}, {}, "h", {})
    m2 = ReleaseManifest({"p": 2}, {}, "h", {})
    track = ReleaseTrack(m1)
    assert track.start_run("r1") == m1.id
    gate = release_gate({"a": {"passed": True, "checks": {}}}, {"a": {"passed": True, "checks": {}}}, 1.0, ())
    assert track.apply(m2, gate) == "promoted" and track.current.id == m2.id
    assert track.pinned_runs["r1"] == m1.id and track.history == [m1.id]
