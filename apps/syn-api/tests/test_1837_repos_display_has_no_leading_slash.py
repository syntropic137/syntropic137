"""#1837: an execution started on a repo URL lists `repos_display` as `owner/repo`.

Repos are stored as full URLs, and the label used to split them after `https:`,
so every row read `/github.com/owner/repo`. This replays a real
`WorkflowExecutionStarted` event into the real list projection and calls the
real route function, so the label is checked where the wire sees it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_list: WorkflowExecutionListProjection


async def test_a_repo_url_is_listed_as_owner_slash_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    listing = WorkflowExecutionListProjection(store)
    await listing.on_workflow_execution_started(
        WorkflowExecutionStartedEvent(
            workflow_id="wf-1837",
            execution_id="exec-1837",
            workflow_name="repos",
            started_at=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
            total_phases=1,
            inputs={"repos": "https://github.com/acme/widgets"},
        ).model_dump()
    )
    manager = _StubProjectionManager(store=store, workflow_execution_list=listing)

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)

    # Every parameter explicit: called outside FastAPI, `Query(...)` defaults
    # arrive as `Query` objects rather than the values they describe.
    response = await queries.list_executions_endpoint(
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        tag=None,
        eval_id=None,
        in_eval=None,
        review_verdict=None,
        page=1,
        page_size=50,
    )

    [row] = response.executions
    assert row.model_dump(mode="json")["repos_display"] == "acme/widgets"
