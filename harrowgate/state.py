"""Layer 5 - State and memory, kept in four separate places on purpose.

| Store            | What it holds                                   | Lifetime              | Who writes   |
|------------------|-------------------------------------------------|-----------------------|--------------|
| Knowledge        | airport map, FAQ text (shared facts)            | until republished     | nobody (read)|
| Context packet   | the facts one decision needs right now          | one decision          | context layer|
| Memory           | passenger preferences, only with consent + TTL  | days, then expires    | the passenger|
| Journey state    | run checkpoints and the passenger's phase       | until the trip ends   | runtime layer|

Mixing them causes classic bugs: a preference treated as a fact, an old gate kept as "memory",
or a crash that forgets what was already done. Journey state and memory live in SQLite so a
restarted process resumes where the last one stopped.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


class StateStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)  # API serialises access with a lock
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, plan TEXT NOT NULL, step INTEGER NOT NULL,
                data TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS journey (passenger TEXT PRIMARY KEY, phase TEXT NOT NULL,
                updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS memory (passenger TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                expires_at INTEGER NOT NULL, PRIMARY KEY (passenger, key));
        """)

    # ---- journey state (durable checkpoints)
    def checkpoint(self, run_id: str, plan: list[str], step: int, data: dict, status: str = "running") -> None:
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                        "plan=excluded.plan, step=excluded.step, data=excluded.data, status=excluded.status",
                        (run_id, json.dumps(plan), step, json.dumps(data, sort_keys=True), status))
        self.db.commit()

    def load(self, run_id: str) -> dict | None:
        row = self.db.execute("SELECT plan, step, data, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return {"plan": json.loads(row[0]), "step": row[1], "data": json.loads(row[2]), "status": row[3]}

    def set_phase(self, passenger: str, phase: str, now: int) -> None:
        self.db.execute("INSERT INTO journey VALUES (?,?,?) ON CONFLICT(passenger) DO UPDATE SET "
                        "phase=excluded.phase, updated_at=excluded.updated_at", (passenger, phase, now))
        self.db.commit()

    def phase(self, passenger: str) -> str | None:
        row = self.db.execute("SELECT phase FROM journey WHERE passenger=?", (passenger,)).fetchone()
        return row[0] if row else None

    # ---- memory (preferences: consent required, expires)
    def remember(self, passenger: str, key: str, value, now: int, *, consent: bool, ttl_min: int = 7 * 24 * 60) -> bool:
        if not consent:
            return False
        self.db.execute("INSERT INTO memory VALUES (?,?,?,?) ON CONFLICT(passenger, key) DO UPDATE SET "
                        "value=excluded.value, expires_at=excluded.expires_at",
                        (passenger, key, json.dumps(value), now + ttl_min))
        self.db.commit()
        return True

    def recall(self, passenger: str, now: int) -> dict:
        rows = self.db.execute("SELECT key, value FROM memory WHERE passenger=? AND expires_at>?", (passenger, now))
        return {k: json.loads(v) for k, v in rows}

    def forget(self, passenger: str) -> None:
        self.db.execute("DELETE FROM memory WHERE passenger=?", (passenger,))
        self.db.commit()


@dataclass
class CacheEntry:
    data: dict
    fetched_at: int


class FlightCache:
    """A read-through cache of flight records. Cheap, but it can go stale - layer 4 decides when to trust it."""

    def __init__(self) -> None:
        self.entries: dict[str, CacheEntry] = {}

    def put(self, flight_id: str, data: dict, fetched_at: int) -> None:
        self.entries[flight_id] = CacheEntry(dict(data), fetched_at)

    def get(self, flight_id: str) -> CacheEntry | None:
        return self.entries.get(flight_id)
