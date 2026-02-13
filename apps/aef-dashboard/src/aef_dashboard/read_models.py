"""Read models for dashboard queries.

This implements the read side of CQRS - querying data from PostgreSQL
while writes go through the Event Store Server (gRPC).

In TEST environment, queries use in-memory repositories for isolation.
In DEVELOPMENT/PRODUCTION, queries PostgreSQL directly.

Uses asyncpg for non-blocking database access.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aef_shared.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

logger = logging.getLogger(__name__)

# Connection timeout in seconds
DB_TIMEOUT = 5.0


@dataclass
class WorkflowReadModel:
    """Read model for workflow data."""

    id: str
    name: str
    workflow_type: str
    classification: str
    status: str
    phases: list[dict[str, Any]] = field(default_factory=list)
    description: str | None = None
    created_at: datetime | None = None


@dataclass
class SessionReadModel:
    """Read model for session data."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    status: str
    agent_provider: str | None
    total_tokens: int
    total_cost_usd: float
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class ArtifactReadModel:
    """Read model for artifact data."""

    id: str
    workflow_id: str | None
    phase_id: str | None
    artifact_type: str
    title: str | None
    size_bytes: int
    created_at: datetime | None = None


def _is_test_environment() -> bool:
    """Check if we're running in test environment."""
    return get_settings().is_test


def get_database_url() -> str:
    """Get the database URL from centralized settings."""
    from aef_shared.settings.config import get_settings

    settings = get_settings()
    if not settings.aef_observability_db_url:
        raise ValueError("AEF_OBSERVABILITY_DB_URL must be configured. Set it in your .env file.")
    return str(settings.aef_observability_db_url)


def _parse_workflow_from_event(event_data: dict[str, Any]) -> WorkflowReadModel:
    """Parse a WorkflowCreated event into a read model."""
    return WorkflowReadModel(
        id=event_data.get("workflow_id", ""),
        name=event_data.get("name", "Unnamed"),
        workflow_type=event_data.get("workflow_type", "unknown"),
        classification=event_data.get("classification", "standard"),
        status="pending",  # Default status for created workflows
        phases=event_data.get("phases", []),
        description=event_data.get("description"),
        created_at=None,
    )


async def _query_with_timeout[T](
    query_func: Callable[[], Awaitable[T]], timeout: float = DB_TIMEOUT
) -> T | None:
    """Execute a query function with timeout."""
    try:
        return await asyncio.wait_for(query_func(), timeout=timeout)
    except TimeoutError:
        logger.warning("Database query timed out after %s seconds", timeout)
        return None
    except Exception as e:
        logger.error("Database query failed: %s", e)
        return None


# =============================================================================
# TEST ENVIRONMENT - Read from in-memory repositories
# =============================================================================


async def _get_all_workflows_test() -> list[WorkflowReadModel]:
    """Get all workflows from in-memory storage (test only)."""
    from aef_adapters.storage import get_workflow_repository

    repo = get_workflow_repository()
    # In-memory repo has get_all method (sync)
    if hasattr(repo, "get_all"):
        workflows = repo.get_all()
        return [
            WorkflowReadModel(
                id=w.id,
                name=w._name or "Unnamed",
                workflow_type=str(w._workflow_type) if w._workflow_type else "unknown",
                classification=str(w._classification) if w._classification else "standard",
                status=str(w._status.value) if w._status else "pending",
                phases=[
                    {
                        "phase_id": p.phase_id,
                        "name": p.name,
                        "order": p.order,
                        "description": p.description,
                    }
                    for p in (w._phases or [])
                ],
                description=w._description,
                created_at=None,
            )
            for w in workflows
        ]
    return []


async def _get_workflow_by_id_test(workflow_id: str) -> WorkflowReadModel | None:
    """Get a workflow by ID from in-memory storage (test only)."""
    from aef_adapters.storage import get_workflow_repository

    repo = get_workflow_repository()
    # In-memory repo has get_by_id method (async)
    if hasattr(repo, "get_by_id"):
        workflow = await repo.get_by_id(workflow_id)
        if workflow:
            return WorkflowReadModel(
                id=workflow.id,
                name=workflow._name or "Unnamed",
                workflow_type=str(workflow._workflow_type)
                if workflow._workflow_type
                else "unknown",
                classification=str(workflow._classification)
                if workflow._classification
                else "standard",
                status=str(workflow._status.value) if workflow._status else "pending",
                phases=[
                    {
                        "phase_id": p.phase_id,
                        "name": p.name,
                        "order": p.order,
                        "description": p.description,
                    }
                    for p in (workflow._phases or [])
                ],
                description=workflow._description,
                created_at=None,
            )
    return None


