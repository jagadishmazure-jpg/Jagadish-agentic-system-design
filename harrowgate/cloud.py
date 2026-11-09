"""Hosting options cost model: Azure (primary), AWS, GCP and self-hosted open models.

All prices are ESTIMATES assumed for modelling on `AS_OF`; they are round, list-price-style figures,
not quotes, and they change. Replace them with current provider pricing before using the output.
Token prices for the managed options are set equal on purpose, so the comparison isolates hosting
and operating differences; model choice is handled by the router (layer 17).
"""

from __future__ import annotations

from dataclasses import dataclass

AS_OF = "2026-11-09"
LABEL = f"ESTIMATES assumed on {AS_OF}; not quotes; verify against current provider pricing"


@dataclass(frozen=True)
class HostingOption:
    key: str
    name: str
    runtime: str
    model_access: str
    fixed_month: float  # always-on hosting, secrets, logs, ingress (USD, estimate)
    small_per_1k: float  # USD per 1K tokens, small tier (estimate)
    large_per_1k: float  # USD per 1K tokens, large tier (estimate)
    capacity_rps: float | None = None  # self-hosted only: sustained requests per second (estimate)
    ops_hours_month: float = 2.0  # people time to run it (estimate)
    ops_hourly: float = 90.0


OPTIONS = {
    "azure": HostingOption("azure", "Azure", "Container Apps (1 always-on replica)",
                           "Microsoft Foundry model deployment", 85.0, 0.0003, 0.0030),
    "aws": HostingOption("aws", "AWS", "ECS on Fargate (1 task) + load balancer", "managed model endpoint (Bedrock)",
                         80.0, 0.0003, 0.0030),
    "gcp": HostingOption("gcp", "Google Cloud", "Cloud Run (1 minimum instance)", "managed model endpoint (Vertex AI)",
                         70.0, 0.0003, 0.0030),
    "onprem": HostingOption("onprem", "Self-hosted", "2 small NVIDIA GPU servers (24 GB each), open 8B model",
                            "OpenAI-compatible server (for example vLLM)", 2 * 9000 / 36 + 160, 0.0, 0.0,
                            capacity_rps=6.0, ops_hours_month=10.0),
}


def monthly_cost(opt: HostingOption, requests: int, small_tokens: float, large_tokens: float) -> dict:
    tokens = requests * (small_tokens * opt.small_per_1k + large_tokens * opt.large_per_1k) / 1000
    ops = opt.ops_hours_month * opt.ops_hourly
    total = opt.fixed_month + tokens + ops
    over = None
    if opt.capacity_rps is not None:
        peak_rps = requests / (30 * 24 * 3600) * 10  # assume peak is 10x the average rate
        over = peak_rps > opt.capacity_rps
    return {"option": opt.key, "requests": requests, "fixed": round(opt.fixed_month, 2), "tokens": round(tokens, 2),
            "ops": round(ops, 2), "total": round(total, 2), "per_1k_requests": round(1000 * total / requests, 3),
            "over_capacity": over}


def compare(volumes: list[int], small_tokens: float, large_tokens: float) -> list[dict]:
    return [monthly_cost(o, v, small_tokens, large_tokens) for v in volumes for o in OPTIONS.values()]
