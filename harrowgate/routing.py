"""Layer 17 - Cost, model routing and budgets.

Not every step needs the biggest model. The router scores how hard a request is from cheap,
deterministic features (how many things it asks for, length, references to several records) and
sends easy work to a small tier and hard work to a large tier. If the small tier's answer fails
schema validation, the request is retried once on the large tier (a cascade), so cost never buys a
wrong answer silently.

Budgets are enforced in code: per request (tokens, tool calls, simulated latency) by the runtime
(layer 10), and per tenant per day here. When a tenant is close to its cap the router degrades to
the small tier for easy work and refuses new work at the cap instead of overspending.

Prices below are ASSUMPTIONS for a cost model, not quotes; see `PRICE_AS_OF`. Change them in one
place and every report regenerates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRICE_AS_OF = "2026-11-09 (assumed list-price-style figures for modelling, not quotes; verify before use)"


@dataclass(frozen=True)
class ModelTier:
    name: str
    usd_per_1k_tokens: float  # blended input+output, ASSUMED
    latency_ms_per_call: int  # simulated
    max_difficulty: int  # simulated capability: highest difficulty it answers reliably


SMALL = ModelTier("small", 0.0003, 180, 1)
LARGE = ModelTier("large", 0.0030, 450, 3)
TIERS = {"small": SMALL, "large": LARGE}


def difficulty(text: str, intents_hint: int, ids: int) -> int:
    """0 = trivial, 3 = hard. Deterministic features only, no model call."""
    d = 0
    if intents_hint > 1:
        d += 2
    if ids > 1:
        d += 1
    if len(text.split()) > 28:
        d += 1
    return min(d, 3)


@dataclass
class TenantBudget:
    daily_usd: float
    spent: float = 0.0
    refused: int = 0

    @property
    def left(self) -> float:
        return self.daily_usd - self.spent

    def charge(self, usd: float) -> None:
        self.spent += usd


@dataclass
class Router:
    enabled: bool = True
    budget: TenantBudget | None = None
    degrade_at: float = 0.9  # share of the daily cap after which easy work stays on small
    decisions: list[dict] = field(default_factory=list)

    def choose(self, diff: int) -> ModelTier | None:
        if self.budget is not None and self.budget.left <= 0:
            self.budget.refused += 1
            self.decisions.append({"difficulty": diff, "tier": None, "why": "tenant daily budget used up"})
            return None
        if not self.enabled:
            tier, why = LARGE, "routing off: always large"
        elif diff <= SMALL.max_difficulty:
            tier, why = SMALL, "easy request"
        elif self.budget is not None and self.budget.spent >= self.degrade_at * self.budget.daily_usd:
            tier, why = LARGE, "hard request (budget near cap, still needs large)"
        else:
            tier, why = LARGE, "hard request"
        self.decisions.append({"difficulty": diff, "tier": tier.name, "why": why})
        return tier


def cost_usd(tokens_by_tier: dict[str, int]) -> float:
    return sum(TIERS[t].usd_per_1k_tokens * n / 1000 for t, n in tokens_by_tier.items())
