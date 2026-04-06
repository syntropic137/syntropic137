# ADR-050: Hybrid Webhook + Polling Event Pipeline

## Status

**Accepted** — 2026-03-29

## Context

Syntropic137's GitHub trigger system was 100% webhook-driven. Workflows fired in response to GitHub webhook deliveries — push events, PR updates, check runs. This works well when the GitHub App has a reachable webhook URL, but introduces a hard requirement that blocks zero-config onboarding:

### The webhook tunnel problem

Self-hosted users behind NAT or firewalls must configure a reverse tunnel (Cloudflare Tunnel, smee.io, ngrok) before GitHub events can arrive. Without it, the platform appears broken — triggers never fire, workflows never start. This is the single largest friction point for new users.

### Why not just poll?

GitHub's [Events API](https://docs.github.com/en/rest/activity/events) provides an alternative path, but has limitations:

- **Rate limit:** 60 conditional requests per hour per installation token
- **Delay:** Events appear with a ~5 minute delay
- **Pagination:** Returns most recent 300 events, newest first
- **No filtering:** Must fetch all events and filter client-side

Neither source alone is sufficient. Webhooks provide real-time delivery but require infrastructure setup. Polling provides zero-config access but with delay and rate constraints.

### The dedup challenge

When both sources are active, the same logical event (e.g., a push to `main`) arrives twice — once via webhook (with a UUID delivery ID) and once via the Events API (with a numeric event ID). These IDs are completely different for the same event. Without deduplication, triggers fire twice.

## Decision

### 1. Unified EventPipeline with dual ingest

Both webhook endpoint and poller feed events through a single `EventPipeline.ingest(NormalizedEvent)` entry point. The `NormalizedEvent` dataclass normalizes payload format differences between the two sources (webhook payloads include `repository`, `sender`, `installation` wrappers; Events API payloads use a flat `repo.name` field).

**Location:** `packages/syn-domain/.../event_pipeline/pipeline.py`

### 2. Content-based dedup keys

Dedup keys are derived from stable identifiers present in both webhook and Events API payloads — not delivery IDs or event IDs, which differ between sources.

Per-event-type extractors (`dedup_keys.py`):

| Event type | Key components | Example key |
|---|---|---|
| `push` | repo + after SHA | `push:owner/repo:abc123` |
| `pull_request` | repo + PR number + action + updated_at | `pr:owner/repo:42:opened:2026-03-29T...` |
| `check_run` | repo + check run ID + action | `check_run:owner/repo:789:completed` |
| `issue_comment` | repo + comment ID + action | `comment:owner/repo:456:created` |
| Unknown types | `unknown:` + SHA-256 hash of sorted payload | `unknown:a1b2c3d4e5f6...` |

The `updated_at` field in PR keys prevents stale dedup: reopening a PR generates a new key even though the PR number is the same.

### 3. Redis SETNX + TTL for dedup storage

- **Primary:** `RedisDedupAdapter` using `SET key 1 NX EX <ttl>` — atomic check-and-mark in one round trip
- **Fallback:** `InMemoryDedupAdapter` with `OrderedDict`-based LRU (10K entries) for tests and offline mode
- **Key prefix:** `syn:dedup:`, **TTL:** 86400s (24 hours, configurable)

Redis is already in the Docker stack for signal queues. SETNX is O(1), atomic, and auto-expires — no cleanup jobs needed.

### 4. Fail-open dedup

If the dedup backend (Redis) is unreachable, the event is **processed anyway**. Rationale: a missed event is worse than a duplicate trigger evaluation. Safety guards in `EvaluateWebhookHandler` (fire counts, cooldown periods) provide second-layer protection against duplicate triggers actually causing harm.

```
Dedup available   → check key → duplicate? skip : process
Dedup unavailable → log warning → process anyway (fail-open)
```

### 5. Polling ON by default (zero-config onboarding)

Polling is enabled out of the box. The opt-out variable is `SYN_POLLING_DISABLED=true` (not an opt-in `SYN_POLLING_ENABLED`). This ensures new users get event ingestion immediately without any webhook configuration.

The poller runs as a named `asyncio.Task` (`github-event-poller`) inside the syn-api process — no new container, no new deployment artifact. It starts during `lifecycle.startup()` and stops during `lifecycle.shutdown()`, degrading gracefully if GitHub is not configured.

