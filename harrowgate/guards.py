"""Input guard: spot text that tries to instruct the assistant instead of asking for help.

The guard does not block the request. It sets a flag that the policy layer (layer 8) uses to deny
bookings and seat holds for that request, and it records the match in the trace. FAQ answers and
read-only help still work.
"""

from __future__ import annotations

import re

_PATTERNS = [
    r"ignore (all |any |the )?(previous |prior |above )?(rules|instructions|policy|policies)",
    r"you are now", r"system prompt", r"developer mode", r"act as (an? )?(admin|agent|supervisor)",
    r"free upgrade", r"(upgrade|move) me to (first|business)", r"override (the )?(policy|rules|approval)",
    r"without (any )?approval", r"disregard",
]
_RX = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.I)


def check_input(text: str) -> dict:
    m = _RX.search(text or "")
    return {"untrusted_instruction": bool(m), "match": m.group(0) if m else None, "length": len(text or "")}
