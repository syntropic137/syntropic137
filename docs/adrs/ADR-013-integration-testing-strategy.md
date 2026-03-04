# ADR-013: Integration Testing Strategy with Event Store

**Status:** Accepted
**Date:** 2025-12-04
**Updated:** 2025-12-16
**Authors:** @neural
**Related:** ADR-004 (Environment Configuration), ADR-006 (Event Sourcing), ADR-018 (Observability Events)

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

### 2025-12-16 Update: Tool Observability Testing

While implementing tool observability (parsing SDK messages for tool_use/tool_result events), we developed a fast unit testing approach that validates parsing logic **without Claude API calls**. This reduced feedback time from 5+ minutes to 0.24 seconds.

**Key Insight**: For external API integrations (Claude SDK, GitHub API, etc.), create mock message types that match the SDK's structure. This enables comprehensive testing without:
- API costs
- Network latency
- Rate limiting
- Flaky external dependencies

## Decision

Implement a **three-tier testing strategy** following the event-sourcing-platform pattern:

### ⚠️ CRITICAL: Test Environment Isolation

**Mocks and memory implementations MUST only be used in the `test` environment.**

```python
# conftest.py - CORRECT pattern
import os
import pytest

@pytest.fixture
def event_store_client():
    """Get event store client - memory only in tests."""
    env = os.getenv("SYN_ENVIRONMENT", "development")

    if env == "test":
        # Memory client is ONLY acceptable in tests
        from syn_adapters.storage.memory import MemoryEventStoreClient
        return MemoryEventStoreClient()
    else:
        # NEVER use memory client in dev/prod - will give false positives!
        raise RuntimeError(
            f"Tests must run with SYN_ENVIRONMENT=test, got {env}. "
            "Memory implementations must not leak into dev/prod."
        )
```

**Why This Matters**:
- Memory implementations skip serialization → miss JSON encoding bugs
- Memory implementations skip network → miss connectivity issues
- Memory implementations skip auth → miss permission bugs
- **False positives in dev/prod are WORSE than no tests** - they create false confidence

**Enforcement**:
```python
# In production code - defensive check
class MemoryEventStoreClient:
    def __init__(self):
        env = os.getenv("SYN_ENVIRONMENT", "development")
        if env not in ("test", "testing"):
            raise RuntimeError(
                "MemoryEventStoreClient can only be used in test environment. "
                f"Current environment: {env}"
            )
```

### Tier 1: Unit Tests (Fast, <1s total)
- Use mocks for external APIs (Claude SDK, GitHub, etc.)
- Use `MemoryEventStoreClient` for event store logic (**test env only!**)
- Test business logic, validation, parsing, event handlers
- **Goal: <0.5s for full suite** - enables rapid iteration
- Run on every save/change

**Example: SDK Message Parsing (from tool observability)**
```python
# packages/syn-agent-runner/tests/test_runner.py
@dataclass
class MockToolUseBlock:
    """Mock SDK ToolUseBlock - no API calls needed."""
    type: str = "tool_use"
    id: str = "toolu_01abc123"
    name: str = "Bash"
    input: dict = field(default_factory=lambda: {"command": "ls"})

class TestToolObservabilityParsing:
    """15 tests in 0.24 seconds - no Claude API!"""

    def test_parses_tool_use_block_object(self, runner):
        message = MockAssistantMessage(
            content=[MockToolUseBlock(name="Bash", id="toolu_001")]
        )
        with mock.patch("syn_agent_runner.runner.emit_tool_use") as m:
            runner._handle_assistant_message(message)
            m.assert_called_once()
```

### Tier 2: Integration Tests (Real Infrastructure, ~10s)
- Use testcontainers for isolated event store instance
- Test serialization round-trips, projection handlers, subscription service
- **Catches bugs that mocks miss** (datetime serialization, JSON encoding)
- Run in CI, optional locally with pre-running containers

### Tier 3: E2E Tests (Full Stack, ~5min)
- Real infrastructure (Docker Compose)
- Test complete workflows: Agent → Event Store → API → UI
- Run sparingly - before PR merge
- **Not for rapid iteration** - use for validation gates only

### Mock Patterns for External APIs

When testing code that interacts with external APIs (Claude SDK, GitHub, etc.), create mock objects that match the SDK's structure using duck typing:

```python
# Use dataclasses to create type-safe mocks
@dataclass
class MockToolUseBlock:
    type: str = "tool_use"
    id: str = "toolu_01abc123"
    name: str = "Bash"
    input: dict = field(default_factory=dict)

@dataclass
class MockAssistantMessage:
    content: list = field(default_factory=list)
    usage: MockUsage = field(default_factory=MockUsage)
```

**Benefits**:
- Type-safe: IDEs provide autocomplete
- Explicit: Clear what's being mocked
- Portable: Can be shared across test modules
- SDK-agnostic: Works even if SDK types aren't exported

**Consider for agentic-primitives**: These mock patterns could become canonical test fixtures that all Syn137 packages share.

### Fast Development Mode (from event-sourcing-platform)

For local development:
```bash
# Pre-running infrastructure (~50ms startup)
export TEST_DATABASE_URL=postgresql://localhost:15648/test
export TEST_EVENTSTORE_URL=localhost:50051
export SYN_ENVIRONMENT=test  # Required for memory implementations!
```

For CI:
```bash
# Testcontainers fallback (isolated but slower)
export FORCE_TESTCONTAINERS=1
export SYN_ENVIRONMENT=test
```

## Implementation Plan

### Phase 1: Add testcontainers to syn-adapters

```toml
# packages/syn-adapters/pyproject.toml
[project.optional-dependencies]
test = [
    "pytest-testcontainers>=0.0.4",
    "testcontainers[postgres]>=4.0.0",
]
```

### Phase 2: Create integration test fixtures

```python
# packages/syn-adapters/tests/conftest.py
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
# packages/syn-adapters/tests/integration/test_projection_serialization.py
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
- **Rapid iteration** - unit tests <1s enable TDD workflow
- **No API costs** - mocks eliminate Claude/GitHub API charges during development

### Negative
- **Slower CI** - integration tests add ~30-60s to pipeline
- **Docker dependency** - requires Docker for local integration tests
- **Complexity** - two-mode testing (fast dev vs testcontainers)
- **Mock maintenance** - mocks must be updated when SDK changes

### Critical: Environment Isolation
- **Memory implementations MUST NOT leak to dev/prod**
- **Mocks give false positives** if used outside test environment
- **Defensive checks required** in memory implementations
- **CI must set `SYN_ENVIRONMENT=test`** explicitly

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
- [agentic-primitives TDD ADR](lib/agentic-primitives/docs/adrs/008-test-driven-development.md)
- ADR-004: Environment Configuration
- ADR-006: Event Sourcing with EventStoreDB
- ADR-018: Commands vs Observations Event Architecture

### Implementation Examples
- `packages/syn-agent-runner/tests/test_runner.py` - Fast unit tests for SDK message parsing
- `packages/syn-adapters/tests/conftest.py` - Test fixture patterns
- `docker/test-observability/` - Isolated integration test environment