Only repos with at least one active trigger are polled (`trigger_store.list_all(status="active")`), preventing wasted API calls.

### 6. Adaptive mode switching (PollerState)

The poller operates in two modes based on webhook health:

| Mode | Interval | When |
|---|---|---|
| `ACTIVE_POLLING` | 60s (configurable) | No webhook received in 30 minutes, or never |
| `SAFETY_NET` | 300s (configurable) | Webhooks arriving normally |

`WebhookHealthTracker` tracks the last webhook delivery timestamp using `time.monotonic()` (immune to clock adjustments). The poller checks `health_tracker.is_stale` at the start of each cycle and transitions mode accordingly.

**Error handling:** Consecutive errors trigger exponential backoff (`base * 2^errors`), capped at 600s. Rate limit errors extract `reset_at` from `GitHubRateLimitError` and wait accordingly. Successful polls reset the error counter.

**GitHub compliance:** The actual sleep interval is `max(computed_interval, response.poll_interval)`, respecting GitHub's `X-Poll-Interval` header (typically 60s).

## Consequences

### Positive

- **Zero-config onboarding** — Polling works immediately; no tunnel setup needed
- **Resilient** — Webhook failures automatically trigger aggressive polling within 30 minutes
- **Efficient dedup** — Content-based keys prevent double-firing regardless of which source delivers first
- **Safe failure modes** — Fail-open dedup + trigger cooldowns prevent both missed events and runaway triggers
- **No infrastructure changes** — Runs inside existing syn-api process, uses existing Redis instance

### Negative

- **API quota consumption** — Each polled repo uses Events API quota (~60 conditional requests/hr in active mode, ~12/hr in safety net mode)
- **Redis dependency for best dedup** — In-memory fallback doesn't survive restarts; a restart during dual-delivery could cause one duplicate
- **Dedup key maintenance** — Each new event type needs a dedicated extractor or falls back to hash-based dedup (which doesn't guarantee cross-source key match for unknown types)
- **5-minute delay** — Events API events appear with a delay; polling alone is not real-time

## Addendum: Checks API Polling (#602) — 2026-04-06

The original ADR describes two event sources (webhooks + Events API). Issue #602 adds a third: **Checks API polling** for `check_run` events.

### Problem

`check_run` events are not available through GitHub's Events API — they are webhook-only. This meant self-healing (CI fails → auto-fix workflow) required a tunnel or public URL, which is the biggest onboarding friction point.

### Solution

When a `pull_request` event arrives (already polled via Events API), register the head SHA. A background poller (`CheckRunPoller`) hits `GET /repos/{o}/{r}/commits/{sha}/check-runs` every 30s. When a check run completes with `conclusion: failure`, synthesize a `check_run.completed` NormalizedEvent and feed it through `EventPipeline.ingest()`. Content-based dedup handles overlap with webhooks automatically.

### Three-source model

| Source | API | Events | Latency |
|--------|-----|--------|---------|
| Events API poller | `GET /repos/{o}/{r}/events` | 17 types (PR, push, etc.) | ~5 min |
| Webhooks | Push-based | All 60+ types | ~1s |
| **Checks API poller** | `GET /repos/{o}/{r}/commits/{sha}/check-runs` | `check_run` only | ~30-90s |

### Key design decisions

- **Observer pattern** on `EventPipeline`: `CheckRunPoller.on_pr_event()` is registered as an observer, called after each non-deduplicated event. Simpler than adding a shared queue or making the pipeline aware of downstream consumers.
- **Trigger gating**: Poller only runs when active `check_run` triggers exist. Zero API calls when self-healing is not configured.
- **Webhook-adaptive intervals**: Reuses `PollerState` from the Events API poller — 30s when webhooks stale, 120s when healthy.
- **PendingSHA lifecycle**: Register on PR event → poll → remove when all checks completed → cleanup stale after 2h TTL.
- **`DeliveryChannel.CHECKS_API`**: New enum value in `event_availability.py`. `check_run` moves from `WEBHOOK` to `CHECKS_API` channel, meaning `requires_webhook("check_run")` returns `False` and `available_via_polling("check_run")` returns `True`.

## Related ADRs

- **ADR-040** — GitHub Trigger Architecture (trigger rules that this pipeline feeds into)
- **ADR-042** — Event Type Naming Standard (compound event naming convention used by the pipeline)
