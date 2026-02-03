"""Integration test fixtures for Level 4 (real database) verification.

These fixtures connect to the real event store via gRPC.

Uses shared test_infrastructure fixture (ADR-034) which auto-detects:
- test-stack (just test-stack) on port 55051
- testcontainers fallback with dynamic ports

Level 4 Verification: Real persistence roundtrip
- Save aggregate to event store
- Load aggregate back from event store
- Verify events persisted correctly
- Verify projections updated
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository, GrpcEventStoreClient, RepositoryFactory

    from aef_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


# Mark all tests as integration - only run when explicitly requested
pytestmark = pytest.mark.integration


@pytest.fixture
async def grpc_client(test_infrastructure) -> GrpcEventStoreClient:
    """Create gRPC client using shared test infrastructure.

    Note: scope="function" due to pytest-asyncio event loop constraints.
    Each test gets a fresh connection.

    If event store is unavailable, the test will fail with a clear connection error.
    """
    from event_sourcing import GrpcEventStoreClient

    address = f"{test_infrastructure.eventstore_host}:{test_infrastructure.eventstore_port}"
    client = GrpcEventStoreClient(address=address)
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
def repository_factory(grpc_client: GrpcEventStoreClient) -> RepositoryFactory:
    """Create repository factory with real event store client."""
    from event_sourcing import RepositoryFactory

    return RepositoryFactory(grpc_client)


@pytest.fixture
def workflow_execution_repository(
    repository_factory: RepositoryFactory,
) -> EventStoreRepository[WorkflowExecutionAggregate]:
    """Create repository for WorkflowExecution aggregates."""
    from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

    return repository_factory.create_repository(WorkflowExecutionAggregate, "WorkflowExecution")


@pytest.fixture
def agent_session_repository(
    repository_factory: RepositoryFactory,
) -> EventStoreRepository[AgentSessionAggregate]:
    """Create repository for AgentSession aggregates."""
    from aef_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )

    return repository_factory.create_repository(AgentSessionAggregate, "AgentSession")


@pytest.fixture
def unique_execution_id() -> str:
    """Generate unique execution ID for test isolation."""
    return f"test-exec-{uuid4().hex[:8]}"


@pytest.fixture
def unique_session_id() -> str:
    """Generate unique session ID for test isolation."""
    return f"test-session-{uuid4().hex[:8]}"
