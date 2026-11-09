from harrowgate.routing import LARGE, SMALL, Router, TenantBudget, cost_usd, difficulty


def test_difficulty_uses_cheap_features_only():
    assert difficulty("refund WG-1001", 1, 1) == 0
    assert difficulty("refund WG-1001 and tell me the policy", 2, 1) == 2
    assert difficulty(" ".join(["word"] * 40), 2, 2) == 3


def test_router_sends_easy_work_to_small_and_hard_work_to_large():
    r = Router()
    assert r.choose(0) is SMALL and r.choose(1) is SMALL and r.choose(2) is LARGE
    assert Router(enabled=False).choose(0) is LARGE


def test_tenant_budget_refuses_new_work_at_the_cap():
    b = TenantBudget(daily_usd=0.01)
    r = Router(budget=b)
    spent = 0
    while (tier := r.choose(0)) is not None:
        b.charge(cost_usd({tier.name: 500}))
        spent += 1
    assert b.spent <= 0.01 + cost_usd({"small": 500}) and b.refused == 1 and spent > 0


def test_cost_model_uses_tier_prices():
    assert cost_usd({"small": 1000}) == SMALL.usd_per_1k_tokens
    assert cost_usd({"large": 2000}) == 2 * LARGE.usd_per_1k_tokens
