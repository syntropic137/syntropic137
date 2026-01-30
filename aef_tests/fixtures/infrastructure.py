"""Test infrastructure fixtures.

Provides database and service connections for integration tests.
Uses test-stack if running, otherwise falls back to testcontainers.

See: ADR-034 - Test Infrastructure Architecture
See: es-p pattern in lib/event-sourcing-platform
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# Set AGENTIC_RECORDINGS_DIR for recording-based tests
_AEF_ROOT = Path(__file__).parent.parent.parent  # aef_tests/fixtures/infrastructure.py -> AEF root
_RECORDINGS_DIR = (
    _AEF_ROOT / "lib/agentic-primitives/providers/workspaces/claude-cli/fixtures/recordings"
)
if _RECORDINGS_DIR.exists() and "AGENTIC_RECORDINGS_DIR" not in os.environ:
    os.environ["AGENTIC_RECORDINGS_DIR"] = str(_RECORDINGS_DIR)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import asyncpg

# Test stack ports (offset by +10000 from dev)
TEST_STACK_PORTS = {
    "timescaledb": 15432,
    "eventstore": 55051,
    "collector": 18080,
    "minio_api": 19000,
    "minio_console": 19001,
    "redis": 16379,
}

# Dev stack ports (for reference)
DEV_STACK_PORTS = {
    "timescaledb": 5432,
    "eventstore": 50051,
    "collector": 8080,
    "minio_api": 9000,
    "minio_console": 9001,
    "redis": 6379,
}


@dataclass
class TestInfrastructure:
    """Test infrastructure connection details."""

    timescaledb_url: str
    eventstore_host: str
    eventstore_port: int
    collector_url: str
    minio_url: str
    redis_url: str
    source: str = "unknown"  # "env", "test-stack", "testcontainers"

    @property
    def is_testcontainer(self) -> bool:
        """True if using testcontainers (not test-stack)."""
        return self.source == "testcontainers"

    @property
    def is_test_stack(self) -> bool:
        """True if using the test-stack (just test-stack)."""
        return self.source == "test-stack"


def _check_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _check_test_stack_running() -> bool:
    """Check if test-stack is running by probing TimescaleDB port."""
    return _check_port_open("localhost", TEST_STACK_PORTS["timescaledb"])


def _get_test_stack_infrastructure() -> TestInfrastructure:
    """Get infrastructure config for running test-stack."""
    return TestInfrastructure(
        timescaledb_url=f"postgres://aef:aef_dev_password@localhost:{TEST_STACK_PORTS['timescaledb']}/aef",
        eventstore_host="localhost",
        eventstore_port=TEST_STACK_PORTS["eventstore"],
        collector_url=f"http://localhost:{TEST_STACK_PORTS['collector']}",
        minio_url=f"http://localhost:{TEST_STACK_PORTS['minio_api']}",
        redis_url=f"redis://localhost:{TEST_STACK_PORTS['redis']}",
        source="test-stack",
    )


def _get_env_infrastructure() -> TestInfrastructure:
    """Get infrastructure from environment variables.

    Supports two styles:
    - Full URL: TEST_DATABASE_URL=postgres://user:pass@host:port/db
    - Components: TEST_TIMESCALEDB_HOST + TEST_TIMESCALEDB_PORT
    """
    # Build TimescaleDB URL from components or use full URL
    if os.environ.get("TEST_DATABASE_URL"):
        timescaledb_url = os.environ["TEST_DATABASE_URL"]
    else:
        host = os.environ.get("TEST_TIMESCALEDB_HOST", "localhost")
        port = os.environ.get("TEST_TIMESCALEDB_PORT", "15432")
        timescaledb_url = f"postgres://aef:aef_dev_password@{host}:{port}/aef_observability"

    return TestInfrastructure(
        timescaledb_url=timescaledb_url,
        eventstore_host=os.environ.get("TEST_EVENTSTORE_HOST", "localhost"),
        eventstore_port=int(os.environ.get("TEST_EVENTSTORE_PORT", "55051")),
        collector_url=os.environ.get("TEST_COLLECTOR_URL", "http://localhost:18080"),
        minio_url=os.environ.get("TEST_MINIO_URL", "http://localhost:19000"),
        redis_url=os.environ.get("TEST_REDIS_URL", "redis://localhost:16379"),
        source="env",
    )


async def _get_testcontainer_infrastructure() -> tuple[TestInfrastructure, Any]:
    """Spin up testcontainers and return infrastructure config.

    Returns:
        Tuple of (TestInfrastructure, containers_to_cleanup)
    """
    # Import here to avoid dependency if not needed
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    containers: list[Any] = []

    # Start containers (they pick random available ports)
    postgres = PostgresContainer("timescale/timescaledb:latest-pg16")
    postgres.start()
    containers.append(postgres)

    redis = RedisContainer("redis:7-alpine")
    redis.start()
    containers.append(redis)

    # For now, skip eventstore/collector/minio in testcontainers
    # They can be added later as needed

    # testcontainers returns postgresql+psycopg2:// but asyncpg needs postgresql://
    pg_url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

    infra = TestInfrastructure(
        timescaledb_url=pg_url,
        eventstore_host="localhost",
        eventstore_port=0,  # Not available in testcontainers mode
        collector_url="",  # Not available
        minio_url="",  # Not available
        redis_url=f"redis://localhost:{redis.get_exposed_port(6379)}",
        source="testcontainers",
    )

    return infra, containers


@pytest.fixture(scope="session")
async def test_infrastructure() -> AsyncGenerator[TestInfrastructure, None]:
    """Get test infrastructure - uses test-stack if running, else testcontainers.

    Detection order:
    1. Explicit env vars (TEST_DATABASE_URL, etc.) - for CI override
    2. Test-stack running (port 15432) - for local continuous testing
    3. Testcontainers fallback - for CI/hermetic testing

    Usage:
        def test_something(test_infrastructure: TestInfrastructure):
            conn = await asyncpg.connect(test_infrastructure.timescaledb_url)
    """
    containers: list[Any] = []

    # 1. Check for explicit env var override (full URL or host/port components)
    if os.environ.get("TEST_DATABASE_URL") or os.environ.get("TEST_TIMESCALEDB_HOST"):
        print("📌 Using infrastructure from environment variables")
        yield _get_env_infrastructure()
        return

    # 2. Check if test-stack is running
    if _check_test_stack_running():
        print("🚀 Using running test-stack (just test-stack)")
        yield _get_test_stack_infrastructure()
        return

    # 3. Fallback to testcontainers
    print("🐳 Test-stack not running, spinning up testcontainers...")
    infra, containers = await _get_testcontainer_infrastructure()
    yield infra

    # Cleanup
    import contextlib

    for container in containers:
        with contextlib.suppress(Exception):
            container.stop()


@pytest.fixture
async def db_pool(
    test_infrastructure: TestInfrastructure,
) -> AsyncGenerator[asyncpg.Pool, None]:
    """Get database connection pool.

    Usage:
        async def test_query(db_pool):
            async with db_pool.acquire() as conn:
                result = await conn.fetch("SELECT 1")
    """
    import asyncpg

    pool = await asyncpg.create_pool(test_infrastructure.timescaledb_url)
    if pool is None:
        msg = "Failed to create database pool"
        raise RuntimeError(msg)
    yield pool
    await pool.close()


@pytest.fixture
async def db_connection(
    test_infrastructure: TestInfrastructure,
) -> AsyncGenerator[asyncpg.Connection, None]:
    """Get single database connection (simpler than pool for basic tests).

    Usage:
        async def test_query(db_connection):
            result = await db_connection.fetch("SELECT 1")
    """
    import asyncpg

    conn = await asyncpg.connect(test_infrastructure.timescaledb_url)
    yield conn
    await conn.close()
