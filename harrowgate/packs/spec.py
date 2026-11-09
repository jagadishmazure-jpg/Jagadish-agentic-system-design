"""What a domain pack declares. Everything else comes from the shared layers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WriteTool:
    name: str
    params: dict  # name -> type
    effect: str  # effect kind recorded in the world
    entity_arg: str  # which argument names the main record (for ownership checks)
    compensate: str | None = None  # tool that undoes it
    risk: str = "low"  # low | high (high-risk writes never run on untrusted input)
    updates: dict = field(default_factory=dict)  # field changes applied to the record


@dataclass(frozen=True)
class Plan:
    outcome: str  # act | deny
    rule: str
    proposals: tuple = ()  # (tool, args) pairs, executed in order (a saga when more than one)
    message: str = ""


@dataclass
class PackSpec:
    key: str
    org: str
    domain: str
    use_case: str
    region: str
    id_prefix: str
    entity_table: str
    entity_label: str
    action_intent: str
    action_words: tuple[str, ...]
    status_words: tuple[str, ...]
    writes: tuple[WriteTool, ...]
    records: Callable[[], dict]
    plan: Callable[[dict, dict, int], Plan]  # (entity, customer, now) -> Plan
    authority: Callable[[str, dict, dict], tuple[str, str, str]]  # (tool, args, entity) -> verdict, rule, why
    docs: list[dict]
    allowed_fields: frozenset[str]
    protected_fields: frozenset[str]
    volatile_field: str
    closed_value: str
    injected: Callable[[dict], tuple[str, dict]]  # what a model that obeys injected text would add
    examples: dict  # entity ids for scenario families
    threats: tuple[str, ...]
    regulatory: tuple[str, ...]
    kpis: dict  # business KPI names and assumptions (see roi.py)
    internal_queues: frozenset[str] = frozenset({"review-queue"})
    info_questions: tuple = ()  # (question, doc id)
    status_text: Callable[[dict], str] = lambda e: f"Current status: {e.get('status')}."
