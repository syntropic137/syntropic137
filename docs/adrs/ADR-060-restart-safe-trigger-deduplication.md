# ADR-060: Restart-Safe Trigger Deduplication

## Status

**Accepted** — 2026-04-12

## Context

### The restart storm bug

When the Syntropic137 stack restarts (deployment, crash recovery, or manual `docker compose down && up`), a cascade of failures causes every recent GitHub event to be re-processed, firing triggers and dispatching workflow executions that already ran. For self-hosted users paying per-execution, this creates an unexpected billing event on every restart.

The root cause is a chain of four independent volatile-state failures that all happen simultaneously on restart:

1. **ETag cache lost** — `GitHubEventsAPIClient` stores ETags in an in-memory `dict`. On restart, the poller sends no `If-None-Match` header, and GitHub returns up to 300 recent events instead of `304 Not Modified`.

2. **Dedup state lost** — `RedisDedupAdapter` uses `SETNX + TTL` in Redis. When Redis restarts (or is flushed), all dedup keys are gone. Every re-fetched event passes dedup as "new."

3. **Guard 4 bypassed** — The delivery idempotency guard checks `payload._delivery_id`, but polled events have an empty `delivery_id` (webhook-only field). Guard 4 is **silently skipped for all polled events**, providing zero protection in polling mode.

4. **Guard 6 reset** — The concurrency guard (`has_running_execution`) is in-memory only. On restart, it's empty — no running executions are tracked, so all triggers pass the concurrency check.

### Impact

- A restart with 5 active triggers and 200 recent events can dispatch dozens of workflow executions simultaneously
- Each execution consumes API tokens ($5-10+ per Claude session)
- Self-hosted users have reported this on stack restarts and updates
- The fail-open dedup design (ADR-050) is correct for transient Redis issues but catastrophic when Redis restarts alongside the application

### Why ADR-050's dedup design is insufficient

ADR-050 made a reasonable trade-off: Redis SETNX is fast and atomic, and the in-memory fallback handles test/offline scenarios. The assumption was that Redis would rarely restart at the same time as the application. But in Docker Compose stacks, **all services restart together** — invalidating this assumption for every self-hosted deployment.

## Decision

### 1. Postgres-backed dedup (durable, restart-safe)

Replace Redis as the primary dedup backend with PostgreSQL (TimescaleDB), which is already in the stack and backed by a persistent Docker volume.

**Table:** `dedup_keys`

