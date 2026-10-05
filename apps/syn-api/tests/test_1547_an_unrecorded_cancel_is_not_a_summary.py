"""#1547: a cancel whose landed refs neither store took does not leave the API as handled.

The processor names those refs in `WorkflowExecutionResult.unrecorded_work`;
they are in process memory and nowhere else, so a restart forgets them and no
event will ever tell the PR. `execute()` used to copy only the status into an
`ExecutionSummary`, so the run read as an ordinary cancel and the background
runner, which logs only an `Err`, said nothing. Both hops are driven here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from fastapi import BackgroundTasks

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api.routes.executions.commands import ExecuteWorkflowRequest
from syn_api.types import Err, ExecutionSummary, Ok
from syn_domain.contexts._shared import AdmissionGate, AdmissionTicket
from syn_domain.contexts.orchestration import (
    ExecuteWorkflowCommand,
    QuarantinedRef,
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-1547"
EXECUTION_ID = "exec-1547-unrecorded"
_REF = QuarantinedRef(
    repository="acme/widget",
    branch="feat/thing",
    ref=f"refs/syn/lost/{EXECUTION_ID}/implement",
    commit="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    commit_count=1,
    pull_request=42,
)


class _CancellingHandler:
    """Stands in for ExecuteWorkflowHandler: the run is cancelled, its refs as given."""

    def __init__(self, unrecorded: tuple[QuarantinedRef, ...]) -> None:
        self._unrecorded = unrecorded

    async def handle(
        self, command: ExecuteWorkflowCommand, *, admitted: AdmissionTicket | None = None
    ) -> WorkflowExecutionResult:
        if admitted is not None:
            admitted.mark_visible()
        return WorkflowExecutionResult(
            workflow_id=command.aggregate_id,
            execution_id=EXECUTION_ID,
            status="cancelled",
            started_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
            unrecorded_work=self._unrecorded,
        )


class _NoWorkflowDetail:
    async def get_by_id(self, _workflow_id: str) -> None:
        return None


class _Manager:
    workflow_detail = _NoWorkflowDetail()


class _WorkflowRepo:
    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate:
        del aggregate_id
        return WorkflowTemplateAggregate()


def _serve(monkeypatch: pytest.MonkeyPatch, unrecorded: tuple[QuarantinedRef, ...]) -> None:
    import syn_api._wiring_admission as admission
    from syn_api import _wiring
    from syn_api.routes.executions import commands

    async def _noop_connect() -> None:
        return None

    async def _handler() -> _CancellingHandler:
        return _CancellingHandler(unrecorded)

    monkeypatch.setattr(
        admission,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "ensure_connected", _noop_connect)
    monkeypatch.setattr(commands, "get_projection_mgr", _Manager)
    monkeypatch.setattr(commands, "get_workflow_repo", _WorkflowRepo)
    monkeypatch.setattr(_wiring, "get_execute_workflow_handler", _handler)


@pytest.mark.asyncio
async def test_an_unrecorded_cancel_is_an_error_naming_its_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from syn_api.routes.executions import commands

    _serve(monkeypatch, (_REF,))

    result = await commands.execute(WORKFLOW_ID)

    assert isinstance(result, Err), f"an unrecorded cancel was reported as handled: {result}"
    assert _REF.ref in (result.message or "")
    assert _REF.commit in (result.message or "")


@pytest.mark.asyncio
async def test_a_recorded_cancel_is_still_a_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_api.routes.executions import commands

    _serve(monkeypatch, ())

    result = await commands.execute(WORKFLOW_ID)

    assert isinstance(result, Ok)
    assert isinstance(result.value, ExecutionSummary)
    assert result.value.status == "cancelled"


@pytest.mark.asyncio
async def test_the_background_run_logs_the_refs_an_unrecorded_cancel_holds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from syn_api.routes.executions import commands

    _serve(monkeypatch, (_REF,))
    tasks = BackgroundTasks()
    request = ExecuteWorkflowRequest(repos=["https://github.com/syntropic137/syntropic137"])

    with caplog.at_level(logging.ERROR, logger=commands.logger.name):
        await commands.execute_workflow_endpoint(WORKFLOW_ID, request, tasks)
        await tasks()

    logged = [str(getattr(r, "error", "")) for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(_REF.ref in line and _REF.commit in line for line in logged), logged