async def _get_all_sessions_test() -> list[SessionReadModel]:
    """Get all sessions from in-memory storage (test only)."""
    from aef_adapters.storage import get_session_repository

    repo = get_session_repository()
    if hasattr(repo, "get_all"):
        sessions = repo.get_all()
        return [
            SessionReadModel(
                id=s.id,
                workflow_id=s._workflow_id,
                phase_id=s._phase_id,
                status=str(s._status.value) if s._status else "unknown",
                agent_provider=s._agent_provider,
                total_tokens=s._tokens.total_tokens if hasattr(s, "_tokens") and s._tokens else 0,
                total_cost_usd=float(s._cost.total_cost_usd)
                if hasattr(s, "_cost") and s._cost
                else 0.0,
                started_at=s._started_at,
                completed_at=s._completed_at,
            )
            for s in sessions
        ]
    return []


async def _get_all_artifacts_test() -> list[ArtifactReadModel]:
    """Get all artifacts from in-memory storage (test only)."""
    from aef_adapters.storage import get_artifact_repository

    repo = get_artifact_repository()
    if hasattr(repo, "get_all"):
        artifacts = repo.get_all()
        return [
            ArtifactReadModel(
                id=a.id,
                workflow_id=a._workflow_id,
                phase_id=a._phase_id,
                artifact_type=str(a._artifact_type.value) if a._artifact_type else "unknown",
                title=a._title,
                size_bytes=a._size_bytes or 0,
                created_at=None,  # Artifact doesn't have created_at field
            )
            for a in artifacts
        ]
    return []


# =============================================================================
# PRODUCTION ENVIRONMENT - Read from PostgreSQL
# =============================================================================


async def _get_all_workflows_db() -> list[WorkflowReadModel]:
    """Get all workflows from PostgreSQL."""
    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg not installed, returning empty workflows")
        return []

    async def query() -> list[WorkflowReadModel]:
        database_url = get_database_url()
        workflows: list[WorkflowReadModel] = []

        conn = await asyncpg.connect(database_url, timeout=DB_TIMEOUT)
        try:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (aggregate_id)
                    aggregate_id,
                    event_type,
                    payload,
                    to_timestamp(recorded_time_unix_ms / 1000.0) as created_at
                FROM events
                WHERE aggregate_type = 'Workflow'
                ORDER BY aggregate_id, event_version DESC
            """)

            for row in rows:
                try:
                    payload = row["payload"]
                    if isinstance(payload, (bytes, memoryview)):
                        event_data = json.loads(bytes(payload))
                    else:
                        event_data = payload

                    workflow = _parse_workflow_from_event(event_data)
                    workflow.created_at = row["created_at"]
                    workflows.append(workflow)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to parse workflow event: %s", e)
                    continue

        finally:
            await conn.close()

        return workflows

    result = await _query_with_timeout(query)
    return result if result else []


async def _get_workflow_by_id_db(workflow_id: str) -> WorkflowReadModel | None:
    """Get a workflow by ID from PostgreSQL."""
    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg not installed")
        return None

    async def query() -> WorkflowReadModel | None:
        database_url = get_database_url()

        conn = await asyncpg.connect(database_url, timeout=DB_TIMEOUT)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    event_type,
                    payload,
                    to_timestamp(recorded_time_unix_ms / 1000.0) as created_at
                FROM events
                WHERE aggregate_type = 'Workflow' AND aggregate_id = $1
                ORDER BY event_version ASC
                """,
                workflow_id,
            )

            workflow: WorkflowReadModel | None = None

            for row in rows:
                try:
                    payload = row["payload"]
                    if isinstance(payload, (bytes, memoryview)):
                        event_data = json.loads(bytes(payload))
                    else:
                        event_data = payload

                    event_type = row["event_type"]

                    if event_type == "WorkflowTemplateCreated":
                        workflow = _parse_workflow_from_event(event_data)
                        workflow.created_at = row["created_at"]

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to parse workflow event: %s", e)
                    continue

            return workflow

        finally:
            await conn.close()

    return await _query_with_timeout(query)


