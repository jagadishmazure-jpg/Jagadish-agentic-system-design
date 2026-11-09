"""Layer 19 - Versioning and release: know exactly what is running, change it safely, undo it fast.

A release manifest pins everything that changes behaviour: prompt template versions, the model tier
map, a hash of the reviewed tool definitions (layer 15) and every feature flag. Its id is a content
hash, so two identical manifests have the same id and any change produces a new one.

A candidate goes out as a canary: a stable hash of the request id sends a fixed share of traffic to
it. The gate compares candidate and current on the canary slice and on the full offline suite:
safety checks must stay at 100%, success must not drop, and no scenario that used to pass may fail.
Pass -> promote. Fail -> automatic rollback to the current manifest. A run that started on one
manifest finishes on it (runs are pinned), so a rollback never replays old steps under new rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass


@dataclass(frozen=True)
class ReleaseManifest:
    prompts: dict
    models: dict
    tools_hash: str
    flags: dict

    @property
    def id(self) -> str:
        body = json.dumps({"p": self.prompts, "m": self.models, "t": self.tools_hash, "f": self.flags},
                          sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:12]


def manifest_for(config, prompts: dict, models: dict, tools_hash: str) -> ReleaseManifest:
    flags = asdict(config) if is_dataclass(config) else dict(config)
    flags.pop("name", None)
    return ReleaseManifest(prompts, models, tools_hash, flags)


def canary_bucket(request_id: str, share: float) -> bool:
    h = int(hashlib.sha256(request_id.encode()).hexdigest()[:8], 16)
    return (h % 10_000) < int(share * 10_000)


@dataclass
class GateResult:
    promoted: bool
    reasons: list[str]
    canary_n: int
    current_success: float
    candidate_success: float
    regressions: list[str] = field(default_factory=list)


def release_gate(current: dict[str, dict], candidate: dict[str, dict], share: float,
                 safety_keys: tuple[str, ...]) -> GateResult:
    """`current`/`candidate`: scenario id -> {"passed": bool, "checks": {...}} from the same suite."""
    reasons = []
    canary = [sid for sid in sorted(candidate) if canary_bucket(sid, share)]
    if not canary:
        reasons.append("empty canary slice")
    safety_ok = all(candidate[s]["checks"].get(k, True) for s in candidate for k in safety_keys)
    if not safety_ok:
        reasons.append("a safety check failed on the candidate")
    cur = sum(current[s]["passed"] for s in current) / len(current)
    cand = sum(candidate[s]["passed"] for s in candidate) / len(candidate)
    if cand < cur:
        reasons.append(f"success fell from {cur:.4f} to {cand:.4f}")
    regressions = sorted(s for s in current if current[s]["passed"] and not candidate[s]["passed"])
    if regressions:
        reasons.append(f"{len(regressions)} previously passing scenarios now fail")
    canary_bad = [s for s in canary if current[s]["passed"] and not candidate[s]["passed"]]
    if canary_bad:
        reasons.append(f"{len(canary_bad)} canary requests regressed")
    return GateResult(not reasons, reasons or ["all gates passed"], len(canary), round(cur, 4), round(cand, 4),
                      regressions)


@dataclass
class ReleaseTrack:
    current: ReleaseManifest
    history: list[str] = field(default_factory=list)
    pinned_runs: dict[str, str] = field(default_factory=dict)

    def start_run(self, run_id: str) -> str:
        self.pinned_runs[run_id] = self.current.id
        return self.current.id

    def apply(self, candidate: ReleaseManifest, gate: GateResult) -> str:
        if gate.promoted:
            self.history.append(self.current.id)
            self.current = candidate
            return "promoted"
        return "rolled_back"
