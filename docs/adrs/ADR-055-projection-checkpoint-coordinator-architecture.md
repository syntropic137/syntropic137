# ADR-055: Projection Checkpoint Coordinator Architecture

## Status

Accepted

## Date

2026-04-04

**Partially Supersedes:** ADR-010 (subscription mechanism section)

## Related

- ADR-010: Event Subscription Architecture (legacy service this partially supersedes)
- ADR-014 (event-sourcing-platform): Projection Checkpoint Architecture (foundational design)
- ADR-008: VSA Projection Architecture

## Context

ADR-010 introduced `EventSubscriptionService` to connect the event store to projections via a catch-up + live-tail subscription. That service used a **single global checkpoint** stored in `projection_states` under the key `global_subscription`. All projections shared one position.

This caused several problems as the number of projections grew:

- **Coupled rebuilds.** Bumping a projection's version (schema change, bug fix) required resetting the global position, forcing every projection to replay the full event stream from scratch — even those with no schema change.
- **Independent recovery was impossible.** A new projection added mid-life had no way to replay only its own history without taking all other projections back to position 0.
- **Silent failures.** The legacy `ProjectionManager.dispatch()` swallowed exceptions; projection failures advanced the global position anyway, silently losing events.
- **Position drift after infrastructure restarts.** If PostgreSQL restarted (clearing `projection_states`) while the event store retained all events, the service resumed from position 0 metadata but skipped re-processing earlier events because the in-memory position was stale.

The `event-sourcing-platform` library solved these problems at the infrastructure layer in ADR-014 by introducing `CheckpointedProjection`, `PostgresCheckpointStore`, and `SubscriptionCoordinator`. ADR-055 documents Syntropic137's adoption of that architecture.

## Decision

Replace `EventSubscriptionService` with `CoordinatorSubscriptionService`, wired via the `create_coordinator_service()` factory.

### Per-projection checkpoints via `PostgresCheckpointStore`

Each `CheckpointedProjection` tracks its own position in a `projection_checkpoints` table (managed by the ESP library). The coordinator subscribes from `min(all checkpoints)` so fast projections are not held back by slow ones, and a new projection can replay independently without disturbing others.

### 12 projections registered in the factory

`create_coordinator_service()` in `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py` is the single registry. All projections are instantiated here:

| Projection | Context |
|---|---|
| `WorkflowListProjection` | orchestration |
| `WorkflowDetailProjection` | orchestration |
| `WorkflowExecutionListProjection` | orchestration |
| `WorkflowExecutionDetailProjection` | orchestration |
| `SessionListProjection` | agent_sessions |
| `ArtifactListProjection` | artifacts |
| `DashboardMetricsProjection` | orchestration |
| `WorkflowDispatchProjection` | github |
| `TriggerQueryProjection` | github |
| `OrganizationProjection` (via adapter) | organization |
| `SystemProjection` (via adapter) | organization |
| `RepoProjection` (via adapter) | organization |

### `AutoDispatchProjection` base class

Most projections extend `AutoDispatchProjection` from the ESP library, which uses `get_subscribed_event_types()` to auto-route events to `handle_<EventType>` methods. This eliminates the fragile two-places-to-update pattern where adding an event type to the subscription list and adding a handler method had to stay in sync manually.

### `_NamespacedProjectionAdapter` for organization context

Organization-context projections (`OrganizationProjection`, `SystemProjection`, `RepoProjection`) use namespace-qualified event type strings (e.g., `organization.OrganizationCreated`). The coordinator strips namespace prefixes when matching subscribed event types, so thin adapter wrappers (`OrganizationListAdapter`, `SystemListAdapter`, `RepoListAdapter`) handle the namespace translation.

### `SessionToolsProjection` excluded

`SessionToolsProjection` is not registered in the coordinator. It is a read-only SQL query against TimescaleDB observability tables, not an event consumer. It has no `handle_event` method and does not implement `CheckpointedProjection`.

### `RealTimeProjectionAdapter` wraps legacy `RealTimeProjection` for SSE

`RealTimeProjection` (non-persisting, SSE broadcast) predates `CheckpointedProjection`. Rather than rewrite it, `RealTimeProjectionAdapter` wraps it as a `CheckpointedProjection` that always returns `ProjectionResult.SUCCESS` without saving a checkpoint. This keeps the SSE path unchanged (documented in ADR-010's RealTimeProjection section) while integrating it into the coordinator lifecycle.

### Degraded-mode startup

Subscription failure does not abort API startup. `start()` returns after launching the coordinator as a background `asyncio.Task`. If the event store is unreachable at startup, the coordinator retries via backoff rather than crashing the API process. The API serves stale read models until the subscription catches up.

### Exponential backoff reconnect

On gRPC disconnection or error, the coordinator resets and retries with delay doubling from 1 s, capped at 60 s:

```
1s → 2s → 4s → 8s → 16s → 32s → 60s (cap)
```

Logic lives in `coordinator_helpers.run_coordinator()`.

### Version-based automatic rebuild

`CheckpointedProjection.get_version()` returns an integer. When the coordinator detects that a projection's stored checkpoint version is lower than its declared version, it clears the projection's data and resets its checkpoint to 0, triggering an independent full replay for that projection only. Other projections are unaffected.

## Consequences

### Positive

- **Independent rebuild.** A single projection can be rebuilt (version bump or manual reset) without touching any other projection's checkpoint.
- **Version-based replay.** Incrementing `get_version()` on a projection is the only change needed to trigger a replay — no manual checkpoint manipulation.
- **Explicit failure handling.** `ProjectionResult.FAILURE` prevents checkpoint advancement; the event will be retried on the next coordinator start.
- **Degraded mode.** The API remains available even when the event store is down; projections catch up automatically on reconnection.
- **Fitness test coverage.** `ci/fitness/event_sourcing/test_projection_wiring.py` asserts the exact projection count, failing with guidance when a new projection is registered but the test is not updated.

### Negative

- **More complex wiring.** `create_coordinator_service()` must be kept in sync with all projections; forgetting to register a new projection silently omits it from the subscription.
- **Checkpoint store dependency.** A running PostgreSQL instance is required before `start()` is called. Tests must inject a `MemoryCheckpointStore` (via the `checkpoint_store` parameter) to avoid the database dependency.
- **Organization adapters.** Organization-context projections use namespace-qualified event types that require thin adapter wrappers (`OrganizationListAdapter`, `SystemListAdapter`, `RepoListAdapter`). New projections in similar contexts may need the same treatment.
- **Two registries coexist.** The coordinator registry (`create_coordinator_service()`) and the legacy `ProjectionManager` with its `EVENT_HANDLERS` map coexist during migration. Delete the legacy `ProjectionManager` and `EVENT_HANDLERS` when migration is complete.

## Legacy Status of ADR-010

ADR-010's **subscription mechanism section** (global `EventSubscriptionService`, `ProjectionManager` dispatch, `projection_states` global position) is now legacy. The service still exists in `packages/syn-adapters/src/syn_adapters/subscriptions/service.py` but is no longer wired at startup.

ADR-010's **RealTimeProjection / SSE section** (updated 2026-03-21) remains current — the `RealTimeProjection` interface and SSE route design are unchanged; only the subscription lifecycle that drives it has been replaced.

## References

- `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py` — service + factory
- `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_helpers.py` — backoff/lifecycle
- `lib/event-sourcing-platform/docs/adrs/ADR-014-projection-checkpoint-architecture.md` — foundational checkpoint design
- `ci/fitness/event_sourcing/test_projection_wiring.py` — fitness test that enforces registry completeness