async def _get_all_sessions_db() -> list[SessionReadModel]:
    """Get all sessions from PostgreSQL."""
    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg not installed")
        return []

    async def query() -> list[SessionReadModel]:
        database_url = get_database_url()
        sessions: list[SessionReadModel] = []

        conn = await asyncpg.connect(database_url, timeout=DB_TIMEOUT)
        try:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (aggregate_id)
                    aggregate_id,
                    event_type,
                    payload,
                    to_timestamp(recorded_time_unix_ms / 1000.0) as created_at
                FROM events
                WHERE aggregate_type = 'AgentSession'
                ORDER BY aggregate_id, event_version DESC
            """)

            for row in rows:
                try:
                    payload = row["payload"]
                    if isinstance(payload, (bytes, memoryview)):
                        event_data = json.loads(bytes(payload))
                    else:
                        event_data = payload

                    session = SessionReadModel(
                        id=event_data.get("session_id", row["aggregate_id"]),
                        workflow_id=event_data.get("workflow_id"),
                        phase_id=event_data.get("phase_id"),
                        status=event_data.get("status", "unknown"),
                        agent_provider=event_data.get("agent_provider"),
                        total_tokens=event_data.get("total_tokens", 0),
                        total_cost_usd=event_data.get("total_cost_usd", 0.0),
                        started_at=row["created_at"],
                    )
                    sessions.append(session)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to parse session event: %s", e)
                    continue

        finally:
            await conn.close()

        return sessions

    result = await _query_with_timeout(query)
    return result if result else []


async def _get_all_artifacts_db() -> list[ArtifactReadModel]:
    """Get all artifacts from PostgreSQL."""
    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg not installed")
        return []

    async def query() -> list[ArtifactReadModel]:
        database_url = get_database_url()
        artifacts: list[ArtifactReadModel] = []

        conn = await asyncpg.connect(database_url, timeout=DB_TIMEOUT)
        try:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (aggregate_id)
                    aggregate_id,
                    event_type,
                    payload,
                    to_timestamp(recorded_time_unix_ms / 1000.0) as created_at
                FROM events
                WHERE aggregate_type = 'Artifact'
                ORDER BY aggregate_id, event_version DESC
            """)

            for row in rows:
                try:
                    payload = row["payload"]
                    if isinstance(payload, (bytes, memoryview)):
                        event_data = json.loads(bytes(payload))
                    else:
                        event_data = payload

                    artifact = ArtifactReadModel(
                        id=event_data.get("artifact_id", row["aggregate_id"]),
                        workflow_id=event_data.get("workflow_id"),
                        phase_id=event_data.get("phase_id"),
                        artifact_type=event_data.get("artifact_type", "unknown"),
                        title=event_data.get("title"),
                        size_bytes=len(event_data.get("content", "")),
                        created_at=row["created_at"],
                    )
                    artifacts.append(artifact)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to parse artifact event: %s", e)
                    continue

        finally:
            await conn.close()

        return artifacts

    result = await _query_with_timeout(query)
    return result if result else []


# =============================================================================
# Public API - Automatically selects based on environment
# =============================================================================


async def get_all_workflows() -> list[WorkflowReadModel]:
    """Get all workflows from the event store."""
    if _is_test_environment():
        return await _get_all_workflows_test()
    return await _get_all_workflows_db()


async def get_workflow_by_id(workflow_id: str) -> WorkflowReadModel | None:
    """Get a workflow by ID from the event store."""
    if _is_test_environment():
        return await _get_workflow_by_id_test(workflow_id)
    return await _get_workflow_by_id_db(workflow_id)


async def get_all_sessions() -> list[SessionReadModel]:
    """Get all sessions from the event store."""
    if _is_test_environment():
        return await _get_all_sessions_test()
    return await _get_all_sessions_db()


async def get_all_artifacts() -> list[ArtifactReadModel]:
    """Get all artifacts from the event store."""
    if _is_test_environment():
        return await _get_all_artifacts_test()
    return await _get_all_artifacts_db()


async def get_metrics() -> dict[str, Any]:
    """Get aggregated metrics from the event store."""
    workflows = await get_all_workflows()
    sessions = await get_all_sessions()
    artifacts = await get_all_artifacts()

    completed = sum(1 for w in workflows if w.status == "completed")
    failed = sum(1 for w in workflows if w.status == "failed")

    return {
        "total_workflows": len(workflows),
        "completed_workflows": completed,
        "failed_workflows": failed,
        "total_sessions": len(sessions),
        "total_tokens": sum(s.total_tokens for s in sessions),
        "total_cost_usd": sum(s.total_cost_usd for s in sessions),
        "total_artifacts": len(artifacts),
        "total_artifact_bytes": sum(a.size_bytes for a in artifacts),
    }
