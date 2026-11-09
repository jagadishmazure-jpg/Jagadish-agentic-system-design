"""Agent-to-agent handoff envelope (layer 9).

When one agent needs another (the journey agent finds a gate change and asks the baggage agent
about the bag), it sends a typed task envelope rather than its whole conversation. The envelope
names the intent, carries references to facts instead of copies, and is checked against what the
receiving agent says it accepts.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

_ids = itertools.count(1)


@dataclass
class Handoff:
    from_agent: str
    to_agent: str
    intent: str
    context_refs: dict
    reason: str
    status: str = "submitted"
    task_id: str = field(default_factory=lambda: f"task-{next(_ids)}")

    def to_message(self) -> dict:
        return {"type": "task", **asdict(self)}


class HandoffError(ValueError):
    pass


def validate_handoff(h: Handoff, accepts: dict[str, set[str]]) -> None:
    if h.to_agent not in accepts:
        raise HandoffError(f"unknown agent {h.to_agent}")
    if h.intent not in accepts[h.to_agent]:
        raise HandoffError(f"{h.to_agent} does not accept '{h.intent}'")
    if h.from_agent == h.to_agent:
        raise HandoffError("an agent cannot hand off to itself")
    big = [k for k, v in h.context_refs.items() if isinstance(v, dict | list) and len(str(v)) > 200]
    if big:
        raise HandoffError(f"pass references, not payloads: {big}")
