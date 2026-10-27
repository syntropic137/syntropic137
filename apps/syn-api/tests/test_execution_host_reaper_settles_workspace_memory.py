"""The ExecutionHost's reaper is the one that frees leaked workspace memory (okrs-51p.30).

Through the real `start_execution_host`: a settling reaper that exists but is
never handed to the host would leave every unit test green and leaked memory
charged forever.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.execution_host.ledger_settling_reaper import LedgerSettlingReaper
from syn_api._wiring_workspace_memory import get_workspace_memory_ledger
from syn_api.services import execution_host_runner as runner
from syn_domain.contexts.orchestration.ports import IsolationLevel
from syn_shared.settings import reset_settings

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


class _Reaper:
    def scope(self) -> str:
        return "engine-under-test"

    def provider(self) -> str:
        return "docker"

    def isolation(self) -> IsolationLevel:
        return IsolationLevel.CONTAINER

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        return True


async def test_the_host_reaps_through_the_ledger_settling_reaper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = MagicMock()
    executor.join = AsyncMock()
    executor.leave = AsyncMock()
    executor.run_until_drained = AsyncMock()
    built = MagicMock(return_value=executor)
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(runner, "get_execution_processor", AsyncMock())
    monkeypatch.setattr(runner, "get_workflow_execution_repository", MagicMock())
    monkeypatch.setattr(runner, "get_execution_event_stream", MagicMock())
    monkeypatch.setattr(runner, "ExecutionHost", built)
    monkeypatch.setattr(runner, "reap_unlabelled_if_alone", AsyncMock())
    monkeypatch.setattr(runner, "DockerDeadHostReaper", _Reaper)
    reset_settings()
    try:
        await runner.start_execution_host()
    finally:
        await runner.stop_execution_host()
        reset_settings()

    reaper = built.call_args.kwargs["reaper"]
    assert isinstance(reaper, LedgerSettlingReaper)
    assert reaper._ledger is get_workspace_memory_ledger()
