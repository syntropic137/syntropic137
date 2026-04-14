# Deep Audit: Error Handling, Aggregate Guards, In-Memory State

**Created:** 2026-04-14
**Scope:** Beyond the dispatch pipeline - system-wide reliability gaps

This document captures findings from three parallel audits that extend
the original trigger/dispatch analysis to cover the full system.

---

## 1. Error Handling Patterns

### 1.1 Silent Exception Swallowing

| Severity | File | Line | Pattern |
|----------|------|------|---------|
| **HIGH** | `contexts/agent_sessions/slices/list_sessions/projection.py` | 320 | `except Exception: pass` in `reconcile_running_sessions()` - orphan session reconciliation failures discarded with no log. Sessions may remain stuck in "running" state indefinitely. |
| LOW | `syn_adapters/workspace_backends/docker/docker_container_ops.py` | 40 | `except Exception: pass` in `get_container_network()` - falls back to default network silently. |
| LOW | `syn_adapters/conversations/minio.py` | 116 | Bare `except Exception:` with no logging in conversation storage. |

### 1.2 Background Task Exception Loss

| Severity | File | Line | Pattern |
|----------|------|------|---------|
| **HIGH** | `contexts/github/slices/evaluate_webhook/debouncer.py` | 49-56 | `asyncio.create_task(_fire())` with no done callback. If `callback()` raises, exception escapes the task silently. Trigger firing failures are lost. |
| **HIGH** | `syn-api/services/lifecycle.py` | 129 | Recovery loop task (`_recovery_loop`) with no done callback. If it raises unexpectedly, degraded service recovery stops silently. |
| MEDIUM | `syn_adapters/dedup/postgres_dedup.py` | 104 | Cleanup task with no done callback. Dedup table cleanup failures silently lost. |

### 1.3 Checkpoint Behavior

The coordinator itself is correct - does NOT advance checkpoint on
`ProjectionResult.FAILURE`. However:

| Severity | File | Line | Pattern |
|----------|------|------|---------|
| MEDIUM | `syn_adapters/subscriptions/realtime_adapter.py` | 95 | SSE broadcast failures return `SKIP` not `FAILURE`. Coordinator advances checkpoint on `SKIP`. Events permanently skipped for SSE delivery, never retried. Intentional (SSE is best-effort) but notable. |

---

## 2. Aggregate Invariant Enforcement

Full audit of all 10 aggregates across 5 bounded contexts.

### Well-Guarded (No Issues)

- **AgentSessionAggregate** - all commands check status before emitting
- **ArtifactAggregate** - guards existence, deletion state, prevents double-delete
- **WorkflowTemplateAggregate** - guards existence, prevents double-archive
- **OrganizationAggregate** / **SystemAggregate** - guards existence and deletion
- **RepoAggregate** - guards existence, deregistered state, double-assign
- **RepoClaimAggregate** - guards existence, allows re-claim after release
- **WorkflowExecutionAggregate** - guards on all command handlers
- **InstallationAggregate** - factory pattern, `revoke()` is idempotent

### Issues Found

| Severity | Aggregate | Method | Line | Issue |
|----------|-----------|--------|------|-------|
| **HIGH** | `TriggerRuleAggregate` | `record_fired()` | 221 | **Zero guards.** Emits `TriggerFiredEvent` regardless of trigger status. A PAUSED or DELETED trigger can fire. `can_fire()` exists at line 257 but is never called. The caller (`EvaluateWebhookHandler`) checks status via a read-model index, but there's a window where the index is stale. |
| LOW | `TriggerRuleAggregate` | `record_blocked()` | 239 | No status guard on audit event. Arguably intentional but undocumented. |
| LOW | `WorkspaceAggregate` | `record_isolation_started()` | 440 | No current-status guard. Double-call after crash silently resets status to READY. Low risk because caller is controlled. |
| LOW | `WorkspaceAggregate` | `record_error()` | 481 | No terminal-state guard. Callable on already-DESTROYED workspace. Harmless but not defensive. |

**Fix for TriggerRuleAggregate:** One line at line 222:
```python
if not self.can_fire():
    raise ValueError(f"Cannot fire trigger in status {self._status}")
```

---

## 3. In-Memory State Patterns

### Critical - Production impact on restart or multi-instance

