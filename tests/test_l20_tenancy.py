import pytest

from harrowgate.freshness import VersionedCache
from harrowgate.tenancy import Tenant, TenantScopedStore, TokenBucket, ns, simulate


def test_namespace_is_set_by_the_platform_and_cannot_be_spoofed():
    assert ns("retail", "orders", "WG-1") == "retail:orders:WG-1"
    for bad in ("", "retail:banking"):
        with pytest.raises(ValueError):
            ns(bad, "x")


def test_tenant_scoped_store_never_returns_another_tenants_value():
    s = TenantScopedStore()
    s.put("retail", "pref", "email")
    assert s.get("retail", "pref") == "email" and s.get("banking", "pref") is None


def test_shared_cache_keys_are_split_by_tenant():
    c = VersionedCache(ttl=5)
    c.put("retail", "customers", "C-1", {"name": "A"}, now=0)
    assert c.get("banking", "customers", "C-1", now=1) is None


def _arrivals():
    a = []
    for t in range(30):
        a += [(t, "noisy", False)] * 10
        a += [(t, "quiet", False)]
        if t % 5 == 0:
            a.append((t, "urgent", True))
    return a


def _tenants():
    return {k: Tenant(k, TokenBucket(rate=0.5, burst=3)) for k in ("noisy", "quiet", "urgent")}


def test_fair_share_protects_quiet_tenants_from_a_noisy_neighbour():
    fair = simulate(_tenants(), _arrivals(), workers=3, queue_cap=10, fair=True)
    unfair = simulate(_tenants(), _arrivals(), workers=3, queue_cap=10, fair=False)
    assert fair.served["quiet"] > unfair.served["quiet"]
    assert fair.rate_limited["noisy"] > 0 and fair.urgent_shed == 0


def test_urgent_work_displaces_low_priority_work_when_the_queue_is_full():
    tenants = {"a": Tenant("a", TokenBucket(rate=100, burst=100)), "u": Tenant("u", TokenBucket(1, 1))}
    arr = [(0, "a", False)] * 5 + [(0, "u", True)]
    r = simulate(tenants, arr, workers=1, queue_cap=5, fair=True)
    assert r.served["u"] == 1 and r.shed["a"] == 1 and r.urgent_shed == 0


def test_kill_switch_stops_one_tenant_only():
    t = _tenants()
    t["noisy"].killed = True
    r = simulate(t, _arrivals(), workers=3, queue_cap=10)
    assert r.served["noisy"] == 0 and r.served["quiet"] > 0


def test_token_bucket_refills_up_to_burst():
    b = TokenBucket(rate=1, burst=2)
    assert b.take() and b.take() and not b.take()
    b.tick()
    b.tick()
    b.tick()
    assert b.tokens == 2
