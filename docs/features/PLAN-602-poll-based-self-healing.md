# Plan: #602 — Poll-Based Self-Healing (Detect CI Failures Without Webhooks)

> **Status: Implemented.** Self-healing now works zero-config via Checks API polling. The problem statement below describes the state *before* this feature was built.

## Context

Self-healing is the flagship use case: CI fails on a PR → Syntropic137 fires a workflow to auto-fix it. But `check_run` events are **webhook-only** — the GitHub Events API never returns them. Without a Cloudflare Tunnel configured, self-healing doesn't work. This is the biggest onboarding friction point.

**Solution:** When a `pull_request` event arrives (already polled via Events API), record its `head.sha`. A new background poller polls the Checks API (`GET /repos/{owner}/{repo}/commits/{sha}/check-runs`) every 30s. When a check run completes with `conclusion: failure`, synthesize a `check_run.completed` NormalizedEvent and feed it through the existing `EventPipeline.ingest()`. Dedup handles overlap with webhooks automatically.

**The 30-90s latency trade-off is negligible** — CI already took minutes to run.

---

## Architecture Overview

```
PullRequestEvent (via Events API poller or webhook)
  └─→ Pipeline observer → CheckRunPoller.on_pr_event()
      └─→ Register (repo, sha, pr_number, branch, installation_id) in PendingSHAStore

CheckRunPoller (asyncio.Task, 30s interval)
  └─→ For each pending SHA:
      └─→ GET /repos/{owner}/{repo}/commits/{sha}/check-runs
      └─→ For each check_run with status=completed + conclusion=failure:
          └─→ Synthesize check_run.completed payload (matches webhook format exactly)
          └─→ NormalizedEvent(source=CHECKS_API)
          └─→ EventPipeline.ingest() → dedup → trigger evaluation → self-heal fires
      └─→ Remove SHA when all checks completed (any conclusion)
      └─→ Cleanup stale SHAs (>2h TTL)
```

---

## Key Design Decisions

1. **Separate service, not bolted onto GitHubEventPoller.** Different API (Checks vs Events), different polling cadence (30s vs 60-300s), different lifecycle (only runs when `check_run` triggers exist). Combining would tangle concerns.

2. **Pipeline observer pattern** for SHA registration. `EventPipeline.ingest()` notifies registered observers after processing. `CheckRunPoller` registers as an observer, only acts on `pull_request` events. Minimal surface area — one optional param on pipeline constructor, no new event bus.

3. **`CHECKS_API` as third EventSource.** Accurate for debugging/observability. Dedup still works because the key is `check_run:{repo}:{check_run_id}:{action}` — identical regardless of source.

4. **In-memory PendingSHAStore.** SHAs are ephemeral (2h TTL). A restart just means a brief gap — the next PR event re-registers the SHA. Redis can be added later if needed.

5. **Webhook-adaptive interval.** When webhooks are healthy (not stale), extend check-run polling to 120s. When stale, poll every 30s. Dedup handles any overlap.

6. **Synthesized payload matches webhook format exactly.** The `SELF_HEALING_PRESET` conditions (`check_run.conclusion == "failure"`, `check_run.pull_requests` not empty) and input mappings work unchanged.

---

## Step 1: Domain — EventSource + PendingSHA Port

### 1a. Add `CHECKS_API` to EventSource enum

**File:** `packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/normalized_event.py`

```python
class EventSource(StrEnum):
    WEBHOOK = "webhook"
    EVENTS_API = "events_api"
    CHECKS_API = "checks_api"  # NEW: synthesized from Checks API polling
```

### 1b. Create PendingSHA port

**New file:** `packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pending_sha_port.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

@dataclass(frozen=True, slots=True)
class PendingSHA:
    """A commit SHA awaiting check-run completion."""
    repository: str           # "owner/repo"
    sha: str
    pr_number: int
    branch: str               # head ref
    installation_id: str
    registered_at: datetime

class PendingSHAStore(Protocol):
    """Port: tracks SHAs whose check runs need polling."""
    async def register(self, pending: PendingSHA) -> None: ...
    async def list_pending(self) -> list[PendingSHA]: ...
    async def remove(self, repository: str, sha: str) -> None: ...
    async def cleanup_stale(self, max_age: timedelta) -> int: ...
```

