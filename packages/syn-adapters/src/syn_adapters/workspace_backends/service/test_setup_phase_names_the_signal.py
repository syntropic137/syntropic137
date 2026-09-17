"""The secret-injection path must name the signal too (#1295).

One of the three runs lost to exit ``-11`` in a single day died here, at LOW
concurrency - so this is not confined to git-in-a-workspace, and this log line
plus the credential-removal trail are what an operator has to read when it
happens. Both printed a bare negative number.

These assert the strings the logger emits and the trail the guard carries, not
the formatter underneath them.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import (
    _remove_staged_credential,
    run_setup_phase,
)
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _workspace(result: ExecutionResult) -> MagicMock:
    workspace = MagicMock(spec=ManagedWorkspace)
    workspace.workspace_id = "ws-1295"
    workspace.inject_files = AsyncMock()
    workspace.execute = AsyncMock(return_value=result)
    return workspace


async def _failure_log(result: ExecutionResult, caplog: pytest.LogCaptureFixture) -> str:
    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
            new=AsyncMock(),
        ),
        caplog.at_level(
            logging.ERROR, logger="syn_adapters.workspace_backends.service.setup_phase"
        ),
    ):
        await run_setup_phase(_workspace(result), SetupPhaseSecrets.for_testing())

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, f"expected exactly one error log, got {errors}"
    return errors[0]


async def test_a_segfaulted_setup_is_logged_as_sigsegv(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The verbatim #1295 case, with no stderr to explain it."""
    message = await _failure_log(
        ExecutionResult(exit_code=-11, success=False, duration_ms=430.0),
        caplog,
    )

    assert "exit=-11 (SIGSEGV: Segmentation fault)" in message
    assert "Secret-injection setup failed" in message


async def test_a_setup_that_never_reported_is_not_logged_as_sighup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``-1`` is the providers' "no status" sentinel, not signal 1."""
    message = await _failure_log(
        ExecutionResult(exit_code=-1, success=False, duration_ms=1.0, timed_out=True),
        caplog,
    )

    assert "SIGHUP" not in message
    assert "exit=-1 (no exit status)" in message


async def test_the_credential_removal_trail_names_the_signal() -> None:
    """The SECURITY report says which signal killed each attempt.

    This trail is the whole evidence an operator gets that a staged credential
    may still be in the container, so ``exit=-11`` three times over is the
    worst place to make them decode it.
    """
    workspace = _workspace(ExecutionResult(exit_code=-11, success=False, duration_ms=5.0))

    with patch(
        "syn_adapters.workspace_backends.service.setup_phase._wait_before_retry",
        new=AsyncMock(),
    ):
        outcome = await _remove_staged_credential(workspace)

    assert not outcome.succeeded
    assert outcome.attempts, "the trail must record the attempts it made"
    for attempt in outcome.attempts:
        assert attempt == "exit=-11 (SIGSEGV: Segmentation fault)"
