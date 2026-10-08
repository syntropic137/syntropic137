"""A provisioning checkout read that timed out is retried once, then is transient (PC-126).

`run_bounded` wraps every read in coreutils `timeout`, so a read cut off under
host load arrives as exit 124 with `timed_out=False` - the backend never saw a
timeout of its own. These tests produce that exit from a real `timeout` process
rather than writing the number by hand, and send it through the real `checked`
and `verify_checkout`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.checkout_verification import (
    verify_provisioned_checkout,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
    WorkspaceInspectionFailedError,
    failure_account,
)
from syn_shared.settings import reset_settings
from syn_shared.upstream_failure import UpstreamFailureKind

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        SourceCommit,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

PIN = "a" * 40
PINNED = {"syntropic137/syntropic137": PIN}


async def _cut_off_by_timeout() -> ExecutionResult:
    """What a shell returns when `timeout` killed the read: exit 124, no backend flag."""
    process = await asyncio.create_subprocess_exec("timeout", "0.05", "sleep", "5")
    exit_code = await process.wait()
    assert exit_code == 124
    return ExecutionResult(exit_code=exit_code, success=False, duration_ms=50.0)


def _workspace(timeouts: int, *, then: ExecutionResult | None = None) -> AsyncMock:
    """Reads that are cut off ``timeouts`` times, then answer with ``then`` (HEAD at the pin)."""
    answer = then or ExecutionResult(exit_code=0, success=True, duration_ms=1.0, stdout=PIN)
    remaining = [timeouts]

    async def execute(command: list[str], **_: object) -> ExecutionResult:
        if remaining[0]:
            remaining[0] -= 1
            return await _cut_off_by_timeout()
        return answer

    workspace = AsyncMock()
    workspace.execute = AsyncMock(side_effect=execute)
    return workspace


@pytest.fixture(autouse=True)
def verify_timeout(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    """A configured bound no default could produce, so reading it is proven."""
    monkeypatch.setenv("CHECKOUT_VERIFICATION_TIMEOUT_SECONDS", "77")
    reset_settings()
    yield 77
    monkeypatch.delenv("CHECKOUT_VERIFICATION_TIMEOUT_SECONDS")
    reset_settings()


async def _verify(workspace: AsyncMock) -> tuple[SourceCommit, ...]:
    return await verify_provisioned_checkout(
        workspace, PINNED, continued_branches={}, phase_name="Prepare"
    )


async def test_one_cut_off_read_is_retried_under_the_configured_bound() -> None:
    workspace = _workspace(1)

    (commit,) = await _verify(workspace)

    assert commit.sha == PIN
    assert workspace.execute.await_count == 2
    for call in workspace.execute.await_args_list:
        assert call.args[0][:3] == ["timeout", "--kill-after=5", "77"]


async def test_a_second_cut_off_read_is_a_transient_provision_failure() -> None:
    workspace = _workspace(2)

    with pytest.raises(ProvisionStepTimeoutError) as raised:
        await _verify(workspace)

    assert workspace.execute.await_count == 2
    assert raised.value.step is ProvisionStep.CHECKOUT_VERIFICATION
    assert "'Prepare'" in str(raised.value)
    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.UNAVAILABLE


async def test_a_read_that_answered_with_a_failure_is_not_retried_or_transient() -> None:
    refused = ExecutionResult(exit_code=128, success=False, duration_ms=1.0, stderr="fatal")
    workspace = _workspace(0, then=refused)

    with pytest.raises(WorkspaceInspectionFailedError) as raised:
        await _verify(workspace)

    assert not isinstance(raised.value, ProvisionStepTimeoutError)
    assert failure_account(raised.value).upstream is None
