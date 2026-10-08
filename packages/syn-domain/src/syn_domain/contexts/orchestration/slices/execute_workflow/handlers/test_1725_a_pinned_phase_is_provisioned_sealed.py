"""`isolation: pinned` has to reach the setup script, not merely be written (#1725).

The declaration lives in `workflows/evals/implement-pinned/workflow.yaml` and is
only useful in the bash the workspace runs. Between the two it crosses
`PhaseYamlDefinition`, `PhaseDefinition`, a serialized `WorkflowTemplateCreated`
event, `ExecutablePhase`, `WorkspaceProvisionHandler` and `SetupPhaseSecrets`,
and every hop defaults to STANDARD - the value a dropped field produces - so a
loss anywhere provisions the eval with the fix one `git log --all` away while
both ends still look right. The assertions are therefore on the setup script
the real handler builds from the shipped workflow file.

What the seal then DOES to a repository is proven against a real git by
`syn_adapters/.../test_1725_sealed_workspace_runs_against_git.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.setup_phase_secrets import _GitHubAuth
from syn_api._wiring_agent_command import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts.orchestration._shared.phase_isolation import PhaseIsolation
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SourceCommit,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_1308_the_declaration_survives_to_execution import (
    _executable_phases,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOWS = Path(__file__).resolve().parents[9] / "workflows"
_REPO = "syntropic137/syntropic137"
_REPO_URL = f"https://github.com/{_REPO}"
_PIN = "0123456789abcdef0123456789abcdef01234567"


async def _setup_script(phase: ExecutablePhase) -> tuple[str, object]:
    """The setup script the REAL provision handler hands the workspace, and its secrets."""
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1725"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()
    workspace.execute = AsyncMock(return_value=MagicMock(exit_code=0, stdout=""))
    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_agent_command,
    )
    module = "syn_domain.contexts.orchestration.slices.execute_workflow.handlers"
    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_github_auth",
            AsyncMock(
                return_value=_GitHubAuth(
                    repo_tokens={_REPO_URL: "tok-installation"},
                    gh_token="tok-installation",
                    author_name="syn-bot",
                    author_email="bot@example.com",
                )
            ),
        ),
        # The checkout read-back (#967) is not what this file is about, and the
        # fake workspace has no HEAD to report.
        patch(f"{module}.WorkspaceProvisionHandler.verify_checkout", AsyncMock(return_value=())),
    ):
        await handler.handle(
            todo=TodoItem(
                execution_id="exec-1725",
                action=TodoAction.PROVISION_WORKSPACE,
                phase_id=phase.phase_id,
            ),
            phase=phase,
            workflow_id="wf-1725",
            session_id=f"sess-{phase.phase_id}",
            repos=[_REPO_URL],
            artifacts=ArtifactCollector(AsyncMock(), AsyncMock(), None),
            completed_phase_ids=[],
            phase_outputs=PhaseOutputCache(primary={}),
            inputs={"task": "fix the thing"},
            pinned_commits=[SourceCommit(repository=_REPO, sha=_PIN)],
        )
    (secrets,) = workspace.run_setup_phase.await_args.args
    return secrets.build_setup_script(), secrets


async def test_the_eval_phase_is_provisioned_sealed_at_its_pin() -> None:
    phases = await _executable_phases(_WORKFLOWS / "evals/implement-pinned/workflow.yaml")
    assert phases["implement"].isolation is PhaseIsolation.PINNED

    script, _ = await _setup_script(phases["implement"])

    assert f"refs/remotes/pinned/{_PIN}" in script
    assert "git remote remove" in script
    assert "rm -f ~/.git-credentials ~/.config/gh/hosts.yml" in script
    # gh is never given the token at all, not merely given it and then denied.
    assert "oauth_token:" not in script


async def test_a_sealed_workspace_is_never_handed_its_credential_again() -> None:
    """Credential renewal re-mints from what setup recorded; a seal records nothing."""
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace

    phases = await _executable_phases(_WORKFLOWS / "evals/implement-pinned/workflow.yaml")
    _, secrets = await _setup_script(phases["implement"])
    workspace = MagicMock(spec=ManagedWorkspace)
    workspace._credential_source = None
    workspace._ledger = MagicMock()

    with patch(
        "syn_adapters.workspace_backends.service.managed_workspace._run_setup_phase",
        AsyncMock(return_value=MagicMock(exit_code=0)),
    ):
        await ManagedWorkspace.run_setup_phase(workspace, secrets)  # type: ignore[arg-type]

    assert workspace._credential_source is None
    assert await ManagedWorkspace.renew_git_credential(workspace) == ()


async def test_an_ordinary_implement_phase_keeps_its_history_and_credential() -> None:
    """The control: a phase that pushes must not be sealed by this change."""
    phases = await _executable_phases(_WORKFLOWS / "sdlc/implement/workflow.yaml")
    assert phases["implement"].isolation is PhaseIsolation.STANDARD

    script, _ = await _setup_script(phases["implement"])

    assert "git remote remove" not in script
    assert "oauth_token: tok-installation" in script
    assert "rm -f ~/.git-credentials" not in script
