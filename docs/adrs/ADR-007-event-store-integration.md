# ADR-007: Event Store Integration Architecture

```yaml
---
status: accepted
created: 2025-12-02
updated: 2025-12-02
deciders: System Architect
consulted: Development Team
informed: All Stakeholders
---
```

## Context

The Syntropic137 uses event sourcing for domain aggregates (Workflows, Sessions, Artifacts). We need to decide how to persist events and integrate with the `event-sourcing-platform` library.

### Options Considered

1. **Direct PostgreSQL Queries**
   - Write custom SQL to insert/read events from PostgreSQL
   - Simpler initial setup, only requires PostgreSQL
   - Duplicates functionality already in the event-sourcing-platform

2. **Event Store Server via gRPC** (Selected)
   - Use the Rust-based Event Store Server from `event-sourcing-platform`
   - Connect via gRPC using the Python SDK (`event_sourcing.client.grpc_client`)
   - Leverages existing, battle-tested infrastructure

3. **In-Memory Only**
   - Use in-memory storage for everything
   - Fast but no persistence
   - Only suitable for unit tests

## Decision

We will use the **Event Store Server via gRPC** for all non-test environments.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Syn137 Application                               │
├─────────────────────────────────────────────────────────────────────┤
│  Domain Layer (syn-domain)                                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │ WorkflowAggregate│  │ SessionAggregate │  │ ArtifactAggregate│     │
│  │ @aggregate       │  │ @aggregate       │  │ @aggregate       │     │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘     │
│           │                    │                    │               │
│           └────────────────────┼────────────────────┘               │
│                                │                                     │
├────────────────────────────────┼─────────────────────────────────────┤
│  Adapter Layer (syn-adapters)  │                                     │
│  ┌─────────────────────────────┴─────────────────────────────┐      │
│  │              EventStoreRepository (SDK)                    │      │
│  │  - Uses event_sourcing.core.repository                    │      │
│  │  - Handles aggregate load/save                            │      │
│  └─────────────────────────────┬─────────────────────────────┘      │
│                                │                                     │
│  ┌─────────────────────────────┴─────────────────────────────┐      │
│  │              EventStoreClient (SDK)                        │      │
│  │  TEST:  MemoryEventStoreClient (in-memory)                │      │
│  │  DEV:   GrpcEventStoreClient → Event Store Server         │      │
│  │  PROD:  GrpcEventStoreClient → Event Store Server         │      │
│  └─────────────────────────────┬─────────────────────────────┘      │
└────────────────────────────────┼─────────────────────────────────────┘
                                 │ gRPC (port 50051)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Event Store Server (Rust)                         │
│  - High-performance gRPC service                                     │
│  - Optimistic concurrency control                                    │
│  - Stream-based event storage                                        │
│  - Multi-tenant support                                              │
├─────────────────────────────────────────────────────────────────────┤
│  Backend: PostgreSQL                                                 │
│  - event_store.events table                                          │
│  - Indexed by aggregate_id, event_type, created_at                  │
│  - Supports global nonce for projections                            │
└─────────────────────────────────────────────────────────────────────┘
```

### Environment-Based Client Selection

| Environment | APP_ENVIRONMENT | Event Store Client | Persistence |
|-------------|-----------------|-------------------|-------------|
| Unit Tests | `test` | `MemoryEventStoreClient` | None (in-memory) |
| Local Dev | `development` | `GrpcEventStoreClient` | PostgreSQL via Event Store Server |
| Production | `production` | `GrpcEventStoreClient` | PostgreSQL via Event Store Server |

### Configuration

```bash
# Event Store Server connection
EVENTSTORE_HOST=localhost
EVENTSTORE_PORT=50051
EVENTSTORE_TENANT_ID=syn137

# For local development (Docker)
# Event Store Server connects to PostgreSQL internally
DATABASE_URL=postgres://syn137:syn137_dev_password@postgres:5432/syn137
```

### Docker Compose Services

```yaml
services:
  postgres:
    # PostgreSQL database
    
  event-store:
    # Rust Event Store Server
    # - Connects to PostgreSQL
    # - Exposes gRPC on port 50051
    # - BACKEND=postgres
```

## Rationale

### Why Event Store Server over Direct SQL?

1. **DRY Principle**: The event-sourcing-platform already implements:
   - Optimistic concurrency control
   - Stream naming conventions
   - Event serialization/deserialization
   - Global nonce for projections

2. **Performance**: The Rust gRPC server is optimized for:
   - High-throughput event appends
   - Efficient stream reads
   - Connection pooling

3. **Consistency**: Using the official SDK ensures:
   - Correct stream naming (`AggregateType-AggregateId`)
   - Proper version handling
   - Compatible event format

4. **Future-Proofing**: The Event Store Server supports:
   - Subscriptions for real-time projections
   - Multi-tenant isolation
   - Schema evolution

### Why In-Memory for Tests?

Per ADR-008 (Test-Driven Development):
- Unit tests should be fast (<1ms per test)
- Mocks/in-memory stores prevent test pollution
- No external dependencies for unit tests

The `MemoryEventStoreClient` from the SDK provides the same interface, ensuring tests are realistic while remaining fast.

## Consequences

### Positive

✅ **Reuse**: Leverages existing event-sourcing-platform infrastructure

✅ **Performance**: Rust gRPC server is highly optimized

✅ **Consistency**: Single source of truth for event storage

✅ **Testability**: Easy to swap in-memory client for tests

✅ **Observability**: Event Store Server provides metrics and logging

### Negative

⚠️ **Additional Service**: Requires running the Event Store Server

⚠️ **Build Complexity**: Event Store Server needs to be built from Rust source

⚠️ **Network Hop**: gRPC adds latency vs direct SQL (mitigated by connection pooling)

### Mitigations

1. **Docker Compose**: Automates Event Store Server setup for local dev
2. **Health Checks**: Ensure Event Store Server is ready before app starts
3. **Graceful Degradation**: Clear error messages if Event Store is unavailable

## Implementation

### Storage Module Structure

```
packages/syn-adapters/src/syn_adapters/storage/
├── __init__.py           # Factory functions with environment detection
├── in_memory.py          # In-memory implementations (TEST ONLY)
├── event_store_client.py # Event Store client factory
└── repositories.py       # Repository implementations using SDK
```

### Key Code Patterns

```python
# Factory function selects client based on environment
def get_event_store_client() -> EventStoreClient:
    settings = get_settings()
    if settings.is_test:
        return EventStoreClientFactory.create_memory_client()
    return EventStoreClientFactory.create_grpc_client(
        host=settings.eventstore_host,
        port=settings.eventstore_port,
        tenant_id=settings.eventstore_tenant_id,
    )

# Repositories use the SDK's EventStoreRepository
def get_workflow_repository() -> EventStoreRepository[WorkflowAggregate]:
    client = get_event_store_client()
    factory = RepositoryFactory(client)
    return factory.create_repository(WorkflowAggregate, "Workflow")
```

## Related Decisions

- **ADR-003**: Event Sourcing Decorators (defines aggregate patterns)
- **ADR-008**: Test-Driven Development (mocks for unit tests only)
- **ADR-005**: Development Environments (Docker-based local dev)

## References

- [event-sourcing-platform/event-store](../lib/event-sourcing-platform/event-store/README.md)
- [event-sourcing Python SDK](../lib/event-sourcing-platform/event-sourcing/python/README.md)
- [Event Store Server gRPC API](../lib/event-sourcing-platform/event-store/eventstore-proto/proto/eventstore.proto)

---

**Status**: Accepted  
**Last Updated**: 2025-12-02

