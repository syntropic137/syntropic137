"""The startup posture for workflow-execution concurrency.

Concurrent executions are not isolated from each other (#865). Until that is
fixed, a deployment that has raised the limit should learn it at startup rather
than from a workflow that finished against someone else's inputs.
"""

from __future__ import annotations

import logging

import pytest

from syn_api._wiring import BackgroundWorkflowDispatcher
from syn_api.services.lifecycle import _log_execution_concurrency_posture
from syn_shared.env_constants import ENV_SYN_POLLING_MAX_CONCURRENT_DISPATCHES


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