---

## Step 2: Domain — Check-Run Synthesizer (Pure Function)

**New file:** `packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/check_run_synthesizer.py`

Pure function, no I/O. Takes a Checks API response dict + `PendingSHA` context → `NormalizedEvent | None`. Returns `None` if check run is not `completed` or not `failure`/`timed_out`.

Synthesized payload structure (must match webhook `check_run.completed` format):
```python
{
    "action": "completed",
    "check_run": {
        "id": raw["id"],
        "name": raw["name"],
        "status": "completed",
        "conclusion": raw["conclusion"],
        "html_url": raw["html_url"],
        "output": {
            "title": raw.get("output", {}).get("title", ""),
            "summary": raw.get("output", {}).get("summary", ""),
        },
        "pull_requests": [{
            "number": pending.pr_number,
            "head": {"ref": pending.branch, "sha": pending.sha},
        }],
    },
    "repository": {"full_name": pending.repository},
}
```

This satisfies all `SELF_HEALING_PRESET` conditions and input mappings:
- `check_run.conclusion` → "failure" ✓
- `check_run.pull_requests` → not_empty ✓
- `check_run.pull_requests[0].number` → pr_number ✓
- `check_run.pull_requests[0].head.ref` → branch ✓
- `check_run.name`, `.output.title`, `.output.summary`, `.html_url` → all present ✓

Uses existing `compute_dedup_key("check_run", "completed", payload)` → `check_run:{repo}:{id}:completed`

---

## Step 3: Pipeline Observer Hook

**Modify:** `packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py`

Add optional `observers` parameter to `EventPipeline.__init__` and `add_observer()` method:

```python
from collections.abc import Callable, Coroutine

class EventPipeline:
    def __init__(
        self,
        dedup: DedupPort,
        evaluator: TriggerEvaluator,
        observers: list[Callable[[NormalizedEvent], Coroutine[object, object, None]]] | None = None,
    ) -> None:
        self._dedup = dedup
        self._evaluator = evaluator
        self._observers = list(observers) if observers else []

    def add_observer(
        self,
        callback: Callable[[NormalizedEvent], Coroutine[object, object, None]],
    ) -> None:
        self._observers.append(callback)
```

After successful processing (before `return PipelineResult(status="processed", ...)`), notify observers:

```python
    # Notify observers (fire-and-forget)
    for observer in self._observers:
        try:
            await observer(event)
        except Exception:
            logger.warning("Observer failed for %s", event.dedup_key, exc_info=True)
```

Only notify on non-deduplicated events (placed before the final return).

---

## Step 4: Adapter — GitHubChecksAPIClient

**New file:** `packages/syn-adapters/src/syn_adapters/github/checks_api_client.py`

Thin client wrapping `GET /repos/{owner}/{repo}/commits/{ref}/check-runs`. Follows `GitHubEventsAPIClient` pattern.

```python
@dataclass(frozen=True, slots=True)
class CheckRunsResponse:
    check_runs: list[dict[str, Any]]
    total_count: int

class GitHubChecksAPIClient:
    def __init__(self, github_client: GitHubAppClient) -> None:
        self._client = github_client

    async def get_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, installation_id: str,
    ) -> CheckRunsResponse:
        """Fetch check runs for a commit SHA.
        
        Endpoint: GET /repos/{owner}/{repo}/commits/{ref}/check-runs
        """
```

---

## Step 5: Adapter — InMemoryPendingSHAStore

**New file:** `packages/syn-adapters/src/syn_adapters/github/pending_sha_store.py`

```python
class InMemoryPendingSHAStore:
    """In-memory PendingSHAStore. Ephemeral — SHAs are lost on restart."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingSHA] = {}  # (repo, sha) → PendingSHA

    async def register(self, pending: PendingSHA) -> None:
        key = (pending.repository, pending.sha)
        if key not in self._pending:
            self._pending[key] = pending

    async def list_pending(self) -> list[PendingSHA]:
        return list(self._pending.values())

    async def remove(self, repository: str, sha: str) -> None:
        self._pending.pop((repository, sha), None)

    async def cleanup_stale(self, max_age: timedelta) -> int:
        cutoff = datetime.now(UTC) - max_age
        stale = [k for k, v in self._pending.items() if v.registered_at < cutoff]
        for k in stale:
            del self._pending[k]
        return len(stale)
```

