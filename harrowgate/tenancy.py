"""Layer 20 - Multi-tenancy, rate limits and backpressure.

One deployment serves several organisations (tenants). Three rules keep them apart and keep the
system standing under load:

* Isolation in code, not in the prompt: every cache key, state key and memory namespace starts
  with the tenant id (`ns`). The model never chooses the tenant; the platform sets it from the
  authenticated caller.
* Fair share: each tenant has its own token bucket, so one tenant's burst cannot use another
  tenant's capacity (the noisy-neighbour problem).
* Backpressure instead of collapse: the admission queue is bounded. When it is full, low-priority
  work is shed with a clear "try again" answer, while urgent work (a safety or time-critical
  request) is still admitted. Each tenant also has a kill switch.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def ns(tenant: str, *parts: str) -> str:
    if not tenant or ":" in tenant:
        raise ValueError("tenant id must be set by the platform and contain no ':'")
    return ":".join((tenant, *parts))


@dataclass
class TokenBucket:
    rate: float  # tokens added per tick
    burst: int
    tokens: float = -1.0

    def __post_init__(self) -> None:
        if self.tokens < 0:
            self.tokens = float(self.burst)

    def tick(self) -> None:
        self.tokens = min(self.burst, self.tokens + self.rate)

    def take(self) -> bool:
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


@dataclass
class Tenant:
    id: str
    bucket: TokenBucket
    killed: bool = False


@dataclass
class LoadResult:
    admitted: dict[str, int]
    shed: dict[str, int]
    rate_limited: dict[str, int]
    urgent_shed: int
    p95_wait_ticks: float
    served: dict[str, int]


def simulate(tenants: dict[str, Tenant], arrivals: list[tuple[int, str, bool]], *, workers: int,
             queue_cap: int, fair: bool = True) -> LoadResult:
    """arrivals: (tick, tenant, urgent). Each tick: refill buckets, admit, serve `workers` items."""
    queue: list[tuple[int, int, str, bool]] = []  # (priority, arrival tick, tenant, urgent)
    adm = {t: 0 for t in tenants}
    shed = {t: 0 for t in tenants}
    rl = {t: 0 for t in tenants}
    served = {t: 0 for t in tenants}
    waits: list[int] = []
    urgent_shed = 0
    last = max(a[0] for a in arrivals) if arrivals else 0
    by_tick: dict[int, list] = {}
    for a in arrivals:
        by_tick.setdefault(a[0], []).append(a)
    tick = 0
    while tick <= last or queue:
        for t in tenants.values():
            t.bucket.tick()
        for _, tid, urgent in by_tick.get(tick, []):
            ten = tenants[tid]
            if ten.killed:
                shed[tid] += 1
                continue
            if fair and not urgent and not ten.bucket.take():
                rl[tid] += 1
                continue
            if len(queue) >= queue_cap:
                if urgent:
                    lows = [i for i, q in enumerate(queue) if not q[3]]
                    if lows:
                        victim = queue.pop(lows[-1])
                        shed[victim[2]] += 1
                        adm[victim[2]] -= 1
                    else:
                        urgent_shed += 1
                        shed[tid] += 1
                        continue
                else:
                    shed[tid] += 1
                    continue
            queue.append((0 if urgent else 1, tick, tid, urgent))
            adm[tid] += 1
        queue.sort()
        for _ in range(workers):
            if not queue:
                break
            _, at, tid, _ = queue.pop(0)
            waits.append(tick - at)
            served[tid] += 1
        tick += 1
    waits.sort()
    p95 = waits[min(len(waits) - 1, int(round(0.95 * (len(waits) - 1))))] if waits else 0
    return LoadResult(adm, shed, rl, urgent_shed, float(p95), served)


@dataclass
class TenantScopedStore:
    """A key-value store that refuses keys outside the caller's tenant."""

    data: dict[str, object] = field(default_factory=dict)

    def put(self, tenant: str, key: str, value) -> None:
        self.data[ns(tenant, key)] = value

    def get(self, tenant: str, key: str):
        return self.data.get(ns(tenant, key))
