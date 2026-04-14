# 05 - Temporal: The Definition of "New"

**Status:** COMPLETE

## Question

> "What is this system's definition of 'new'?"

## Per-Source Definition

| Source | "New" means | Mechanism | Durable? | Restart safe? |
|--------|-----------|-----------|----------|--------------|
| Webhook | Unseen dedup key | Postgres dedup table | Yes (7-day TTL) | Yes |
| Events API poll | Unseen ETag from GitHub | Postgres cursor store | Yes (fail-open on load) | Mostly |
| Check-run poll | Pending SHA in store | **In-memory only** | **No** | **No** |
| Projection catch-up | Event position > checkpoint | Postgres checkpoint | Yes (if saved) | Gap between dispatch and save |

## Cursor Persistence

| Poller | Cursor store | Durable? | Atomic with processing? |
|--------|-------------|----------|------------------------|
| Events API | `PostgresPollerCursorStore` (etag + last_event_id) | Yes | **No** - cursor saved after processing |
| Check-run | `InMemoryPendingSHAStore` | **No** | N/A - lost on restart |

**last_event_id is write-only**: The Events API client stores it
(`events_api_client.py:121`) but **never reads it back or uses it for
filtering**. It's dead metadata. The sole cursor mechanism is the ETag.

## Dedup Key TTL

- **Postgres dedup**: 7-day TTL (`postgres_dedup.py:22`), cleanup hourly
- **Redis dedup**: 24-hour TTL (`polling.py:52`)
- **Mismatch**: Settings file says 24h, Postgres adapter defaults to 7 days

**Risk**: After 7 days, a dedup key expires. If the same logical event
is re-observed (e.g., poller restart after long downtime), it passes dedup
as "new." Safety guards provide second-layer protection but are imperfect
(daily limits reset each day, cooldowns only check recent fires).

## Events API Pagination Gap

**The Events API client fetches only the first page (30 events).**

No `per_page` or `page` parameters are sent (`events_api_client.py:80`).
GitHub returns up to 30 events per page by default. If >30 events occur
between polls (e.g., during a 300s SAFETY_NET interval, or after a
restart), only the most recent 30 are seen. The rest are **permanently
lost** to this system.

This is not a correctness bug (missed events can't cause duplicate spend)
but it is a reliability gap (triggers may never fire for events that fell
off the first page).

## Ordering

**No out-of-order handling exists.**

- No sequence number tracking
- No watermark
- No ordering guarantees enforced
- Events processed in arrival order

If "PR closed" arrives before "PR opened," both are evaluated
independently against trigger rules. The dedup keys are different
(different actions), so both pass.

The aggregate guards (max_attempts, cooldown) implicitly tolerate
out-of-order by being count/time-based rather than sequence-based.
This is acceptable for the current trigger model.

## Findings

1. **Check-run poller has no durable cursor** - pending SHAs lost on
   restart, brief gap until next PR event re-registers
2. **Events API pagination not implemented** - events beyond first page
   are silently dropped
3. **Dedup TTL mismatch** between settings (24h) and Postgres adapter (7d)
4. **last_event_id stored but never used** - dead code
5. **No out-of-order handling** - acceptable for current model but worth
   noting as the system scales
