"""#1381: the actual dispatcher must preserve Git work before its workspace exits."""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutionStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_runtime import PhaseRuntime
from syn_domain.contexts.orchestration.slices.execute_workflow.test_1381_shutdown_records_the_run_interrupted import (
    PHASE,
    QUARANTINE_REF,
    _Harness,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_unpushed_work_guard import (
    _clone_repository,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


async def test_dispatcher_shutdown_pushes_unpushed_commit_before_workspace_exit(
    tmp_path: Path,
) -> None:
    clone = _clone_repository(tmp_path)
    lost = clone.commit("shutdown_work.py", "saved before platform teardown\n")
    h = _Harness()
    # Use the actual runtime salvage, which executes Git against a bare origin.
    h.runtime.save_unpushed_work = PhaseRuntime.save_unpushed_work.__get__(h.runtime)  # type: ignore[method-assign]
    h.runtime._workspaces[PHASE] = clone.workspace  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
    exited = asyncio.Event()

    async def destroy_workspace(*_: object) -> None:
        assert clone.reachable_in_origin(lost, QUARANTINE_REF)
        assert len(h.interruptions()) == 1
        shutil.rmtree(clone.path)
        exited.set()

    cm = MagicMock()
    cm.__aexit__ = AsyncMock(side_effect=destroy_workspace)
    h.runtime._workspace_cms[PHASE] = cm  # pyright: ignore[reportPrivateUsage]
    dispatcher = BackgroundWorkflowDispatcher(handler=MagicMock())
    task = h.start()
    dispatcher._tasks.add(task)  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]
    await h.in_flight.wait()

    await dispatcher.shutdown()

    assert task.cancelled()
    assert exited.is_set()
    assert not clone.path.exists()
    assert clone.reachable_in_origin(lost, QUARANTINE_REF)
    assert h.aggregate.status is ExecutionStatus.INTERRUPTED
    (event,) = h.interruptions()
    assert QUARANTINE_REF in (event.reason or "")
