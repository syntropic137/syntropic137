"""#967: an execution's tags reach the HTTP read path, and `?tag=` filters by them.

The domain already records tags on the start event and edits them with
`ExecutionTagsAdded`/`Removed`; the projections already store them. Those
tests stop at the read model. These start from real events, replay them into
the real projections and call the real route functions, so a response model
that does not declare `tags`, a constructor that does not pass it, or a route
that accepts `tag` and never hands it to the projection, all fail here. The
write side is pinned the same way: request tags must reach `execute()` and the
`ExecuteWorkflowCommand` it builds, whose handler test takes it from there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_api.routes.executions.commands import ExecuteWorkflowRequest
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts.orchestration import (
    ExecuteWorkflowCommand,
    TagSet,
    WorkflowNotFoundError,
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionTagsAddedEvent import (
    ExecutionTagsAddedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-967"
NIGHTLY_ID = "exec-nightly-967"
"""Launched with `nightly`, then retroactively tagged `eval:planning-2026-08`."""
PLAIN_ID = "exec-plain-967"
"""Launched with `smoke` only."""


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection
    workflow_execution_list: WorkflowExecutionListProjection


def _started(execution_id: str, tags: list[str]) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        workflow_name="tagged",
        started_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        total_phases=1,
        inputs={},
        tags=tags,
    )


async def _serve(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    listing = WorkflowExecutionListProjection(store)
    retro = ExecutionTagsAddedEvent(
        execution_id=NIGHTLY_ID, workflow_id=WORKFLOW_ID, tags=["eval:planning-2026-08"]
    )
    for projection in (detail, listing):
        await projection.on_workflow_execution_started(
            _started(NIGHTLY_ID, ["nightly"]).model_dump()
        )
        await projection.on_workflow_execution_started(_started(PLAIN_ID, ["smoke"]).model_dump())
        await projection.on_execution_tags_added(retro)
    manager = _StubProjectionManager(
        store=store, workflow_execution_detail=detail, workflow_execution_list=listing
    )

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)


async def _listed(tag: list[str] | None) -> dict[str, list[str]]:
    """`GET /executions?tag=...`, as execution id -> the tags on the wire."""
    from syn_api.routes.executions import queries

    # Every parameter explicit: called outside FastAPI, `Query(...)` defaults
    # arrive as `Query` objects rather than the values they describe.
    response = await queries.list_executions_endpoint(
        status=None,
        statuses=None,
        started_after=None,
        started_before=None,
        q=None,
        tag=tag,
        page=1,
        page_size=50,
    )
    assert response.total == len(response.executions)
    return {e.workflow_execution_id: e.model_dump()["tags"] for e in response.executions}


class TestTheListCarriesTags:
    @pytest.mark.asyncio
    async def test_each_row_carries_its_current_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        await _serve(monkeypatch)
        assert await _listed(None) == {
            NIGHTLY_ID: ["eval:planning-2026-08", "nightly"],
            PLAIN_ID: ["smoke"],
        }


class TestTheTagFilter:
    @pytest.mark.asyncio
    async def test_a_tag_keeps_only_executions_carrying_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _serve(monkeypatch)
        assert set(await _listed(["smoke"])) == {PLAIN_ID}

    @pytest.mark.asyncio
    async def test_a_retroactive_tag_is_filterable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        await _serve(monkeypatch)
        assert set(await _listed(["eval:planning-2026-08"])) == {NIGHTLY_ID}

    @pytest.mark.asyncio
    async def test_an_unknown_tag_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        await _serve(monkeypatch)
        assert await _listed(["no-such-tag"]) == {}

    @pytest.mark.asyncio
    async def test_repeated_tags_are_anded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        await _serve(monkeypatch)
        assert set(await _listed(["nightly", "eval:planning-2026-08"])) == {NIGHTLY_ID}
        assert await _listed(["nightly", "smoke"]) == {}

    @pytest.mark.asyncio
    async def test_the_filter_is_normalised_like_stored_tags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _serve(monkeypatch)
        assert set(await _listed(["  NIGHTLY "])) == {NIGHTLY_ID}

    @pytest.mark.asyncio
    async def test_an_invalid_tag_is_rejected_not_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _serve(monkeypatch)
        with pytest.raises(HTTPException) as raised:
            await _listed(["has space"])
        assert raised.value.status_code == 422
        assert "has space" in str(raised.value.detail)


class TestTheDetailCarriesTags:
    @pytest.mark.asyncio
    async def test_detail_carries_current_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from syn_api.routes.executions import queries

        await _serve(monkeypatch)
        detail = await queries.get_execution_endpoint(NIGHTLY_ID)
        assert detail.model_dump()["tags"] == ["eval:planning-2026-08", "nightly"]


# -- The write path: POST /workflows/{id}/execute ------------------------------


class _WorkflowRepo:
    """A workflow that exists, so the route reaches the execute call at all."""

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return WorkflowTemplateAggregate()


class _CapturingExecute:
    """Stands in for `execute()`, keeping only the tags the route handed it."""

    def __init__(self) -> None:
        self.tags: list[TagSet | None] = []

    async def __call__(
        self,
        *,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None,
        repos: list[object],
        admitted: AdmissionTicket | None = None,
        tags: TagSet | None = None,
        eval_choice: object = None,
    ) -> None:
        del workflow_id, inputs, execution_id, task, repos, eval_choice
        self.tags.append(tags)
        if admitted is not None:
            admitted.mark_visible()


class _CapturingHandler:
    """Stands in for ExecuteWorkflowHandler: records the command, then stops."""

    def __init__(self) -> None:
        self.commands: list[ExecuteWorkflowCommand] = []

    async def handle(
        self, command: ExecuteWorkflowCommand, *, admitted: AdmissionTicket | None = None
    ) -> None:
        del admitted
        self.commands.append(command)
        raise WorkflowNotFoundError(command.aggregate_id)


class TestRequestTagsReachTheCommand:
    def test_the_request_normalises_its_tags(self) -> None:
        request = ExecuteWorkflowRequest.model_validate({"tags": [" Nightly", "nightly", "B"]})
        assert list(request.tags) == ["b", "nightly"]

    def test_the_issue_967_eval_keys_are_accepted(self) -> None:
        request = ExecuteWorkflowRequest.model_validate(
            {"tags": ["eval:planning-2026-08", "variant:sonnet-early"]}
        )
        assert list(request.tags) == ["eval:planning-2026-08", "variant:sonnet-early"]

    def test_an_invalid_request_tag_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="has space"):
            ExecuteWorkflowRequest.model_validate({"tags": ["has space"]})

    @pytest.mark.asyncio
    async def test_the_endpoint_hands_request_tags_to_execute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import syn_api._wiring_admission as wiring
        from syn_api.routes.executions import commands

        async def _noop_connect() -> None:
            return None

        execution = _CapturingExecute()
        monkeypatch.setattr(
            wiring,
            "_admission_gate_singleton",
            AdmissionGate(InMemoryMaintenanceAdapter()),
            raising=False,
        )
        monkeypatch.setattr(commands, "ensure_connected", _noop_connect)
        monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
        monkeypatch.setattr(commands, "execute", execution)

        tasks = BackgroundTasks()
        request = ExecuteWorkflowRequest(
            repos=["https://github.com/syntropic137/syntropic137"],
            tags=TagSet(["eval:planning-2026-08"]),
        )
        await commands.execute_workflow_endpoint(WORKFLOW_ID, request, tasks)
        await tasks()

        assert execution.tags == [TagSet(["eval:planning-2026-08"])]

    @pytest.mark.asyncio
    async def test_execute_puts_them_on_the_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from syn_api import _wiring
        from syn_api.routes.executions import commands

        await _serve(monkeypatch)

        async def _noop_connect() -> None:
            return None

        class _NoWorkflowDetail:
            async def get_by_id(self, _workflow_id: str) -> None:
                return None

        class _Manager:
            workflow_detail = _NoWorkflowDetail()

        handler = _CapturingHandler()

        async def _handler() -> _CapturingHandler:
            return handler

        monkeypatch.setattr(commands, "ensure_connected", _noop_connect)
        monkeypatch.setattr(commands, "get_projection_mgr", _Manager)
        monkeypatch.setattr(_wiring, "get_execute_workflow_handler", _handler)

        await commands.execute(WORKFLOW_ID, tags=TagSet(["eval:planning-2026-08"]))

        assert [list(c.tags) for c in handler.commands] == [["eval:planning-2026-08"]]
