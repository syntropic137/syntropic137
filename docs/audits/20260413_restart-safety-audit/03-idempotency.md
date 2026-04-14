# 03 - Idempotency: Dedup Keys and Enforcement

**Status:** COMPLETE

## Question

> "What is the idempotency key for each workflow trigger, and where is
> the idempotency boundary enforced?"

## Dedup Key Inventory

All three sources use the same content-based dedup keys computed by
`compute_dedup_key()` in `event_pipeline/dedup_keys.py`.

| Source | Example dedup key | Stable across sources? |
|--------|------------------|----------------------|
| Webhook | `pr:{repo}:{number}:{action}:{head_sha}` | Yes |
| Events API poll | Same as webhook (normalized) | Yes |
| Check-run poll | `check_run:{repo}:{check_run_id}:{action}` | Yes |
| Unknown event types | SHA-256 hash of full payload | **No** - different payload shapes from different sources produce different hashes |

**Good**: Content-based keys (commit SHA, PR number, check_run ID) mean
the same logical event from webhooks and polling produces the same key.

**Gap**: Unknown event types fall back to payload hashing (line 139),
which will NOT dedup across sources with different payload shapes.

## Enforcement Boundary

Three adapter implementations, selected by priority:

| Priority | Adapter | Storage | TTL | Durable? |
|----------|---------|---------|-----|----------|
| 1 | `PostgresDedupAdapter` | `dedup_keys` table, `INSERT ON CONFLICT DO NOTHING` | 7 days | **Yes** |
| 2 | `RedisDedupAdapter` | Redis `SETNX` + TTL | 24 hours | Mostly (Redis persistence) |
| 3 | `InMemoryDedupAdapter` | `OrderedDict` LRU | 10,000 entries | **No - lost on restart** |

Selection logic in `_wiring.py:369-418`: Postgres > Redis > In-memory.
In dev/selfhost where Postgres may be recreated, falls back to in-memory.

## Fail-Open Behavior

**Pipeline dedup is explicitly fail-open** (`pipeline.py:85-98`):

```python
try:
    if await self._dedup.is_duplicate(event.dedup_key):
        return PipelineResult(status="deduplicated", ...)
except Exception:
    logger.warning("Dedup check failed -- processing anyway (fail-open)")
```

If the dedup backend throws, the event is processed anyway. The rationale
is that safety guards in `EvaluateWebhookHandler` provide second-layer
protection.

**Cursor loading is fail-open** (`events_api_client.py:146`): If Postgres
cursor store is unavailable, poller starts without ETags and re-fetches
everything.

**Cursor saving failure is swallowed** (`events_api_client.py:124-125`):
If persisting a cursor fails, it only exists in memory.

## The 7 Safety Guards

| # | Guard | What it checks | Storage | Durable? |
|---|-------|---------------|---------|----------|
| 1 | Max attempts | Fire count for (trigger, PR) vs config | Postgres projection | **Yes** |
| 2 | Cooldown | Time since last fire for (trigger, PR) | Postgres projection | **Yes** |
| 3 | Daily limit | Today's fire count for trigger | Postgres projection | **Yes** |
| 4 | Idempotency | delivery_id/dedup_key already processed | Postgres in prod, in-memory in test | **Yes in prod** |
| 5 | Cross-trigger cooldown | Any trigger fired on same PR recently | Postgres projection | **Yes, but DISABLED** (cooldown = 0) |
| 6 | Concurrency | Execution already running for (trigger, PR) | **In-memory only** | **No** - intentional, containers don't survive restart |
| 7 | Dispatch rate limit | Sliding window: 10 dispatches per 60s | **In-memory only** | **No** - intentional safety net |

**Per-(trigger, PR) lock**: `asyncio.Lock` in `_fire_locks` dict (line 77).
In-memory only, never pruned (unbounded growth). Protects in-process race
but not cross-restart.

## Assumptions Inventory

| Location | Assumption | What breaks it |
|----------|-----------|----------------|
| Pipeline dedup (fail-open) | Safety guards catch what dedup misses | Guards 6 and 7 are in-memory, reset on restart |
| Guard 6 (concurrency) | Containers don't survive restart | True, but the check also prevents duplicate launches - lost on restart |
| Guard 7 (rate limit) | In-memory is fine as safety net | On restart, 10/60s limit resets - no protection against burst |
| Cursor loading (fail-open) | Dedup catches re-fetched events | If both cursor and dedup are in-memory (dev mode), full re-processing |
| Unknown event type dedup | Payload hash is sufficient | Different sources produce different payload shapes |
| `_fire_locks` | Never pruned | Unbounded memory growth on busy systems |
| Cross-trigger cooldown | Disabled (= 0) | Multiple triggers fire simultaneously on same PR |

## The Core Problem

The idempotency boundary is **layered but not ironclad**:

1. **Primary** (dedup key): Durable in prod (Postgres), fail-open on error
2. **Secondary** (safety guards): Mix of durable (1-4) and in-memory (5-7)
3. **Tertiary** (asyncio.Lock): In-process only

On a clean restart with Postgres available, guards 1-4 provide reasonable
protection. But:
- WorkflowDispatchProjection has **no idempotency check at all** - it fires
  `run_workflow()` unconditionally on any `TriggerFired` event it receives
- `BackgroundWorkflowDispatcher.run_workflow()` has **no idempotency check**
  - it creates an asyncio.Task unconditionally
- The dedup key proves "this event was seen" but nothing proves "this
  workflow was already launched for this trigger"

**Missing invariant**: There is no durable record that says "execution X
was already dispatched for trigger Y with dedup key Z" that is checked at
the point of workflow launch.
