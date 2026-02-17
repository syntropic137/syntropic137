# ADR-041: Offline Development Mode and Webhook Recording

## Status

Accepted

## Date

2026-02-16

## Context

Testing the self-healing trigger pipeline requires: GitHub CI failure → webhook →
trigger evaluation → workflow dispatch. Today this requires the full Docker stack
running, a smee.io tunnel, a real GitHub repo with failing CI, and real API calls.
This is slow, expensive, and fragile.

The codebase already has **agent session recording/replay** (SessionRecorder /
SessionPlayer in agentic-primitives, RecordingEventStreamAdapter in aef-adapters;
see ADR-033). What's missing is **webhook recording** and an **offline dev mode**
that lets the full stack run without Docker or external services.

### Problems

1. **Slow iteration**: Round-tripping through real CI failures takes minutes.
2. **Cost**: Every integration test that touches the agent pipeline burns API credits.
3. **Fragility**: Tests depend on smee.io uptime, GitHub webhook delivery, Docker health.
4. **Accessibility**: New contributors must configure Docker, smee, API keys before
   seeing the dashboard render any data.

## Decision

### 1. Offline Development Mode (`APP_ENVIRONMENT=offline`)

Add an `OFFLINE` environment to the existing `AppEnvironment` enum alongside
`DEVELOPMENT`, `STAGING`, `PRODUCTION`, and `TEST`. When active:

- **In-memory stores** are used for the event store, repositories, and projections
  (same infrastructure as `TEST` mode).
- **Startup seeds data** — workflow templates and trigger presets are created
  automatically so the dashboard renders meaningful content.
- **No Docker required** — no PostgreSQL, EventStoreDB, MinIO, or Redis.
- **No external services** — no smee.io, no GitHub App, no Anthropic API key.

A new `uses_in_memory_stores` property on `Settings` returns `True` for both
`TEST` and `OFFLINE`, replacing scattered `is_test` guards.

### 2. Webhook Recording / Replay

An ASGI middleware (`WebhookRecorderMiddleware`) captures incoming GitHub webhooks
to JSONL files when `AEF_RECORD_WEBHOOKS=true`. Each file follows the same JSONL
convention as SessionRecorder from agentic-primitives:

- **Metadata header** on line 1 (timestamp, event type, source).
- **Event lines** with `_offset_ms` for timing replay.
- **Sanitized headers** — only GitHub-specific headers are recorded; no
  Authorization or cookie leaks.

A companion `scripts/replay_webhooks.py` script replays recorded JSONL against a
running dashboard with speed control and signature stripping.

### 3. Offline Integration Tests

Pytest tests that run fully offline — no Docker, no network:

- Set `APP_ENVIRONMENT=test` (already uses in-memory stores).
- Seed triggers via `aef_api.v1.triggers.enable_preset()`.
- Inject webhook payloads directly via `aef_api.v1.github.verify_and_process_webhook()`.
- Assert triggers fired, correct workflow inputs extracted.
- Replay agent sessions via existing `RecordingEventStreamAdapter`.
- Assert projections populated (session list, costs, tool timeline).

### 4. Scenario Fixtures

Bundled fixtures in `fixtures/webhooks/` and `fixtures/scenarios/` provide
ready-to-use test data:

- `check_run_failure.jsonl` — self-healing trigger scenario
- `issue_comment_command.jsonl` — review-fix trigger scenario
- `installation_created.jsonl` — app installation event

## Consequences

### Positive

- **Velocity**: Iterate on the trigger pipeline in seconds, not minutes.
- **Cost**: Zero API credits for integration testing.
- **Robustness**: Deterministic tests catch regressions that manual testing misses.
- **Accessibility**: `just dev-offline` gives new contributors a working dashboard
  with zero external dependencies.
- **Composability**: Webhook recordings compose with session recordings (ADR-033)
  for full-loop scenario testing.

### Negative

- In-memory stores don't exercise PostgreSQL-specific behavior (query plans,
  constraints, migrations). Real database tests remain necessary for that layer.
- Offline mode can drift from production behavior if new infrastructure
  dependencies are added without updating the offline path.

### Risks

- **Staleness**: Recorded fixtures may become outdated as GitHub's webhook schema
  evolves. Mitigated by dating recordings and including schema version.
- **False confidence**: Passing offline tests don't guarantee production correctness.
  Offline tests complement, not replace, real integration tests.

## References

- ADR-007: Event Store Integration
- ADR-010: Event Subscription Architecture
- ADR-033: Recording-Based Integration Testing
- ADR-034: Test Infrastructure Architecture
