"""The startup posture for the execution budget, and that the setting reaches it (#1557).

The hazard of high concurrency is capacity: each running execution costs the API
memory, and past its limit the kernel kills the API and every run in it (#1552).
Isolation was the old hazard (#865) and #1311 closed it, so the warning is now
about memory, measured against the limit the kernel actually enforces.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from syn_api._wiring_admission import BackgroundWorkflowDispatcher
from syn_api.services.lifecycle import _log_execution_concurrency_posture
from syn_shared.env_constants import (
    ENV_SYN_EXECUTION_MAX_CONCURRENT,
    ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES,
)
from syn_shared.settings import get_settings


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.unit
class TestConcurrencyPosture:
    def test_a_budget_that_fits_the_memory_limit_only_informs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            _log_execution_concurrency_posture(4, memory_limit_mib=512, retired_setting=None)

        assert _warnings(caplog) == []
        assert any(ENV_SYN_EXECUTION_MAX_CONCURRENT in r.getMessage() for r in caplog.records)

    def test_no_readable_limit_is_not_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            _log_execution_concurrency_posture(50, memory_limit_mib=None, retired_setting=None)

        assert _warnings(caplog) == []

    def test_the_incident_posture_warns_and_names_both_numbers(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """#1552 exactly: 8 runs against a 512MiB API."""
        with caplog.at_level(logging.WARNING):
            _log_execution_concurrency_posture(8, memory_limit_mib=512, retired_setting=None)

        (message,) = _warnings(caplog)
        assert ENV_SYN_EXECUTION_MAX_CONCURRENT in message
        assert "512MiB" in message
        assert "1552" in message

    def test_the_retired_name_is_called_out_as_ignored(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _log_execution_concurrency_posture(4, memory_limit_mib=None, retired_setting="1")

        (message,) = _warnings(caplog)
        assert ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES in message
        assert "IGNORED" in message
        assert ENV_SYN_EXECUTION_MAX_CONCURRENT in message


class _NullHandler:
    async def validate_stored_declarations(self, _wid: str) -> None:
        return None

    async def handle(self, *args: object, **kwargs: object) -> None:
        return None


@pytest.mark.unit
class TestTheDispatcherIsSafeWhenAskedForNothing:
    def test_omitting_the_budget_serialises(self) -> None:
        """A caller that says nothing gets a private budget of one, never more."""
        dispatcher = BackgroundWorkflowDispatcher(handler=_NullHandler())  # type: ignore[arg-type]

        assert dispatcher.budget.limit == 1

    @pytest.mark.asyncio
    async def test_the_second_execution_waits_for_the_first(self) -> None:
        """Serialisation BEHAVIOUR, not just the constructed limit."""
        entered = asyncio.Event()
        release = asyncio.Event()
        concurrent = 0
        peak = 0

        class BlockingHandler(_NullHandler):
            async def handle(self, *args: object, **kwargs: object) -> None:
                nonlocal concurrent, peak
                concurrent += 1
                peak = max(peak, concurrent)
                entered.set()
                await release.wait()
                concurrent -= 1

        dispatcher = BackgroundWorkflowDispatcher(handler=BlockingHandler())  # type: ignore[arg-type]

        await dispatcher.run_workflow("wf", {}, "exec-1")
        await dispatcher.run_workflow("wf", {}, "exec-2")
        await entered.wait()
        await asyncio.sleep(0)  # give the second task every chance to slip in

        assert peak == 1, "a second execution entered while the first held the slot"
        position = dispatcher.budget.position("exec-2")
        assert position is not None
        assert position.position == 1

        release.set()
        await asyncio.gather(*list(dispatcher._tasks), return_exceptions=True)

        assert peak == 1
        assert dispatcher.budget.position("exec-2") is None


@pytest.mark.unit
class TestTheConfiguredValueReachesTheDispatcher:
    @pytest.mark.asyncio
    async def test_the_setting_sizes_the_one_shared_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The factory hands the dispatcher the process budget, sized by the setting."""
        import syn_api._wiring as wiring
        import syn_api._wiring_admission as admission

        monkeypatch.setattr(
            wiring, "get_execute_workflow_handler", AsyncMock(return_value=object())
        )
        monkeypatch.setattr(admission, "_execution_budget_singleton", None)
        monkeypatch.setenv(ENV_SYN_EXECUTION_MAX_CONCURRENT, "3")
        get_settings.cache_clear()  # type: ignore[attr-defined]

        try:
            dispatcher = await wiring.get_workflow_dispatcher()
            assert dispatcher.budget.limit == 3
            assert dispatcher.budget is admission.get_execution_budget()
        finally:
            get_settings.cache_clear()  # type: ignore[attr-defined]