| # | Component | File:Line | State | Restart Impact | Multi-Instance Impact |
|---|-----------|-----------|-------|----------------|----------------------|
| 1 | `InMemoryPendingSHAStore` | `_wiring.py:443-457` | Pending SHAs for check-run polling | **Lost** - check polling stops until next PR event | **Wrong** - each instance has different set |
| 2 | `InMemoryDedupAdapter` (fallback) | `_wiring.py:400-418` | Event dedup keys | **Lost** - duplicates fire again | **Wrong** - each instance deduplicates independently |
| 3 | `_sig_failures` dict | `signature.py:21-38` | Webhook signature rate limit | Lost (minor) | Wrong + **unbounded growth** on many unique IPs |
| 4 | `_fire_locks` dict | `EvaluateWebhookHandler.py:77` | asyncio.Lock per (trigger, PR) | No impact | **No cross-instance coordination** - two instances can both pass concurrency guard |
| 5 | `_running_executions` | `trigger_query_store.py:83-84` | Active execution tracker | Correct by design (containers are ephemeral) | **Wrong** - both instances believe no execution is running and both fire |

### Medium - Known, self-healing, or by design

| # | Component | File:Line | State | Notes |
|---|-----------|-----------|-------|-------|
| 6 | `_dispatch_timestamps` | `safety_guards.py:181` | Rate window counts | Intentionally ephemeral per docstring. Multi-instance multiplies effective limit by N. |
| 7 | `_last_received_at` | `webhook_health_tracker.py:26-28` | Webhook freshness | Resets to stale on restart - pollers switch to ACTIVE mode for ~30min. Self-healing. |
| 8 | `_etags` dict | `events_api_client.py:56-57` | GitHub API ETags | Lost on restart. Benign if cursor store configured (re-fetches from last cursor). |
| 9 | `WorkflowExecutionProcessor` dicts | `WorkflowExecutionProcessor.py:120-128` | Infrastructure handles | Correct by design. Re-provisions from last domain event on restart. |

### Key Finding: No durable PendingSHAStore exists

`InMemoryPendingSHAStore` is the **only** implementation. There is no
Redis or Postgres adapter. The `_wiring.py` assertion at line 457
(`assert isinstance(..., InMemoryPendingSHAStore)`) makes this explicit.
A `PostgresPendingSHAStore` or `RedisPendingSHAStore` needs to be created
for production reliability.

### Key Finding: InMemoryDedupAdapter is a silent production fallback

The fallback chain in `_wiring.py:400-418` is Postgres -> Redis ->
InMemory. If both Postgres and Redis fail to connect at startup (even
transiently), the in-memory adapter is installed for the lifetime of the
process. The code logs a `WARNING` but continues. This means a transient
DB connection failure at startup silently disables dedup durability for
the entire process lifetime.

---

## 4. Multi-Instance Readiness Assessment

The system is designed for single-instance deployment. Scaling to 2+
instances would expose these issues:

| Component | Issue | Fix Needed |
|-----------|-------|------------|
| `_fire_locks` | Per-process asyncio.Lock | Postgres advisory lock or Redis lock |
| `_running_executions` | Per-process dict | Shared store (Postgres query or Redis) |
| Dedup adapter | Per-process fallback | Fail-closed (refuse to start without durable dedup) |
| Pending SHA store | Per-process only | Durable implementation needed |
| Safety Guard 7 | Per-process rate window | Shared counter (Postgres or Redis) |
| Webhook health tracker | Per-process freshness | Shared timestamp (Redis) |
| SSE delivery | Per-process subscriber set | Sticky routing or pub/sub broadcast |

**Recommendation:** Multi-instance deployment is not safe today. The
minimum fix for 2-instance HA is: durable dedup (fail-closed), shared
`_fire_locks`, shared `_running_executions`, durable pending SHA store.

---

## 5. Updated Gap Summary

These findings add to the 10 gaps identified in the original audit
([task-list.md](task-list.md)). New gaps:

| Gap | Severity | Phase |
|-----|----------|-------|
| `reconcile_running_sessions` swallows exceptions silently | HIGH | D1 |
| `debouncer.py` task exception loss | HIGH | D1 |
| `lifecycle.py` recovery loop task exception loss | HIGH | D1 |
| `TriggerRuleAggregate.record_fired()` has zero guards | HIGH | B3 (already tracked) |
| `InMemoryPendingSHAStore` is only implementation | MEDIUM | E4 (already tracked) |
| `InMemoryDedupAdapter` silent production fallback | MEDIUM | New - add to Phase A |
| `_sig_failures` dict unbounded growth | LOW | E5-adjacent |
| No multi-instance support | MEDIUM | Future phase |

The system has **13 total architectural gaps** (10 original + 3 new).
All have fixes designed. The critical path to release is:
1. Merge ESP PR #274
2. Phase A (stop bleeding) + Phase B (structural fix) - eliminates replay storm
3. Phase C (cost safety) - prevents unbounded spend
4. Phase D (error handling) - prevents silent data loss

Phases E and multi-instance readiness can follow the release.