---

## Step 6: Settings

**Modify:** `packages/syn-shared/src/syn_shared/settings/polling.py`

Add to `PollingSettings`:

```python
# Check-run polling (poll-based self-healing, #602)
check_run_poll_interval_seconds: float = Field(
    default=30.0, ge=10.0,
    description="Check-run polling interval when webhooks are stale (seconds).",
)
check_run_safety_interval_seconds: float = Field(
    default=120.0, ge=30.0,
    description="Check-run polling interval when webhooks are healthy (seconds).",
)
check_run_sha_ttl_seconds: int = Field(
    default=7200,
    description="Max age for pending SHAs before cleanup (seconds). Default 2h.",
)
```

---

## Step 7: Service — CheckRunPoller

**New file:** `apps/syn-api/src/syn_api/services/check_run_poller.py`

Follows `GitHubEventPoller` lifecycle pattern exactly: `start()/stop()/is_running`, `asyncio.create_task()`, injectable `sleep` for testing.

```python
class CheckRunPoller:
    def __init__(
        self,
        checks_client: GitHubChecksAPIClient,
        pipeline: EventPipeline,
        sha_store: PendingSHAStore,
        health_tracker: WebhookHealthTracker,
        trigger_store: TriggerQueryStore,
        settings: PollingSettings,
        sleep: Callable[[float], Coroutine[object, object, None]] | None = None,
    ) -> None: ...

    async def start(self) -> None:
        """Start the polling background task."""
        self._task = asyncio.create_task(self._poll_loop(), name="check-run-poller")

    async def stop(self) -> None:
        """Cancel and await the polling task."""

    async def on_pr_event(self, event: NormalizedEvent) -> None:
        """Pipeline observer callback. Registers pending SHA for PR events."""
        if event.event_type != "pull_request":
            return
        if event.action not in ("opened", "synchronize", "reopened"):
            return
        # Extract head.sha, pr_number, branch from payload
        # Register in sha_store

    async def _poll_loop(self) -> None:
        """Main loop: poll check runs for pending SHAs."""
        while True:
            # 1. Check if any check_run triggers exist (skip entirely if not)
            # 2. Determine interval (30s if webhooks stale, 120s if healthy)
            # 3. Iterate pending SHAs
            # 4. For each: GET check runs, synthesize events, ingest
            # 5. Remove completed SHAs
            # 6. Cleanup stale SHAs
            # 7. Sleep
```

**Key behaviors:**
- **Only runs when check_run triggers exist.** Queries `trigger_store` for active triggers with `event` containing `"check_run"`. If none, sleeps and rechecks periodically.
- **Webhook-adaptive intervals.** 30s base when webhooks stale, 120s when healthy.
- **Per-SHA completion tracking.** A SHA is "done" when ALL check runs have `status: completed` (regardless of conclusion). Failed ones are synthesized as events before removal.
- **Rate limit awareness.** Respects `X-RateLimit-Remaining`. Backs off when < 100 remaining.

---

## Step 8: Wiring

**Modify:** `apps/syn-api/src/syn_api/_wiring.py`

Add singletons and factories:
```python
_pending_sha_store_singleton: object | None = None
_checks_api_client_singleton: object | None = None

def get_pending_sha_store() -> PendingSHAStore: ...
def get_checks_api_client() -> GitHubChecksAPIClient: ...
```

The observer is registered in lifecycle init (Step 9) to avoid chicken-and-egg with pipeline singleton.

---

## Step 9: Lifecycle

**Modify:** `apps/syn-api/src/syn_api/services/lifecycle.py`

Add `check_run_poller: CheckRunPoller | None = None` to `LifecycleState`.
Add `CHECK_RUN_POLLER` to `DegradedReason` enum.

Add `_init_check_run_poller(state)` called after `_init_event_poller`:

