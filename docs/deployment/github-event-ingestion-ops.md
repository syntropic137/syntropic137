# GitHub Event Ingestion — Operations Guide

Operational guidance for the hybrid webhook + polling event pipeline (ADR-050).

## Prerequisites

- **Redis** — Used for event dedup via `SETNX` + TTL. The same Redis instance
  used for signal queues (`REDIS_URL`) is shared by the dedup adapter.
- **GitHub App** — Optional for polling. If the App is configured with
  `SYN_GITHUB_APP_ID` and a valid private key, the poller uses installation
  tokens to access the Events API. Without GitHub App configuration, the poller
  is automatically disabled.

## Redis Requirements

### Dedup Keys

| Property | Value |
|----------|-------|
| Key pattern | `syn:dedup:<content-based-key>` |
| Value | `"1"` (string) |
| Default TTL | 86400 seconds (24 hours) |
| Key size | ~50–80 bytes |

**Estimated memory usage:** ~1 key per GitHub event across all monitored repos.
At 100 events/day across 10 repos, that's ~1000 keys with 24-hour TTL —
negligible memory impact (< 100 KB).

### Availability

Dedup is **fail-open**: if Redis is unreachable, events are processed anyway.
Trigger safety guards (fire counts, cooldown periods) in the evaluation handler
provide second-layer protection against duplicate workflow triggers.

For production, ensure Redis is monitored. Dedup without Redis works but may
cause occasional duplicate trigger evaluations during the window where both
webhook and poller deliver the same event.

## Rate Limiting

The GitHub Events API has a 60-request-per-hour conditional request limit per
installation token.

- The poller only polls repos with active triggers (no wasted calls)
- `304 Not Modified` responses still count against the limit
- ETag caching (`If-None-Match`) minimizes data transfer on unchanged repos
- If rate-limited, the poller extracts `reset_at` from the `GitHubRateLimitError`
  and backs off accordingly
- Other errors trigger exponential backoff (`base * 2^consecutive_errors`),
  capped at 600 seconds

### Quota Planning

| Mode | Polls/hour/repo | 5 repos | 20 repos |
|------|-----------------|---------|----------|
| Active Polling (60s) | ~60 | ~300 | ~1200 |
| Safety Net (300s) | ~12 | ~60 | ~240 |

With many repositories, consider:
- Increasing `SYN_POLLING_POLL_INTERVAL_SECONDS` to reduce active-mode calls
- Ensuring webhook delivery is reliable to keep the poller in Safety Net mode
- Disabling polling entirely (`SYN_POLLING_DISABLED=true`) if webhooks are stable

## Monitoring

### Log Sources

| Logger | Level | What |
|--------|-------|------|
| `syn_api.services.github_event_poller` | INFO | Poller start/stop, mode transitions |
| `syn_api.services.github_event_poller` | DEBUG | Per-cycle repo count and current mode |
| `syn_api.services.github_event_poller` | WARNING | Rate limit backoff, polling errors |
| `syn_api.services.github_event_poller` | EXCEPTION | Individual event ingestion failures |
| `syn_domain...event_pipeline.pipeline` | DEBUG | Deduplicated events (key + source) |
| `syn_domain...event_pipeline.pipeline` | WARNING | Dedup backend failures (fail-open) |
| `syn_domain...event_pipeline.poller_state` | INFO | Mode transitions (ACTIVE ↔ SAFETY_NET) |

### Health Indicators

| Indicator | Access | Meaning |
|-----------|--------|---------|
| `WebhookHealthTracker.is_stale` | Internal | `True` if no webhook in 30 minutes |
| `WebhookHealthTracker.seconds_since_last` | Internal | Seconds since last webhook (or `None`) |
| `GitHubEventPoller.is_running` | Internal | Background task health |
| Lifecycle degraded reasons | `/health` endpoint | `"event_poller"` appears if poller failed to start |

## Tuning

| Variable | Default | When to Change |
|----------|---------|----------------|
| `SYN_POLLING_POLL_INTERVAL_SECONDS` | `60` | Increase if hitting rate limits with many repos |
| `SYN_POLLING_SAFETY_NET_INTERVAL_SECONDS` | `300` | Decrease for tighter catch-up coverage |
| `SYN_POLLING_WEBHOOK_STALE_THRESHOLD_SECONDS` | `1800` | Decrease for faster failover to active polling |
| `SYN_POLLING_DEDUP_TTL_SECONDS` | `86400` | Increase if events could arrive >24h apart (unusual) |
| `SYN_POLLING_DISABLED` | `false` | Set `true` if webhooks are 100% reliable |

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| Duplicate trigger fires | Redis down + fail-open dedup | Restore Redis; trigger cooldowns limit damage in the interim |
| No events processed at all | Polling disabled AND webhook URL unreachable | Set `SYN_POLLING_DISABLED=false` or fix webhook URL/tunnel |
| High API quota usage | Many repos with active triggers in Active Polling mode | Increase poll interval, or fix webhook delivery to enter Safety Net |
| Poller stuck in Active Polling | Webhooks not reaching the health tracker | Verify webhook route calls `health_tracker.record_received()`; check GitHub App webhook URL |
| `event_poller` in degraded reasons | Poller failed to start (GitHub not configured, import error) | Check logs for the specific startup exception |
| Events arriving with ~5min delay | Normal Events API behavior | This is expected; use webhooks for real-time delivery |
