"""Layer 18 - Caching and freshness: time limits are not enough, so listen for changes.

A time limit (TTL) on cached data protects against old data, but not against data that changed a
minute after it was cached. Systems of record publish a change event whenever a volatile record
changes. Every cache keeps a cursor into that change feed and, before it answers, evicts any entry
that changed after it was stored. No extra tool call is needed when nothing changed.

`AnswerCache` reuses generated answers for repeated questions, keyed by the version of the document
they came from, so an edited document can never be served from an old answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChangeEvent:
    seq: int
    table: str
    key: str
    at: int


@dataclass
class ChangeFeed:
    events: list[ChangeEvent] = field(default_factory=list)

    def publish(self, table: str, key: str, at: int) -> ChangeEvent:
        ev = ChangeEvent(len(self.events) + 1, table, key, at)
        self.events.append(ev)
        return ev

    def since(self, cursor: int) -> list[ChangeEvent]:
        return self.events[cursor:]

    @property
    def head(self) -> int:
        return len(self.events)


@dataclass
class Entry:
    data: dict
    fetched_at: int


@dataclass
class VersionedCache:
    """TTL cache that can also consume a change feed. Keys are (namespace, table, key)."""

    ttl: int
    use_events: bool = True
    entries: dict[tuple, Entry] = field(default_factory=dict)
    cursor: int = 0
    evictions: int = 0

    def put(self, ns: str, table: str, key: str, data: dict, now: int) -> None:
        self.entries[(ns, table, key)] = Entry(dict(data), now)

    def sync(self, feed: ChangeFeed | None) -> int:
        """Evict every entry that changed after it was cached. Returns how many were evicted."""
        if not self.use_events or feed is None:
            return 0
        n = 0
        for ev in feed.since(self.cursor):
            for k in [k for k in self.entries if k[1] == ev.table and k[2] == ev.key]:
                if ev.at >= self.entries[k].fetched_at:
                    del self.entries[k]
                    n += 1
        self.cursor = feed.head
        self.evictions += n
        return n

    def get(self, ns: str, table: str, key: str, now: int, feed: ChangeFeed | None = None,
            ttl: int | None | str = "default") -> Entry | None:
        """`ttl=None` means no time limit (only change events, if any, evict)."""
        self.sync(feed)
        e = self.entries.get((ns, table, key))
        limit = self.ttl if ttl == "default" else ttl
        if e is None or (limit is not None and now - e.fetched_at > limit):
            return None
        return e


@dataclass
class AnswerCache:
    """Reuse a generated answer only while the source document version is unchanged."""

    entries: dict[tuple, str] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, ns: str, question: str, doc_id: str, doc_version: int) -> str | None:
        hit = self.entries.get((ns, " ".join(question.lower().split()), doc_id, doc_version))
        if hit is None:
            self.misses += 1
        else:
            self.hits += 1
        return hit

    def put(self, ns: str, question: str, doc_id: str, doc_version: int, answer: str) -> None:
        self.entries[(ns, " ".join(question.lower().split()), doc_id, doc_version)] = answer
