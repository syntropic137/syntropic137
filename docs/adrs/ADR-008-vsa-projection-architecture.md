# ADR-008: VSA Projection Architecture for CQRS Read Side

## Status
**Accepted** - December 2025

## Context

The Syn137 application uses Event Sourcing for persistence (ADR-007). While the write side (commands) was well-structured, the initial read side implementation had issues:

1. **Monolithic Read Models**: A single `read_models.py` file contained all read model logic, violating Vertical Slice Architecture (VSA) principles
2. **Tight Coupling**: Read models were tightly coupled to infrastructure (PostgreSQL)
3. **Poor Testability**: Difficult to test individual features in isolation
4. **Scalability Issues**: Single file made parallel development difficult

The VSA principle states: "tight coupling within a slice, loose coupling between slices." This enables parallel development and independent testing of features.

## Decision

Implement CQRS read-side using **VSA-compliant Query Slices** with the following structure:

### 1. Query Slice Structure

Each query slice is a self-contained vertical feature:

```
contexts/{context}/slices/{slice_name}/
├── __init__.py           # Exports
├── projection.py         # Handles events, maintains read model
├── handler.py            # Executes queries
├── slice.yaml            # Metadata (subscriptions, returns)
└── test_{slice_name}.py  # Unit tests
```

### 2. Separation of Concerns

**Domain Layer** (`syn-domain`):
- Query DTOs in `domain/queries/` - define query parameters
- Read Model DTOs in `domain/read_models/` - define response shapes
- Projections in `slices/` - handle events, build read models
- Handlers in `slices/` - execute queries

**Adapter Layer** (`syn-adapters`):
- `ProjectionStoreProtocol` - abstract storage interface
- `PostgresProjectionStore` - production implementation
- `InMemoryProjectionStore` - test implementation
- `ProjectionManager` - event dispatch and coordination

### 3. ProjectionStoreProtocol

Abstracts projection storage to keep domain pure:

```python
class ProjectionStoreProtocol(Protocol):
    async def save(self, projection: str, key: str, data: dict) -> None: ...
    async def get(self, projection: str, key: str) -> dict | None: ...
    async def get_all(self, projection: str) -> list[dict]: ...
    async def query(self, projection: str, filters: dict | None = None, ...) -> list[dict]: ...
    async def get_position(self, projection: str) -> int | None: ...
    async def set_position(self, projection: str, position: int) -> None: ...
```

### 4. Event-to-Projection Mapping

The `ProjectionManager` routes events to appropriate projections:

```python
EVENT_HANDLERS = {
    "WorkflowCreated": [
        ("workflow_list", "on_workflow_created"),
        ("workflow_detail", "on_workflow_created"),
        ("dashboard_metrics", "on_workflow_created"),
    ],
    # ... more mappings
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Query Flow                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  API Request                                                     │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────┐                                             │
│  │  Query Handler  │  ← Contains business logic                  │
│  └────────┬────────┘                                             │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐                                             │
│  │   Projection    │  ← Maintains read model state               │
│  └────────┬────────┘                                             │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐     ┌─────────────────┐                     │
│  │ ProjectionStore │ ──▶ │   PostgreSQL    │  (production)       │
│  │   Protocol      │     │   In-Memory     │  (testing)          │
│  └─────────────────┘     └─────────────────┘                     │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                        Event Flow                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Event Store                                                     │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────┐                                         │
│  │ Projection Manager  │  ← Routes events to projections         │
│  └────────┬────────────┘                                         │
│           │                                                      │
│           ├──────────────┬──────────────┬──────────────┐         │
│           ▼              ▼              ▼              ▼         │
│    WorkflowList    WorkflowDetail  SessionList   Metrics         │
│    Projection      Projection      Projection    Projection      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Query Slices Implemented

| Slice | Context | Purpose |
|-------|---------|---------|
| `list_workflows` | workflows | List workflow summaries |
| `get_workflow_detail` | workflows | Get detailed workflow view |
| `list_sessions` | sessions | List session summaries |
| `list_artifacts` | artifacts | List artifact summaries |
| `get_metrics` | metrics | Dashboard aggregate metrics |
| `list_accessible_repos` | github | List repositories accessible to GitHub App installation |

## Consequences

### Positive

1. **VSA Compliance**: Each feature is a self-contained vertical slice
2. **Testability**: Projections can be tested in isolation with in-memory stores
3. **Scalability**: Teams can work on different slices in parallel
4. **Flexibility**: Storage implementation can be swapped without changing domain
5. **Clarity**: Clear separation between query definitions, handlers, and projections
6. **Catch-up Ready**: Projection positions tracked for event replay

### Negative

1. **More Files**: Each feature requires multiple files
2. **Boilerplate**: Handler/Projection pattern requires some repetition
3. **Learning Curve**: Team needs to understand VSA and CQRS patterns

### Neutral

1. **Event Routing**: Central `EVENT_HANDLERS` mapping needs maintenance
2. **Projection Rebuilding**: Not yet implemented (future work)

## Implementation Notes

### Testing Strategy

```python
# Each slice has isolated tests
@pytest.fixture
def memory_store():
    return InMemoryProjectionStore()

@pytest.fixture
def projection(memory_store):
    return WorkflowListProjection(memory_store)

async def test_on_workflow_created(projection):
    await projection.on_workflow_created({"workflow_id": "wf-1", ...})
    summaries = await projection.get_all()
    assert len(summaries) == 1
```

### API Integration

```python
@router.get("/workflows")
async def list_workflows():
    manager = get_projection_manager()
    handler = ListWorkflowsHandler(manager.workflow_list)
    return await handler.handle(ListWorkflowsQuery())
```

## Related Decisions

- **ADR-006**: Hook Architecture (command side)
- **ADR-007**: Event Store Integration
- **ADR-009**: CQRS Pattern Implementation (event-sourcing-platform)

## References

- [Vertical Slice Architecture](https://jimmybogard.com/vertical-slice-architecture/)
- [CQRS Pattern](https://martinfowler.com/bliki/CQRS.html)
- [Event Sourcing Platform ADRs](../lib/event-sourcing-platform/docs/adrs/)
