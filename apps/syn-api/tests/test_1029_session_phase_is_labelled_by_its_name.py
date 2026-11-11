"""#1029: a session's phase is labelled by the name its execution recorded.

A session carries only its phase's id. ``phase_display`` was
``format_phase(phase_id)``, so ``fix`` read "Fix" and a UUID read
"Phase 3f2a..." while the execution's ``phases[].name`` said what the phase
was. The name lives in the execution detail read model, so a page of sessions
reads its executions once, keyed by id.

WHAT FAILS WITHOUT THE CHANGE. The name tests: ``phase_name`` did not exist and
``phase_display`` was "Fix". The batching test: no execution was read at all,
so the name could not arrive. "Address what verification found" is never
derivable from ``fix``, so a response carrying it read it from the execution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from syn_api.types import Ok, SessionDetail, SessionSummary
from syn_domain.pagination import Page
from syn_shared.display import format_phase

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_api.routes.sessions import SessionResponse, SessionSummaryResponse
    from syn_domain.pagination import ProjectionRecord

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

DETAILS = "workflow_execution_details"
EXEC_ID = "exec-1029"
NAME = "Address what verification found"


@pytest.fixture(autouse=True)
def _reset_storage():
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


def _phase(phase_id: str, name: str) -> dict[str, str]:
    return {"workflow_phase_id": phase_id, "name": name, "status": "completed"}


async def _seed_execution(execution_id: str, phases: list[dict[str, str]]) -> None:
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    await get_projection_mgr().store.save(
        DETAILS, execution_id, {"execution_id": execution_id, "phases": phases}
    )


async def _list(rows: list[SessionSummary]) -> list[SessionSummaryResponse]:
    from syn_api.routes import sessions

    page = Page(rows=rows, total=len(rows), status_counts={})
    with (
        patch.object(sessions, "list_sessions", new=AsyncMock(return_value=Ok(page))),
        patch.object(sessions, "_load_session_costs", new=AsyncMock(return_value={})),
    ):
        response = await sessions.list_sessions_endpoint(
            workflow_id=None,
            execution_id=None,
            status=None,
            statuses=None,
            started_after=None,
            started_before=None,
            q=None,
            page=1,
            page_size=50,
            limit=None,
        )
    return response.sessions


async def _detail(execution_id: str, phase_id: str) -> SessionResponse:
    from syn_api.routes import sessions

    detail = SessionDetail(
        id="sess-1029", workflow_id=None, execution_id=execution_id, phase_id=phase_id
    )
    with (
        patch("syn_api.prefix_resolver.resolve_or_raise", new=AsyncMock(return_value=detail.id)),
        patch.object(sessions, "get_session", new=AsyncMock(return_value=Ok(detail))),
    ):
        return await sessions.get_session_endpoint(detail.id)


def _row(session_id: str, execution_id: str, phase_id: str) -> SessionSummary:
    return SessionSummary(
        id=session_id,
        workflow_id=None,
        execution_id=execution_id,
        phase_id=phase_id,
        status="completed",
    )


async def test_the_list_labels_the_phase_by_its_recorded_name() -> None:
    await _seed_execution(EXEC_ID, [_phase("verify", "Verify the change"), _phase("fix", NAME)])

    (row,) = await _list([_row("sess-1029", EXEC_ID, "fix")])

    assert row.phase_name == NAME
    assert row.phase_display == NAME
    assert row.phase_id == "fix"


async def test_the_detail_labels_the_phase_by_its_recorded_name() -> None:
    await _seed_execution(EXEC_ID, [_phase("fix", NAME)])

    body = await _detail(EXEC_ID, "fix")

    assert body.phase_name == NAME
    assert body.phase_display == NAME
    assert body.phase_id == "fix"


@pytest.mark.parametrize(
    ("execution_id", "phase_id"),
    [
        pytest.param("exec-missing", "fix", id="execution-not-found"),
        pytest.param(EXEC_ID, "reverify", id="phase-not-on-execution"),
        # The projection stores the id as the name when PhaseStarted had none.
        pytest.param(EXEC_ID, "3f2a9c1e-0b7d-4e55-9a1c-2d6f8e0b4c11", id="name-is-the-id"),
    ],
)
async def test_an_unknown_name_falls_back_to_the_formatted_id(
    execution_id: str, phase_id: str
) -> None:
    unnamed = "3f2a9c1e-0b7d-4e55-9a1c-2d6f8e0b4c11"
    await _seed_execution(EXEC_ID, [_phase("fix", NAME), _phase(unnamed, unnamed)])

    (row,) = await _list([_row("sess-1029", execution_id, phase_id)])
    body = await _detail(execution_id, phase_id)

    for response in (row, body):
        assert response.phase_name is None
        assert response.phase_display == format_phase(phase_id)


class _CountingStore:
    """A projection store that answers execution reads and counts them."""

    def __init__(self, documents: dict[str, ProjectionRecord]) -> None:
        self._documents = documents
        self.execution_reads = 0

    async def get(self, projection: str, key: str) -> ProjectionRecord | None:
        if projection == DETAILS:
            self.execution_reads += 1
        return self._documents.get(key) if projection == DETAILS else None

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        if projection == DETAILS:
            self.execution_reads += 1
            return {k: self._documents[k] for k in keys if k in self._documents}
        return {}


@dataclass(frozen=True)
class _Manager:
    store: _CountingStore


async def test_a_page_reads_each_execution_at_most_once() -> None:
    from syn_api.routes import sessions

    store = _CountingStore(
        {
            "exec-a": {"phases": [_phase("fix", NAME)]},
            "exec-b": {"phases": [_phase("finalize_pr", "Open the pull request")]},
        }
    )
    rows = [
        _row(f"sess-{i}", "exec-a" if i % 2 else "exec-b", "fix" if i % 2 else "finalize_pr")
        for i in range(10)
    ]

    with patch.object(sessions, "get_projection_mgr", return_value=_Manager(store)):
        listed = await _list(rows)

    assert store.execution_reads <= 2
    assert {r.phase_display for r in listed} == {NAME, "Open the pull request"}