```sql
CREATE TABLE IF NOT EXISTS dedup_keys (
    key TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Implementation:** `PostgresDedupAdapter` implementing `DedupPort`

- `is_duplicate()`: `INSERT INTO dedup_keys (key) VALUES ($1) ON CONFLICT DO NOTHING RETURNING key` — atomic check-and-mark in one round trip. If no row returned → duplicate.
- `mark_seen()`: same INSERT, ignore result.
- **TTL cleanup**: `DELETE FROM dedup_keys WHERE created_at < now() - interval '7 days'` — run on adapter initialization and hourly thereafter.
- Table auto-created on first use, matching the `PostgresCheckpointStore` pattern.

**Adapter selection priority:** Postgres (if DB pool available) > Redis (optional fast cache) > In-memory (tests only).

Redis dedup becomes an optional performance optimization, not a correctness requirement.

**Location:** `packages/syn-adapters/src/syn_adapters/dedup/postgres_dedup.py`

### 2. Persisted poller cursor (ETag + last event ID)

Persist the GitHub Events API ETag and last-seen event ID in PostgreSQL so the poller resumes from where it left off after a restart.

**Table:** `poller_cursors`

```sql
CREATE TABLE IF NOT EXISTS poller_cursors (
    repo TEXT PRIMARY KEY,
    etag TEXT NOT NULL DEFAULT '',
    last_event_id TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Implementation:** `PollerCursorStore` with `save_cursor(repo, etag, last_event_id)` / `load_cursor(repo) → (etag, last_event_id)`.

The `GitHubEventsAPIClient` accepts an optional cursor store. On startup, it loads stored ETags. On each poll, it persists the new ETag + newest event ID. Without the store (tests), behavior is unchanged — volatile in-memory dict.

**Location:** `packages/syn-adapters/src/syn_adapters/github/poller_cursor_store.py`

### 3. Fix Guard 4 for polled events

Guard 4 (delivery idempotency) currently checks `payload._delivery_id`, which is empty for all polled events. Fix: use `dedup_key` as a fallback idempotency identifier.

- `EventPipeline.ingest()` injects `_dedup_key` into the payload alongside `_delivery_id`
- Guard 4 falls back to `_dedup_key` when `_delivery_id` is empty
- Since `dedup_key` is content-based and identical across sources, this provides cross-source idempotency for polled events

The guard state is rebuilt from the event store on startup (via `TriggerQueryProjection`), so it is persistent.

### 4. Global dispatch rate limiter (Guard 7)

A safety-net circuit breaker that caps the number of workflow dispatches in a sliding window, regardless of what goes wrong upstream.

- **Default:** 10 dispatches per 60 seconds (configurable via `SYN_POLLING_DISPATCH_RATE_LIMIT` and `SYN_POLLING_DISPATCH_RATE_WINDOW_SECONDS`)
- **Behavior:** Returns `GuardResult(passed=False, retryable=True)` — events are not lost, just delayed
- **Scope:** Global across all triggers (not per-trigger)
- Uses the existing `TriggerQueryStore` to count recent fires

This provides protection against novel failure modes we haven't anticipated — any bug that causes a flood of trigger evaluations will be capped before it causes a billing catastrophe.

### 5. InMemoryAdapter base class (production guard)

All in-memory adapters that must NOT run in production inherit from a single base class: `InMemoryAdapter` in `packages/syn-adapters/src/syn_adapters/in_memory.py`.

**The problem:** Before this change, the environment check was copy-pasted 7 times across 7 files, with 3 different strategies:

| Strategy | Files | Allowed environments |
|----------|-------|---------------------|
| `settings.uses_in_memory_stores` | `storage/in_memory.py`, `projection_stores/memory_store.py` | test, offline |
| `os.getenv("APP_ENVIRONMENT")` | `control/adapters/memory.py`, `workspace_backends/memory/memory_adapter.py` | test, testing (but not offline) |
| `os.getenv("SYN_ENVIRONMENT")` | `storage/artifact_storage/memory.py` | test only (wrong env var) |
| **None** | `dedup/memory_dedup.py` | **anything (the bug)** |

The inconsistency meant some adapters worked in offline mode and others didn't, and the dedup adapter had no guard at all -- allowing `_create_dedup_adapter()` to silently fall back to in-memory dedup in production when both Postgres and Redis failed.

**The fix:** A single `InMemoryAdapter` base class with one canonical check:

```python
class InMemoryAdapter:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.uses_in_memory_stores:
            raise InMemoryAdapterError(...)
```

- Uses `settings.uses_in_memory_stores` (= `is_test or is_offline`), the canonical check
- All 11 in-memory adapters now inherit from `InMemoryAdapter` or call `assert_test_only()` (for dataclasses that can't inherit `__init__`)
- `_create_dedup_adapter()` raises `RuntimeError` instead of falling back to in-memory -- belt-and-suspenders with the base class guard
- A standalone `assert_test_only()` function is exported for dataclasses (`InMemoryEventStore`, `InMemoryProjectionStore`) that use `__post_init__`

**Location:** `packages/syn-adapters/src/syn_adapters/in_memory.py`

### 6. InMemoryPendingSHAStore: intentional production exception

`InMemoryPendingSHAStore` (`packages/syn-adapters/src/syn_adapters/github/pending_sha_store.py`) is the one in-memory store that intentionally does NOT inherit from `InMemoryAdapter`. It is allowed in production because:

- **Purpose:** Tracks commit SHAs pending check-run polling (#602). When a `pull_request` event arrives, the head SHA is registered. The Checks API poller reads pending SHAs and polls for CI results.
- **Loss on restart is acceptable:** The next `pull_request` event (or Events API poll) re-registers the SHA. Worst case is a delayed check-run poll, not a duplicate execution.
- **No correctness impact:** Unlike dedup state (where loss causes duplicates) or control state (where loss causes orphaned executions), PendingSHA loss causes a temporary gap in check-run awareness that self-heals.
- **No billing impact:** No workflow execution is triggered by PendingSHA alone -- it only enables polling. The dedup layer (section 1) prevents duplicate trigger fires from the polled results.

This exception is intentional and documented. The file carries a comment explaining why it differs from other in-memory stores.

## Consequences

### Positive

- **Restart-safe** — No duplicate workflow executions on stack restart, deployment, or crash recovery
- **Defense in depth** — Four independent layers; any single layer surviving prevents the storm
- **Self-host safe** — Users can restart their stack without worrying about unexpected bills
- **Backwards compatible** — No API changes, no migration needed (tables auto-create), existing Redis dedup still works as a cache layer
- **Polling path hardened** — Guard 4 now works for polled events, closing a silent gap in the safety chain

### Negative

- **Postgres dependency for dedup** — Previously Redis-only; now requires the DB pool. Acceptable since Postgres is already a hard dependency for the event store and checkpoint store
- **Slight latency increase** — Postgres `INSERT ON CONFLICT` is ~1ms vs Redis SETNX ~0.1ms. Negligible for event ingestion rates (<1 event/second typical)
- **Rate limiter can delay legitimate events** — During high-activity bursts (e.g., mass PR review submission), Guard 7 may throttle. The default limit (10/60s) is generous; adjust via config if needed

## Defense in Depth Summary

After this ADR, a restart is protected by four independent layers:

| Layer | Component | What it prevents | Persistent? |
|-------|-----------|-----------------|-------------|
| 1 | Poller cursor (Postgres) | Re-fetching events from GitHub | Yes |
| 2 | Dedup (Postgres) | Re-processing known events | Yes |
| 3 | Guard 4 (fixed) | Re-evaluating triggers for known events | Yes (event store) |
| 4 | Guard 7 (new) | Runaway dispatch from any cause | Stateless (sliding window) |

## Related ADRs

- **ADR-050** — Hybrid Webhook + Polling Event Pipeline (introduced Redis dedup and content-based keys; this ADR hardens the dedup layer)
- **ADR-014** — Checkpointed Projections (the checkpoint pattern reused for cursor persistence)
- **ADR-040** — GitHub Trigger Architecture (trigger rules and safety guards extended by Guard 7)
