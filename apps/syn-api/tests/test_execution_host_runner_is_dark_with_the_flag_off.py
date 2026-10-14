"""With the Run Queue off, no ExecutionHost starts and nothing is wired (#1310 1.5).

The flag-off path must stay main's: no processor built, no host registered.
With it on, a host starts and is cancelled cleanly on stop.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_api.services import execution_host_runner as runner

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


async def test_flag_off_starts_nothing_and_builds_no_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = AsyncMock()
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=None))
    monkeypatch.setattr(runner, "get_execution_processor", processor)
    await runner.start_execution_host()
    assert runner._host_task is None
    processor.assert_not_awaited()
    await runner.stop_execution_host()


async def test_flag_on_starts_one_host_and_stop_cancels_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def _forever() -> None:
        started.set()
        await asyncio.Event().wait()

    host = MagicMock()
    host.run_until_drained = _forever
    built = MagicMock(return_value=host)
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(runner, "get_execution_processor", AsyncMock())
    monkeypatch.setattr(runner, "get_workflow_execution_repository", MagicMock())
    monkeypatch.setattr(runner, "get_execution_event_stream", MagicMock())
    monkeypatch.setattr(runner, "ExecutionHost", built)
    await runner.start_execution_host()
    await runner.start_execution_host()  # idempotent while running
    await asyncio.wait_for(started.wait(), 1)
    assert built.call_count == 1
    task = runner._host_task
    assert task is not None
    await runner.stop_execution_host()
    assert task.cancelled()
    assert runner._host_task is None
