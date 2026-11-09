"""Domain packs: the same layered design applied to other fictional organisations.

Each pack is data plus two small functions (what to propose, and the authority rules). The engine
in `engine.py` supplies every layer: input guard and injection scan, model routing, structured
output with repair, context building with minimum-necessary fields, freshness with change events,
identity-checked tool calls through the JSON-RPC tool server, policy decisions with signed tokens,
human approval, idempotent writes, sagas with compensation, durable checkpoints, egress control,
PII masking, hash-chained audit and tracing.
"""

from .registry import PACKS, get_pack

__all__ = ["PACKS", "get_pack"]
