"""A codex phase may not run under a sandbox the workspace cannot provide (#1434).

Without agentic-workspace's Codex sandbox policy (an unlabeled image, a host
missing the AppArmor profile) codex exits 0 with every command failed. The
probe turns that silent no-op into a provisioning failure with a reason.

A probe that times out says the host was loaded, not that the sandbox is
missing (PC-126): it is retried once, then recorded as a transient timeout.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
    failure_account,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.codex_sandbox_probe import (
    CodexSandboxUnavailableError,
    require_codex_sandbox,
)
from syn_shared.settings import get_settings, reset_settings
from syn_shared.upstream_failure import UpstreamFailureKind

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

BWRAP = "bwrap: No permissions to create a new namespace"
TIMED_OUT = ExecutionResult(exit_code=-1, success=False, duration_ms=5.0, timed_out=True)
OK = ExecutionResult(exit_code=0, success=True, duration_ms=5.0)


@pytest.fixture
def probe_timeout(monkeypatch: pytest.MonkeyPatch):
    """A configured timeout no default could produce, so reading it is proven."""
    monkeypatch.setenv("CODEX_SANDBOX_PROBE_TIMEOUT_SECONDS", "333")
    reset_settings()
    yield 333
    monkeypatch.delenv("CODEX_SANDBOX_PROBE_TIMEOUT_SECONDS")
    reset_settings()


def _phase(provider: str, sandbox: str) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id="review",
        name="Review",
        order=1,
        prompt_template="review it",
        agent_config=AgentConfiguration(provider=provider, sandbox=sandbox),
    )


def _workspace(result: ExecutionResult) -> AsyncMock:
    workspace = AsyncMock()
    workspace.execute = AsyncMock(return_value=result)
    return workspace


async def test_a_sandbox_that_does_not_run_refuses_the_phase() -> None:
    workspace = _workspace(
        ExecutionResult(exit_code=1, success=False, duration_ms=5.0, stderr=BWRAP)
    )
    with pytest.raises(CodexSandboxUnavailableError, match=r"review.*workspace-write.*bwrap"):
        await require_codex_sandbox(workspace, _phase("codex", "workspace-write"))
    workspace.execute.assert_awaited_once_with(
        ["codex", "sandbox", "-c", 'sandbox_mode="workspace-write"', "--", "true"],
        timeout_seconds=get_settings().codex_sandbox_probe_timeout_seconds,
        working_directory="/workspace",
    )


async def test_one_timed_out_probe_is_retried_with_the_configured_timeout(
    probe_timeout: int,
) -> None:
    workspace = AsyncMock()
    workspace.execute = AsyncMock(side_effect=[TIMED_OUT, OK])

    await require_codex_sandbox(workspace, _phase("codex", "workspace-write"))

    assert [c.kwargs["timeout_seconds"] for c in workspace.execute.await_args_list] == [
        probe_timeout,
        probe_timeout,
    ]


async def test_a_second_timeout_is_transient_not_a_missing_sandbox(probe_timeout: int) -> None:
    workspace = AsyncMock()
    workspace.execute = AsyncMock(side_effect=[TIMED_OUT, TIMED_OUT, OK])

    with pytest.raises(ProvisionStepTimeoutError, match=r"codex_sandbox_probe.*333s") as raised:
        await require_codex_sandbox(workspace, _phase("codex", "workspace-write"))

    assert workspace.execute.await_count == 2
    assert raised.value.step is ProvisionStep.CODEX_SANDBOX_PROBE
    assert failure_account(raised.value).upstream is UpstreamFailureKind.UNAVAILABLE


async def test_a_refusal_after_a_timeout_still_blames_the_sandbox() -> None:
    workspace = AsyncMock()
    workspace.execute = AsyncMock(
        side_effect=[
            TIMED_OUT,
            ExecutionResult(exit_code=1, success=False, duration_ms=5.0, stderr=BWRAP),
        ]
    )

    with pytest.raises(CodexSandboxUnavailableError, match="bwrap"):
        await require_codex_sandbox(workspace, _phase("codex", "workspace-write"))


async def test_a_sandbox_that_runs_lets_the_phase_proceed() -> None:
    workspace = _workspace(ExecutionResult(exit_code=0, success=True, duration_ms=5.0))
    await require_codex_sandbox(workspace, _phase("codex", "workspace-write"))
    workspace.execute.assert_awaited_once()


@pytest.mark.parametrize(
    ("provider", "sandbox"), [("codex", "full-access"), ("claude", "workspace-write")]
)
async def test_no_probe_when_codex_will_not_sandbox(provider: str, sandbox: str) -> None:
    """full-access uses no codex sandbox, and claude ignores the field."""
    workspace = _workspace(ExecutionResult(exit_code=1, success=False, duration_ms=5.0))
    await require_codex_sandbox(workspace, _phase(provider, sandbox))
    workspace.execute.assert_not_awaited()


async def test_provisioning_runs_the_probe_and_refuses_the_phase() -> None:
    """Wiring: the real provision handler calls the probe before the agent runs."""
    from unittest.mock import MagicMock, patch

    from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
    from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
        WorkspaceProvisionHandler,
    )

    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()
    workspace.workspace_id = "ws-test"
    workspace.execute = AsyncMock(
        return_value=ExecutionResult(exit_code=1, success=False, duration_ms=5.0, stderr=BWRAP)
    )
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    service = MagicMock()
    service.create_workspace.return_value = workspace_cm

    async def _prompt(*_args: object, **_kwargs: object) -> str:
        return "review it"

    handler = WorkspaceProvisionHandler(
        workspace_service=service,
        prompt_builder=_prompt,
        command_builder=lambda _phase, prompt: ["codex", "exec", prompt],
    )
    todo = TodoItem(execution_id="exec-1", action=TodoAction.PROVISION_WORKSPACE, phase_id="review")
    with patch("syn_adapters.workspace_backends.service.SetupPhaseSecrets") as secrets:
        secrets.create = AsyncMock(return_value=MagicMock())
        with pytest.raises(CodexSandboxUnavailableError):
            await handler.handle(
                todo=todo,
                phase=_phase("codex", "workspace-write"),
                workflow_id="wf-1",
                session_id="sess-1",
                repos=[],
            )
