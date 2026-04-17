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
- All in-memory adapters now inherit from `InMemoryAdapter` or call `assert_test_only()` (for dataclasses that can't inherit `__init__`). No exceptions.
- `_create_dedup_adapter()` and `get_pending_sha_store()` raise `RuntimeError` instead of falling back to in-memory -- belt-and-suspenders with the base class guard
- A standalone `assert_test_only()` function is exported for dataclasses (`InMemoryEventStore`, `InMemoryProjectionStore`) that use `__post_init__`

**Location:** `packages/syn-adapters/src/syn_adapters/in_memory.py`

### 6. Cold-Start Fence (HistoricalPoller)

Sections 1-5 protect against **warm restart** (state existed, was lost). But on **cold start** (fresh install, empty database), there is no state to lose -- the poller has no cursor, dedup table is empty, Guard 4 has no history, and Guard 6 tracks no running executions. All 300 historical events from the GitHub Events API pass every layer and fire triggers.

This caused 9 duplicate "Self-Heal PR" executions on the sandbox repo after a fresh install (9/10 OOM-killed: 10 x 4GB containers on a 7.65GB Docker VM).

**The fix: timestamp-based cold-start fence.** On first poll with no persisted cursor, only events created *after* the poller's start time are processed. Historical events are skipped but the cursor is persisted, so subsequent polls resume correctly (warm start).

This is implemented as a base class in the Event Sourcing Platform: `HistoricalPoller`. The template method pattern ensures subclasses cannot bypass the fence:

- `poll()` is concrete (non-overridable) -- enforces the cold-start fence
- `fetch()` and `process()` are abstract -- subclasses implement these
- `check_historical_poller_structure()` fitness function catches subclasses that override `poll()`

**Why timestamp filtering, not blanket skip:** Events that arrive between startup and first poll are genuinely new and should be processed. A blanket "skip everything on first poll" would lose them. The `created_at >= started_at` comparison preserves these events.

**Cold start vs warm restart:**

| Scenario | Cursor exists? | Behavior |
|----------|---------------|----------|
| Warm restart (state lost) | No (was lost) | Cold-start fence: skip historical, keep post-startup |
| Warm restart (state intact) | Yes | Warm start: process all events |
| Fresh install | No (never existed) | Cold-start fence: skip historical, keep post-startup |

**Location:** `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/historical_poller.py`

### 7. Pipeline Safety Net (source_primed)

Belt-and-suspenders with the HistoricalPoller fence. Even if someone bypasses the base class and calls `pipeline.ingest()` directly with historical events, the pipeline checks `NormalizedEvent.source_primed`:

- Default `True` for webhooks (always live) and backwards compatibility
- Set to `False` by the HistoricalPoller during cold start
- Pipeline skips trigger evaluation when `source_primed=False` but still marks dedup

This second layer protects against implementation mistakes where historical events reach the pipeline through a path that doesn't use `HistoricalPoller`.

**Update 2026-04-16 (#694 fix):** The original implementation checked `source_key in self.primed_sources` inside `process()`, but `_prime()` runs before `process()` on the cold-start path, so the check was always `True` -- dead code. The fix uses an explicit `is_replay: bool` kwarg passed from `HistoricalPoller.poll()` directly to `process()`, removing the race-prone state inspection. See Section 9.

**Location:** `packages/syn-domain/.../event_pipeline/normalized_event.py` and `pipeline.py`

### 8. Configurable dispatch concurrency

`BackgroundWorkflowDispatcher.MAX_CONCURRENT` was hardcoded at 10. On a Docker host with limited memory (e.g., 8GB), 10 simultaneous 4GB containers cause OOM kills.

Now configurable via `SYN_POLLING_MAX_CONCURRENT_DISPATCHES` (default 5). This is distinct from `WorkspaceSettings.max_concurrent` (workspace pool capacity) -- dispatch concurrency is a safety limit on how many workflows fire simultaneously from triggers.

**Location:** `packages/syn-shared/src/syn_shared/settings/polling.py`, `apps/syn-api/src/syn_api/_wiring.py`

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

## 9. Eight-Layer Defense in Depth (Bug #694 Fix)

After the #694 cold-start flood (2026-04-16), the defense in depth was extended to eight layers. For a spurious execution to fire on cold start, **all eight** must fail simultaneously.

| # | Layer | Owner | Prevents | Persistent? | Test |
|---|-------|-------|----------|-------------|------|
| 1 | ETag (HTTP 304) | Adapter (`events_api_client.py`) | Wasted bandwidth + spurious re-delivery when nothing changed | Yes (`cursor.etag` in `poller_cursors`) | adapter unit test |
| 2 | HWM filter inside `fetch()` | Domain (`event_ingestion.py`) | Re-delivery of seen events when ETag changes (root cause of #694) | Yes (`cursor.last_event_id`) | `test_cold_start_flood_694.py::TestLayer2HWMFilter` |
| 3 | Cold-start `_started_at` timestamp fence | ESP `HistoricalPoller` | Historical events on first ever poll | N/A (per-instance) | ESP `test_historical_poller.py` |
| 4 | `is_replay` flag from `poll()` to `process()` | ESP + domain service | Cold-start events bypassing safety nets via dead-code path | N/A | `test_is_replay_signal.py` |
| 5 | Pipeline `source_primed` check | Domain `pipeline.py` | Trigger evaluation for unprimed events | N/A | `test_cold_start_flood_694.py::TestLayer4IsReplay` |
| 6 | Content-based dedup (Postgres) | Domain port (`PostgresDedupAdapter`) | Cross-restart re-deliveries | Yes (`dedup_keys`) | dedup integration test |
| 7 | Guard 7 trigger rate limit | Domain | Damage cap if all above fail | Yes (`trigger_rules.fire_count`) | aggregate guard test |
| 8 | Guard 6 per-PR concurrency | Domain | Per-PR duplicate executions | Yes | aggregate guard test |

### Why Layer 2 (HWM filter) is the principal fix

GitHub's Events API ETag is "anything changed?" not "what changed?". When even one event arrives, the ETag changes and GitHub returns the **full** recent list (up to 300 events, 30 days retention). Without an HWM filter, warm-start re-delivery floods the pipeline with already-seen events.

The fix: `GitHubEventsCursor.last_event_id` is a **required** dataclass field. Every save through the typed cursor includes the HWM; every fetch consults it before passing events down. This is poka-yoke: bypass requires constructing the dataclass without the field, which is a type error.

### Why Layer 4 (is_replay) replaces dead code

The original `source_primed=False` belt-and-suspenders relied on `source_key in self.primed_sources` inside `process()`. But ESP's `_prime()` mutates `primed_sources` *before* calling `process()`, so the check was always `True` -- the safety net was dead. The fix passes `is_replay: bool` directly from `poll()` to `process()`, sidestepping the mutated state.

## 10. Hexagonal Architecture and Port Boundaries

The GitHub bounded context owns:

- The event pipeline (`slices/event_pipeline/pipeline.py`)
- The application services (`services/event_ingestion.py`, `services/check_run_ingestion.py`, `services/webhook_health.py`)
- The ports that adapters implement (`syn_domain.contexts.github.ports.{events_api_port,checks_api_port}`)
- The typed cursor (`services/github_events_cursor.py`)

The adapter layer (`packages/syn-adapters/src/syn_adapters/github/`) owns:

- HTTP plumbing (`client.py`, `client_api.py`, `client_jwt.py`, `client_token.py`, `client_endpoints.py`)
- Implementations of the domain ports (`events_api_client.py`, `checks_api_client.py`)
- Persistent storage (`poller_cursor_store.py`, `postgres_pending_sha_store.py`)
- Internal exception types (`GitHubRateLimitError`, `GitHubAppError`)

The application layer (`apps/syn-api/`) owns:

- HTTP routes (`routes/webhooks/processing.py`)
- Composition root (`_wiring.py`)
- Lifecycle management (`services/lifecycle.py`)
- Nothing else.

Architectural fitness functions (CI-enforced):

- `TestGitHubBCPurity` -- `services/` contains no `syn_adapters` imports
- `TestEventsAPIPortAdoption` -- `GitHubEventsAPIClient` explicitly inherits its port
- `TestChecksAPIPortAdoption` -- `GitHubChecksAPIClient` explicitly inherits its port
- `TestGitHubCursorTyped` -- `GitHubEventsCursor.last_event_id` is required
- `TestHistoricalPollerIsReplay` -- `process()` accepts `is_replay` kwarg

## Defense in Depth Summary

After this ADR + the #694 fix, both warm restart and cold start are protected by **eight** independent layers (see Section 9 for detail):

| Layer | Component | What it prevents | Persistent? | Cold start? |
|-------|-----------|-----------------|-------------|-------------|
| 1 | ETag (HTTP 304) | Re-delivery when nothing changed | Yes (cursor) | After first poll |
| 2 | HWM filter (`fetch()`) | Re-delivery when ETag churns -- **#694 fix** | Yes (`last_event_id`) | After first poll |
| 3 | Cold-start fence (`_started_at`) | Historical events on first poll | N/A | Yes |
| 4 | `is_replay` -> `source_primed=False` | Cold-start events bypassing safety nets | N/A | Yes |
| 5 | Pipeline `source_primed` | Trigger eval for unprimed events | N/A | Yes |
| 6 | Dedup (Postgres) | Re-processing known events | Yes | After first event |
| 7 | Guard 7 rate limiter | Runaway dispatch | Stateless | Yes |
| 8 | Guard 6 per-PR concurrency | Per-PR duplicate executions | Yes | Yes |

## Related ADRs

- **ADR-050** — Hybrid Webhook + Polling Event Pipeline (introduced Redis dedup and content-based keys; this ADR hardens the dedup layer)
- **ADR-014** — Checkpointed Projections (the checkpoint pattern reused for cursor persistence)
- **ADR-040** — GitHub Trigger Architecture (trigger rules and safety guards extended by Guard 7)