```python
async def _init_check_run_poller(state: LifecycleState) -> None:
    """Start the check-run poller for poll-based self-healing (#602)."""
    if not settings.github.is_configured or not settings.polling.enabled:
        return
    try:
        poller = CheckRunPoller(
            checks_client=get_checks_api_client(),
            pipeline=get_event_pipeline(),
            sha_store=get_pending_sha_store(),
            health_tracker=get_webhook_health_tracker(),
            trigger_store=get_trigger_store(),
            settings=settings.polling,
        )
        get_event_pipeline().add_observer(poller.on_pr_event)
        await poller.start()
        state.check_run_poller = poller
    except Exception:
        logger.exception("Failed to start check-run poller (degraded mode)")
        state.degraded_reasons.append(DegradedReason.CHECK_RUN_POLLER)
```

Add shutdown:
```python
if _state.check_run_poller is not None:
    with contextlib.suppress(Exception):
        await _state.check_run_poller.stop()
    _state.check_run_poller = None
```

---

## File Summary

| File | Action | Layer |
|------|--------|-------|
| `.../event_pipeline/normalized_event.py` | Modify — add `CHECKS_API` to `EventSource` | Domain |
| `.../event_pipeline/pending_sha_port.py` | **New** — `PendingSHA` dataclass + `PendingSHAStore` protocol | Domain (port) |
| `.../event_pipeline/check_run_synthesizer.py` | **New** — pure function, payload synthesis + `NormalizedEvent` creation | Domain |
| `.../event_pipeline/pipeline.py` | Modify — add `observers` list + `add_observer()` method | Domain |
| `syn-adapters/.../github/checks_api_client.py` | **New** — `GitHubChecksAPIClient` wrapping Checks API | Adapter |
| `syn-adapters/.../github/pending_sha_store.py` | **New** — `InMemoryPendingSHAStore` | Adapter |
| `syn-shared/.../settings/polling.py` | Modify — add 3 check-run settings fields | Shared |
| `syn-api/.../services/check_run_poller.py` | **New** — `CheckRunPoller` background task | Service |
| `syn-api/.../services/lifecycle.py` | Modify — add init/shutdown for check-run poller | Service |
| `syn-api/.../_wiring.py` | Modify — add factory functions | Wiring |

**4 new files, 5 modifications.**

---

## Implementation Order

1. **Domain types** (Steps 1-2): `EventSource.CHECKS_API`, `PendingSHA`/`PendingSHAStore` port, `check_run_synthesizer`
2. **Pipeline observer** (Step 3): Add `observers` + `add_observer()` to `EventPipeline`
3. **Adapters** (Steps 4-5): `GitHubChecksAPIClient`, `InMemoryPendingSHAStore`
4. **Settings** (Step 6): Add check-run polling settings
5. **Service** (Step 7): `CheckRunPoller` with full lifecycle
6. **Wiring + Lifecycle** (Steps 8-9): Wire everything together

---

## Verification

### Unit tests
- `check_run_synthesizer`: Verify synthesized payload matches webhook format. Run `evaluate_conditions` and `extract_inputs` from `condition_evaluator.py` against it using `SELF_HEALING_PRESET` conditions/mappings.
- `InMemoryPendingSHAStore`: register, list, remove, cleanup_stale
- `CheckRunPoller.on_pr_event`: Only registers for `opened`/`synchronize`/`reopened`, ignores others
- `CheckRunPoller._poll_loop`: Mock checks client → verify events synthesized and ingested

### Integration test
- Fire a `pull_request.synchronize` event → verify SHA registered → mock Checks API returning failure → verify `check_run.completed` NormalizedEvent ingested → verify self-heal trigger fires

### E2E (selfhost)
- Enable self-healing trigger on sandbox repo (no tunnel)
- Push a commit that fails CI
- Wait ~30-90s for check-run poller to detect failure
- Verify self-healing workflow fires
- `syn triggers history` shows the fire

### Dedup verification
- Send webhook `check_run.completed` AND let poller synthesize same event → verify only one trigger fire (dedup key matches)

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **Checks API rate limiting** (shares 5000/hr budget) | Respect `X-RateLimit-Remaining`, back off at <100 remaining, suppress when webhooks healthy |
| **Synthesized payload drift** (preset conditions change) | Unit test that runs `evaluate_conditions` + `extract_inputs` against synthesized payload using actual preset |
| **SHA accumulation** (abandoned PRs) | 2h TTL with periodic cleanup; remove immediately when all checks complete |
| **Restart gap** (in-memory store lost) | Next PR event re-registers SHA; brief gap is acceptable for v1 |
