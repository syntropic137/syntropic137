"""The staged-credential guard under host load, through `run_setup_phase`'s `finally` (PC-126).

Every guard exec that times out establishes nothing, so the guard still fails
closed - no agent is launched. What changes is how the run is recorded: when
EVERY failed attempt timed out, the cause is a loaded host, and the error is a
transient `ProvisionStepTimeoutError` naming the step. A credential confirmed
present, or a removal the container refused, stays a plain fault.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service import setup_phase
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import _MAX_ATTEMPTS, run_setup_phase
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
    failure_account,
)
from syn_shared.settings import reset_settings
from syn_shared.upstream_failure import UpstreamFailureKind

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

OK = ExecutionResult(exit_code=0, success=True, duration_ms=1.0)
TIMED_OUT = ExecutionResult(exit_code=-1, success=False, duration_ms=1.0, timed_out=True)
REFUSED = ExecutionResult(exit_code=1, success=False, duration_ms=1.0, stderr="Permission denied")
ABSENT = ExecutionResult(
    exit_code=0, success=True, duration_ms=1.0, stdout="STAGED_CREDENTIAL_ABSENT"
)
PRESENT = ExecutionResult(
    exit_code=0, success=True, duration_ms=1.0, stdout="STAGED_CREDENTIAL_PRESENT"
)


class _Container:
    """Answers each kind of exec from its own script; the last answer repeats."""

    def __init__(
        self,
        *,
        setup: ExecutionResult = OK,
        removals: list[ExecutionResult],
        probes: list[ExecutionResult],
    ) -> None:
        self.setup = setup
        self.removals = removals
        self.probes = probes
        self.guard_timeouts: list[object] = []

    async def execute(self, command: list[str], **kwargs: object) -> ExecutionResult:
        joined = " ".join(command)
        if "setup.sh" in joined:
            return self.setup
        if "codex-auth.json" in joined and "STAGED_CREDENTIAL" in joined:
            self.guard_timeouts.append(kwargs.get("timeout_seconds"))
            return self.probes.pop(0) if len(self.probes) > 1 else self.probes[0]
        if "codex-auth.json" in joined and command[0] == "rm":
            self.guard_timeouts.append(kwargs.get("timeout_seconds"))
            return self.removals.pop(0) if len(self.removals) > 1 else self.removals[0]
        return OK


@pytest.fixture(autouse=True)
def guard_timeout(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """A configured bound no default could produce, so reading it is proven."""
    monkeypatch.setenv("CREDENTIAL_GUARD_EXEC_TIMEOUT_SECONDS", "23")
    reset_settings()
    with patch.object(setup_phase.asyncio, "sleep", AsyncMock()):
        yield 23
    monkeypatch.delenv("CREDENTIAL_GUARD_EXEC_TIMEOUT_SECONDS")
    reset_settings()


async def _run(container: _Container) -> ExecutionResult:
    workspace = MagicMock(spec=ManagedWorkspace)
    workspace.workspace_id = "ws-pc126"
    workspace.inject_files = AsyncMock()
    workspace.execute = AsyncMock(side_effect=container.execute)
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')
    with patch.object(setup_phase, "clear_secrets", AsyncMock()):
        return await run_setup_phase(workspace, secrets)


async def test_removal_timeouts_after_a_good_setup_are_a_named_transient_failure() -> None:
    container = _Container(removals=[TIMED_OUT], probes=[ABSENT])

    with pytest.raises(ProvisionStepTimeoutError) as raised:
        await _run(container)

    assert raised.value.step is ProvisionStep.SECRET_INJECTION
    assert "credential cleanup" in str(raised.value)
    assert "unable to remove staged codex credential" in str(raised.value)
    assert "timed out after 23s" in str(raised.value)
    assert failure_account(raised.value).upstream is UpstreamFailureKind.UNAVAILABLE
    assert set(container.guard_timeouts) == {23}


async def test_a_setup_timeout_then_removal_timeouts_keeps_the_setup_cause() -> None:
    container = _Container(setup=TIMED_OUT, removals=[TIMED_OUT], probes=[ABSENT])

    with pytest.raises(ProvisionStepTimeoutError) as raised:
        await _run(container)

    assert "the setup script itself had already failed first (timed out)" in str(raised.value)
    assert failure_account(raised.value).upstream is UpstreamFailureKind.UNAVAILABLE


async def test_recheck_timeouts_are_a_named_transient_failure() -> None:
    # First probe is the advisory one; then removal succeeds; every recheck times out.
    container = _Container(removals=[OK], probes=[ABSENT, *[TIMED_OUT] * _MAX_ATTEMPTS])

    with pytest.raises(ProvisionStepTimeoutError) as raised:
        await _run(container)

    assert "unable to confirm removal" in str(raised.value)
    assert failure_account(raised.value).upstream is UpstreamFailureKind.UNAVAILABLE


async def test_a_credential_confirmed_present_is_not_called_transient() -> None:
    container = _Container(removals=[OK], probes=[ABSENT, TIMED_OUT, PRESENT])

    with pytest.raises(RuntimeError, match="unable to confirm removal") as raised:
        await _run(container)

    assert not isinstance(raised.value, ProvisionStepTimeoutError)
    assert failure_account(raised.value).upstream is None


async def test_a_refused_removal_is_not_called_transient_even_after_a_timeout() -> None:
    container = _Container(removals=[TIMED_OUT, REFUSED], probes=[ABSENT])

    with pytest.raises(RuntimeError, match="unable to remove") as raised:
        await _run(container)

    assert not isinstance(raised.value, ProvisionStepTimeoutError)
    assert failure_account(raised.value).upstream is None


async def test_a_recheck_that_failed_without_timing_out_is_not_called_transient() -> None:
    """One probe that broke for another reason means not every look was a loaded host."""
    probes = [ABSENT, REFUSED, *[TIMED_OUT] * (_MAX_ATTEMPTS - 1)]
    container = _Container(removals=[OK], probes=probes)

    with pytest.raises(RuntimeError, match="unable to confirm removal") as raised:
        await _run(container)

    assert not isinstance(raised.value, ProvisionStepTimeoutError)
