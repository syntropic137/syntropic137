# ADR-010: Event Subscription Architecture for Projections

**Status:** Accepted
**Date:** 2025-12-03
**Updated:** 2025-12-09
**Deciders:** Engineering Team
**Related:** ADR-007 (Event Store Integration)

## Context

The Agentic Engineering Framework uses event sourcing with CQRS (Command Query Responsibility Segregation). This means:
- **Write side:** Commands create events that are persisted to the Event Store
- **Read side:** Projections build optimized read models from events

During E2E testing, we discovered a systemic issue: workflows were successfully saved to the Event Store but never appeared in the Dashboard API. The root cause was identified as a **missing subscription mechanism** between the Event Store and Projections.

### Current (Broken) Architecture

```
CLI Seed → CreateWorkflowHandler → Event Store (✓ Works)
                ↓
        EventPublisher.publish() → NoOpEventPublisher (Does nothing!)
                ↓
        ProjectionManager (Never called)
                ↓
        Dashboard API (Returns 0 workflows)
```

The `NoOpEventPublisher` was introduced with the comment "SDK handles persistence" - which is true, but **projections are a separate concern** that must be explicitly updated.

### The Problem

In a proper event-sourced system, projections should **subscribe** to the event store and receive events asynchronously. This is the fundamental pub/sub pattern of event sourcing. Our implementation was missing this critical piece.

## Decision

We will implement a **catch-up subscription with live tailing** pattern:

1. **On Dashboard Startup:**
   - Connect to Event Store
   - Load last processed event position from `projection_states` table
   - Start `EventSubscriptionService` as a background task

2. **Catch-up Phase:**
   - Read all events from last position using `Subscribe` RPC (streaming)
   - Dispatch each event to `ProjectionManager`
   - Update position in `projection_states` periodically

3. **Live Subscription Phase:**
   - Keep subscription stream open
   - As new events arrive, dispatch to `ProjectionManager` in real-time
   - Periodically save position (batched for performance)

4. **On Dashboard Shutdown:**
   - Signal subscription to stop
   - Flush pending position updates
   - Disconnect from Event Store

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EVENT SOURCING ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   WRITE SIDE                           READ SIDE                             │
│   ─────────                            ─────────                             │
│                                                                              │
│   ┌──────────────┐                     ┌──────────────────────────────────┐ │
│   │ CLI / API    │                     │       Dashboard Backend          │ │
│   │ Commands     │                     │                                  │ │
│   └──────┬───────┘                     │  ┌────────────────────────────┐ │ │
│          │                             │  │ EventSubscriptionService   │ │ │
│          ▼                             │  │ - Catch-up subscription    │ │ │
│   ┌──────────────┐                     │  │ - Live tailing             │ │ │
│   │ Aggregates   │                     │  │ - Position tracking        │ │ │
│   │ (Domain)     │                     │  └────────────┬───────────────┘ │ │
│   └──────┬───────┘                     │               │                  │ │
│          │                             │               ▼                  │ │
│          │ Events                      │  ┌────────────────────────────┐ │ │
│          ▼                             │  │   ProjectionManager        │ │ │
│   ┌──────────────┐    Subscribe        │  │   - WorkflowList           │ │ │
│   │ Event Store  │◄────────────────────│  │   - WorkflowDetail         │ │ │
│   │ (gRPC)       │────────────────────▶│  │   - SessionList            │ │ │
│   └──────────────┘    Stream Events    │  │   - ArtifactList           │ │ │
│          │                             │  │   - DashboardMetrics       │ │ │
│          │                             │  └────────────┬───────────────┘ │ │
│          ▼                             │               │                  │ │
│   ┌──────────────┐                     │               ▼                  │ │
│   │ PostgreSQL   │                     │  ┌────────────────────────────┐ │ │
│   │ (Events)     │                     │  │   Projection Store         │ │ │
│   └──────────────┘                     │  │   (PostgreSQL)             │ │ │
│                                        │  │   - workflow_summaries     │ │ │
│                                        │  │   - workflow_detail        │ │ │
│                                        │  │   - projection_states      │ │ │
│                                        │  └────────────────────────────┘ │ │
│                                        │                                  │ │
│                                        └──────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### RealTimeProjection for UI Streaming (Added 2025-12-09)

