"""The setup-failure LOG line must name which setup, too (#1236).

Same defect as the operator-facing error in ``WorkspaceProvisionHandler``: this
line said "Setup phase failed", which reads as the workflow phase named
"Prepare the workspace" rather than the ADR-024 secret-injection step that runs
inside every phase. No phase name is available at this layer, so the workspace
id carries the "which run" half.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import run_setup_phase
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)


async def _failure_log(result: ExecutionResult, caplog: pytest.LogCaptureFixture) -> str:
    workspace = MagicMock(spec=ManagedWorkspace)
    workspace.workspace_id = "ws-1236"
    workspace.inject_files = AsyncMock()
    workspace.execute = AsyncMock(return_value=result)

    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
            new=AsyncMock(),
        ),
        caplog.at_level(
            logging.ERROR, logger="syn_adapters.workspace_backends.service.setup_phase"
        ),
    ):
        await run_setup_phase(workspace, SetupPhaseSecrets.for_testing())

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, f"expected exactly one error log, got {errors}"
    return errors[0]


@pytest.mark.unit
@pytest.mark.anyio
async def test_failure_log_names_the_secret_injection_setup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = await _failure_log(
        ExecutionResult(
            exit_code=1,
            success=False,
            duration_ms=900.0,
            stderr="fatal: could not read Username for 'https://github.com'",
        ),
        caplog,
    )

    assert "Secret-injection setup failed" in message
    assert "Setup phase failed" not in message
    assert "ws-1236" in message
    assert "exit=1" in message
    assert "could not read Username" in message
