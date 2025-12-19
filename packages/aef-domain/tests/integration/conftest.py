"""Integration test fixtures for Level 4 (real database) verification.

These fixtures connect to the real event store via gRPC.
Requires: docker compose -f docker/docker-compose.dev.yaml up

Level 4 Verification: Real persistence roundtrip
- Save aggregate to event store
- Load aggregate back from event store
- Verify events persisted correctly
- Verify projections updated
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from event_sourcing import EventStoreRepository, GrpcEventStoreClient, RepositoryFactory

    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


# Event store connection settings
EVENT_STORE_HOST = os.getenv("EVENT_STORE_HOST", "localhost")
EVENT_STORE_PORT = os.getenv("EVENT_STORE_PORT", "50051")
EVENT_STORE_ADDRESS = f"{EVENT_STORE_HOST}:{EVENT_STORE_PORT}"

# Skip if no event store available
pytestmark = pytest.mark.integration


def is_event_store_available() -> bool:
    """Check if event store is reachable."""
    import socket

    try:
        with socket.create_connection((EVENT_STORE_HOST, int(EVENT_STORE_PORT)), timeout=2):
            return True
    except (OSError, TimeoutError):
        return False


# Skip all tests in this module if event store not available
pytest.importorskip("event_sourcing", reason="event_sourcing package required")


@pytest.fixture
async def grpc_client() -> GrpcEventStoreClient:
    """Create gRPC client connected to real event store.

    Note: scope="function" due to pytest-asyncio event loop constraints.
    Each test gets a fresh connection.
    """
    from event_sourcing import GrpcEventStoreClient

    if not is_event_store_available():
        pytest.skip(f"Event store not available at {EVENT_STORE_ADDRESS}")

    client = GrpcEventStoreClient(address=EVENT_STORE_ADDRESS)
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
    from aef_domain.contexts.workflows._shared.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

    return repository_factory.create_repository(WorkflowExecutionAggregate, "WorkflowExecution")


@pytest.fixture
def agent_session_repository(
    repository_factory: RepositoryFactory,
) -> EventStoreRepository[AgentSessionAggregate]:
    """Create repository for AgentSession aggregates."""
    from aef_domain.contexts.sessions._shared.AgentSessionAggregate import (
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
