# ADR-013: Integration Testing Strategy with Event Store

**Status:** Proposed
**Date:** 2025-12-04
**Authors:** @neural
**Related:** ADR-004 (Environment Configuration), ADR-006 (Event Sourcing)

## Context

On 2025-12-04, we discovered a critical bug where projections failed with:
```
'str' object has no attribute 'isoformat'
```

### Root Cause
- Events serialized to JSON when saved to event store (datetime → ISO string)
- Events deserialized when read back (ISO string stays as string)
- Projections assumed datetime objects, called `.isoformat()` on strings

### Why Tests Didn't Catch It
1. **Unit tests use `MemoryEventStoreClient`** - no JSON serialization round-trip
2. **API tests create fixtures directly** - bypass event store entirely
3. **No integration tests with real event store** - where serialization happens

This is a symptom of insufficient integration test coverage with realistic infrastructure.

## Decision

Implement a **three-tier testing strategy** following the event-sourcing-platform pattern:

### Tier 1: Unit Tests (Fast, In-Memory)
- Use `MemoryEventStoreClient` or mocks
- Test business logic, validation, event handlers
- ~0.1s per test
- Run on every commit

### Tier 2: Integration Tests (Real Event Store)
- Use testcontainers for isolated event store instance
- Test serialization, projection handlers, subscription service
- ~0.5s per test
- Run in CI, optional locally

### Tier 3: E2E Tests (Full Stack)
- Real infrastructure (Docker Compose)
- Test complete workflows with UI
- ~2s per test
- Run before merge

### Fast Development Mode (from event-sourcing-platform)

For local development:
```bash
# Pre-running infrastructure (~50ms startup)
export TEST_DATABASE_URL=postgresql://localhost:15648/test
export TEST_EVENTSTORE_URL=localhost:50051
```

For CI:
```bash
# Testcontainers fallback (isolated but slower)
export FORCE_TESTCONTAINERS=1
```

## Implementation Plan

### Phase 1: Add testcontainers to aef-adapters

```toml
# packages/aef-adapters/pyproject.toml
[project.optional-dependencies]
test = [
    "pytest-testcontainers>=0.0.4",
    "testcontainers[postgres]>=4.0.0",
]
```

### Phase 2: Create integration test fixtures

```python
# packages/aef-adapters/tests/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def event_store_container():
    """Start event store for integration tests."""
    # Check for dev infrastructure first
    if os.getenv("TEST_EVENTSTORE_URL"):
        yield os.getenv("TEST_EVENTSTORE_URL")
        return

    # Fallback to testcontainers
    with PostgresContainer("postgres:15") as postgres:
        yield postgres.get_connection_url()
```

### Phase 3: Add integration tests for projections

```python
# packages/aef-adapters/tests/integration/test_projection_serialization.py
@pytest.mark.integration
async def test_session_projection_round_trip(event_store_container):
    """Test that projections handle event store serialization correctly."""
    client = await connect_event_store(event_store_container)

    # Create aggregate, emit event
    session = AgentSessionAggregate()
    session.start(...)
    await repository.save(session)

    # Load from event store, process through projection
    events = await client.read_stream(...)
    await projection_manager.process_event_envelope(events[0])

    # Verify projection handled datetime serialization
    sessions = await projection.get_all()
    assert len(sessions) == 1
    assert isinstance(sessions[0].started_at, str)  # ISO string from event store
```

### Phase 4: CI Configuration

```yaml
# .github/workflows/ci.yml
jobs:
  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
    env:
      FORCE_TESTCONTAINERS: "1"
    steps:
      - run: uv run pytest -m integration
```

## Consequences

### Positive
- **Catches serialization bugs** - datetime, decimal, enum handling tested
- **Realistic test environment** - CI tests match production behavior
- **Fast development** - pre-running infrastructure for local testing
- **Isolated CI** - testcontainers ensure clean state per run

### Negative
- **Slower CI** - integration tests add ~30-60s to pipeline
- **Docker dependency** - requires Docker for local integration tests
- **Complexity** - two-mode testing (fast dev vs testcontainers)

### Neutral
- **Existing tests unchanged** - unit tests continue working as-is
- **Gradual adoption** - can add integration tests incrementally

## Future Considerations

### Event Store SDK Deserialization
The event-sourcing Python SDK could optionally deserialize datetime fields:
```python
class DomainEvent(BaseModel):
    model_config = {
        "json_decoders": {
            datetime: lambda v: datetime.fromisoformat(v) if isinstance(v, str) else v
        }
    }
```

This would move the burden from application code to the SDK, but requires:
1. SDK change in event-sourcing-platform
2. Schema/type hints for datetime fields
3. Migration path for existing events

For now, the defensive approach in read models (handle both datetime and string) is simpler and more resilient.

## Related Patterns from event-sourcing-platform

From `lib/event-sourcing-platform/`:
- **Fast Testing**: `docs-site/docs/development/fast-testing.md`
- **Testcontainers Rust**: `event-store/eventstore-backend-postgres/tests/`
- **Testcontainers Kotlin**: `referene/eventsourcing-book/src/test/kotlin/`

Key insight: The platform uses **persistent dev containers** for fast iteration, with **testcontainers fallback** for CI isolation.

## References

- [pytest-testcontainers](https://github.com/testcontainers/testcontainers-python)
- [event-sourcing-platform testing docs](lib/event-sourcing-platform/docs-site/docs/development/fast-testing.md)
- ADR-004: Environment Configuration
- ADR-006: Event Sourcing with EventStoreDB
