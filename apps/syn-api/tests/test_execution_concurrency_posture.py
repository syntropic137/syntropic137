"""The startup posture for workflow-execution concurrency.

Concurrent executions are not isolated from each other (#865). Until that is
fixed, a deployment that has raised the limit should learn it at startup rather
than from a workflow that finished against someone else's inputs.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_api.services.lifecycle import _log_execution_concurrency_posture
from syn_shared.env_constants import ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES
from syn_shared.settings import get_settings


@pytest.mark.unit
class TestConcurrencyPosture:
    def test_the_safe_posture_says_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            _log_execution_concurrency_posture(1)

        assert not caplog.records

    @pytest.mark.parametrize("value", [2, 5, 50])
    def test_a_concurrent_posture_warns_once_and_names_the_variable(
        self, caplog: pytest.LogCaptureFixture, value: int
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _log_execution_concurrency_posture(value)

        (record,) = caplog.records
        message = record.getMessage()
        assert ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES in message
        assert str(value) in message
        assert "865" in message


@pytest.mark.unit
class TestTheDispatcherIsSafeWhenAskedForNothing:
    def test_omitting_max_concurrent_serialises(self) -> None:
        """A caller that says nothing must not get the unsafe value.

        The dispatcher's own default was 5 while the setting's was 1, so any
        construction that omitted the argument quietly reintroduced exactly the
        posture the setting exists to prevent.
        """
        dispatcher = BackgroundWorkflowDispatcher(handler=object())  # type: ignore[arg-type]

        assert dispatcher._semaphore._value == 1

    @pytest.mark.asyncio
    async def test_the_second_execution_waits_for_the_first(self) -> None:
        """Serialisation BEHAVIOUR, not just the constructed semaphore value.

        Asserting `_semaphore._value` proves the object was built with 1; it
        does not prove the semaphore is ever acquired. Removing the `async
        with` from _run_with_semaphore left that assertion green, so this
        drives two dispatches through a handler that blocks until released.
        """
        entered = asyncio.Event()
        release = asyncio.Event()
        concurrent = 0
        peak = 0

        class BlockingHandler:
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

        assert peak == 1, "a second execution entered while the first held the gate"

        release.set()
        await asyncio.gather(*list(dispatcher._tasks), return_exceptions=True)

        assert peak == 1


@pytest.mark.unit
class TestTheConfiguredValueReachesTheDispatcher:
    @pytest.mark.asyncio
    async def test_the_setting_is_what_bounds_the_dispatcher(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hardcoded value in the factory would leave every other test green.

        The factory reads the setting; nothing else asserted that it does.
        """
        import syn_api._wiring as wiring

        monkeypatch.setattr(
            wiring, "get_execute_workflow_handler", AsyncMock(return_value=object())
        )
        monkeypatch.setenv(ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES, "3")
        get_settings.cache_clear()  # type: ignore[attr-defined]

        try:
            dispatcher = await wiring.get_workflow_dispatcher()
            assert dispatcher._semaphore._value == 3
        finally:
            get_settings.cache_clear()  # type: ignore[attr-defined]
