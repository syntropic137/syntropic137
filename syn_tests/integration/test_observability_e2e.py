"""End-to-end integration tests for observability pipeline.

Tests the observability infrastructure with live services.
Requires test-stack running or falls back to testcontainers.

See: ADR-034 - Test Infrastructure Architecture
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:
    import asyncpg

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = [pytest.mark.integration]


def _make_event_id(session_id: str, event_type: str, timestamp: str) -> str:
    """Generate deterministic event ID."""
    content = f"{session_id}:{event_type}:{timestamp}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _make_batch(
    events: list[dict[str, Any]],
    agent_id: str = "test-agent",
    session_id: str = "test-session",
) -> dict[str, Any]:
    """Convert raw events to EventBatch format expected by collector."""
    batch_id = str(uuid.uuid4())
    collected_events = []

    for event in events:
        evt_session_id = event.get("session_id", session_id)
        event_type = event.get("type", "session_started")
        timestamp = event.get("timestamp", datetime.now(tz=UTC).isoformat())

        # Map Claude event types to collector event types
        type_mapping = {
            "system.init": "session_started",
            "result": "session_ended",
            "tool_use": "tool_execution_started",
            "tool_result": "tool_execution_completed",
        }
        mapped_type = type_mapping.get(event_type, event_type)

        collected_events.append(
            {
                "event_id": _make_event_id(evt_session_id, mapped_type, timestamp),
                "event_type": mapped_type,
                "session_id": evt_session_id,
                "timestamp": timestamp,
                "data": event,
            }
        )

    return {
        "agent_id": agent_id,
        "batch_id": batch_id,
        "events": collected_events,
    }


class TestCollectorIngestion:
    """Test event ingestion through the Collector service."""

    @pytest.mark.asyncio
    async def test_collector_health_endpoint(self, test_infrastructure: TestInfrastructure) -> None:
        """Collector health endpoint is accessible."""
        if not test_infrastructure.collector_url:
            pytest.skip("Collector not available in testcontainers mode")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{test_infrastructure.collector_url}/health",
                timeout=5.0,
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_collector_accepts_events(self, test_infrastructure: TestInfrastructure) -> None:
        """Collector accepts event POST requests."""
        if not test_infrastructure.collector_url:
            pytest.skip("Collector not available in testcontainers mode")

        test_event = {
            "type": "system.init",
            "session_id": "test-session-001",
            "timestamp": "2025-01-01T00:00:00Z",
            "data": {"model": "claude-3-5-sonnet-20241022"},
        }

        batch = _make_batch([test_event])

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{test_infrastructure.collector_url}/events",
                json=batch,
                timeout=5.0,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] >= 0

    @pytest.mark.asyncio
    async def test_collector_stats_endpoint(self, test_infrastructure: TestInfrastructure) -> None:
        """Collector stats endpoint returns metrics."""
        if not test_infrastructure.collector_url:
            pytest.skip("Collector not available in testcontainers mode")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{test_infrastructure.collector_url}/stats",
                timeout=5.0,
            )

        assert response.status_code == 200
        data = response.json()
        assert "dedup" in data


class TestDatabaseConnectivity:
    """Test database connectivity (works with testcontainers)."""

    @pytest.mark.asyncio
    async def test_can_connect_to_database(self, db_pool: asyncpg.Pool) -> None:
        """Can establish connection to TimescaleDB."""
        async with db_pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
        assert result == 1

    @pytest.mark.asyncio
    async def test_can_query_pg_version(self, db_pool: asyncpg.Pool) -> None:
        """Can query PostgreSQL version."""
        async with db_pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
        assert "PostgreSQL" in version


class TestSchemaPresence:
    """Test database schema exists (requires test-stack with init-db)."""

    @pytest.mark.asyncio
    async def test_workflow_definitions_table_exists(
        self,
        test_infrastructure: TestInfrastructure,
        db_pool: asyncpg.Pool,
    ) -> None:
        """workflow_definitions table exists and is queryable."""
        if test_infrastructure.is_testcontainer:
            pytest.skip("Testcontainers mode lacks init-db schema")

        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'workflow_definitions'
                )
                """
            )

        assert result is True, "workflow_definitions table should exist"

    @pytest.mark.asyncio
    async def test_event_store_schema_exists(
        self,
        test_infrastructure: TestInfrastructure,
        db_pool: asyncpg.Pool,
    ) -> None:
        """event_store schema and events table exist."""
        if test_infrastructure.is_testcontainer:
            pytest.skip("Testcontainers mode lacks init-db schema")

        async with db_pool.acquire() as conn:
            # Check event_store.events table exists
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'event_store' AND table_name = 'events'
                )
                """
            )

        assert exists is True, "event_store.events table should exist"