In addition to persisting projections, the architecture supports a **RealTimeProjection** for streaming domain events to UI clients via WebSocket:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    REAL-TIME UI STREAMING                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Event Store → Subscription → ProjectionManager                            │
│                                      │                                       │
│       ┌──────────────────────────────┼──────────────────────────────────┐   │
│       ▼                              ▼                                  ▼   │
│   [Persisting                   [Persisting                    [RealTime   │
│    Projections]                  Projections]                   Projection] │
│   (WorkflowList,                (ArtifactList,                      │       │
│    WorkflowDetail)               SessionList)                       │       │
│       │                              │                              │       │
│       ▼                              ▼                              ▼       │
│   PostgreSQL                    PostgreSQL                   WebSocket     │
│   (Read Models)                 (Read Models)                Clients (UI)  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

The `RealTimeProjection`:
- Is a **non-persisting** projection that maintains WebSocket connections
- Receives events from the same `ProjectionManager` as persisting projections
- Broadcasts events to connected UI clients for that execution
- Connects via `/ws/executions/{execution_id}` endpoint
- Uses the `useExecutionStream` React hook on the frontend

This pattern ensures:
1. **Single event source:** All UI updates come from the Event Store
2. **No parallel paths:** No SSE or separate event systems
3. **Consistent with ES principles:** Projections (including real-time) are consumers of the event stream

## Consequences

### Positive

1. **Proper Event Sourcing:** Follows the established pub/sub pattern for event-sourced systems
2. **Real-time Updates:** Projections update immediately as events are created
3. **Resilient:** Catch-up subscription handles restarts gracefully
4. **Auditable:** Position tracking provides clear visibility into what's been processed
5. **Decoupled:** Write side doesn't need to know about projections
6. **Scalable:** Multiple consumers can subscribe to the same stream

### Negative

1. **Eventually Consistent:** Small delay between event creation and projection update (typically < 100ms)
2. **Complexity:** Adds a background service that must be managed
3. **Failure Handling:** Must handle subscription disconnects and reconnects

### Neutral

1. **Removes `NoOpEventPublisher`:** No longer needed; subscription handles everything
2. **Dashboard Dependency:** Dashboard must be running for projections to update

## Alternatives Considered

### Alternative 1: Synchronous Dispatch (Rejected)

Replace `NoOpEventPublisher` with one that synchronously dispatches to `ProjectionManager`.

**Pros:**
- Simple to implement
- Immediate consistency

**Cons:**
- Couples write side to read side
- Projection failures could break command handling
- Doesn't scale well
- Not a standard event sourcing pattern

### Alternative 2: Message Queue (Deferred)

Use Redis pub/sub or RabbitMQ between Event Store and Projections.

**Pros:**
- Highly scalable
- Multiple consumer support
- Proven pattern at scale

**Cons:**
- Adds infrastructure complexity
- Event Store already supports subscriptions
- Overkill for current scale

**Decision:** Defer until we need multi-node deployment.

## Implementation Notes

### Position Tracking Schema

The `projection_states` table already exists:

```sql
CREATE TABLE IF NOT EXISTS projection_states (
    projection_name VARCHAR(255) PRIMARY KEY,
    last_event_position BIGINT DEFAULT 0,
    last_event_id VARCHAR(255),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

Use `projection_name = 'global_subscription'` for the main subscription position.

### Error Handling Strategy

1. **Projection Handler Fails:** Log error, continue processing, increment error counter
2. **Position Save Fails:** Keep in-memory position, retry on next batch
3. **Subscription Disconnects:** Exponential backoff reconnect (1s, 2s, 4s, 8s, max 30s)
4. **Event Store Unavailable:** Health check reports unhealthy, retry connection

### Testing Strategy

1. **Unit Tests:** Mock event store client, verify dispatch logic
2. **Integration Tests:** Use in-memory event store, verify full flow
3. **E2E Tests:** Full Docker stack, verify CLI → API → UI flow

## References

- [Event Sourcing Pattern](https://martinfowler.com/eaaDev/EventSourcing.html)
- [CQRS](https://martinfowler.com/bliki/CQRS.html)
- [Catch-up Subscriptions](https://www.eventstore.com/blog/catch-up-subscriptions-in-eventstore)
- ADR-007: Event Store Integration
