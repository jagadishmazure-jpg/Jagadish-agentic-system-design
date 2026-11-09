# Layer 4 - Context design

**Question:** what exactly does each decision get to see?

## Why it matters

Sending "everything" makes answers slower, costlier and less accurate, and it hides old data inside
fresh data. The classic airport failure is a gate read from a cached copy taken before the gate moved.

## How Harrowgate does it

```mermaid
flowchart LR
    RAW[(Raw information<br/>flight board, profiles, bags,<br/>orders, FAQ - about 1,500 tokens)] --> CB[Context builder]
    SPEC[Decision spec<br/>e.g. duty_free needs flight,<br/>location, queue, order] --> CB
    CB --> PKT[Context packet<br/>about 60 tokens<br/>+ source and age of each field]
    CACHE[(Flight cache)] -->|age <= 5 min| CB
    LIVE[flight_status tool] -->|age > 5 min| CB
```

- Each decision type declares at most four fields ([`harrowgate/context.py`](../../harrowgate/context.py)).
- Every field records where it came from and how old it is; the trace keeps that record.
- Volatile flight data older than the spec limit (5 minutes) is fetched live.
- Reads are memoised per request, so the same fact is not fetched twice.
- A passenger can only see their own orders (boundary B3).
- Preferences come from memory only if the passenger agreed (layer 5).

**Measured (synthetic suite):** packets average 57.9<!-- m:final.context.avg_packet_tokens --> tokens against
1530<!-- m:final.context.avg_raw_tokens --> for everything, a 96.2%<!-- m:final.context.reduction --> reduction. Turning the
freshness check on was the first change the learning loop released (layer 14).

## Tests

`tests/test_l04_context.py`: packet size, stale cache refetched, stale cache used when the check is
off, fresh cache trusted, small field lists, no reads of other passengers' orders, memory only with
consent.

## Trade-offs

A time-based rule cannot see a change that lands inside the window. Four scenarios show that miss on
purpose; event-driven invalidation is Planned.
