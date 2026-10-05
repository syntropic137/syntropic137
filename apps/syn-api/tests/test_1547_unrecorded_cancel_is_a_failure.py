"""#1547: a cancel whose landed refs no store took is a failure at the API boundary.

The processor reports those refs as `unrecorded_work` beside a cancelled
status. `execute()` used to copy the status into a normal `ExecutionSummary`
and drop the refs, and the background runner logs only an `Err` - so the one
outcome that no event will ever deliver to the PR vanished without a word.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_api.types import Err, Ok
from syn_domain.contexts.orchestration import QuarantinedRef
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_api.types import ExecutionSummary, Result, WorkflowError

pytestmark = pytest.mark.unit

_REF = QuarantinedRef(
    repository="acme/widget",
    branch="feat/thing",
    ref="refs/syn/lost/exec-1547/implement",
    commit="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    commit_count=1,
    pull_request=42,
)


@dataclass
class _Detail:
    name: str = "wf"


@dataclass
class _Details:
    async def get_by_id(self, workflow_id: str) -> _Detail:
        return _Detail()


@dataclass
class _Manager:
    workflow_detail: _Details = field(default_factory=_Details)


@dataclass
class _Handler:
    unrecorded: tuple[QuarantinedRef, ...]

    async def handle(self, cmd: object, admitted: object = None) -> WorkflowExecutionResult:
        return WorkflowExecutionResult(
            workflow_id="wf-1",
            execution_id="exec-1547",
            status="cancelled",
            started_at=datetime.now(UTC),
            unrecorded_work=self.unrecorded,
        )


async def _execute(
    monkeypatch: pytest.MonkeyPatch, unrecorded: tuple[QuarantinedRef, ...]
) -> Result[ExecutionSummary, WorkflowError]:
    from syn_api import _wiring
    from syn_api.routes.executions import commands

    async def _connected() -> None:
        return None

    async def _handler() -> _Handler:
        return _Handler(unrecorded)

    monkeypatch.setattr(commands, "ensure_connected", _connected)
    monkeypatch.setattr(commands, "get_projection_mgr", _Manager)
    monkeypatch.setattr(_wiring, "get_execute_workflow_handler", _handler)
    return await commands.execute(workflow_id="wf-1", execution_id="exec-1547")


@pytest.mark.asyncio
async def test_a_cancel_whose_work_no_store_took_is_an_err_naming_the_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _execute(monkeypatch, (_REF,))

    assert isinstance(result, Err), "an unrecorded cancel was reported as handled"
    assert result.message is not None
    assert _REF.ref in result.message and _REF.commit in result.message


@pytest.mark.asyncio
async def test_a_cancel_whose_work_is_on_record_is_still_a_cancelled_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _execute(monkeypatch, ())

    assert isinstance(result, Ok)
    assert result.value.status == "cancelled"
