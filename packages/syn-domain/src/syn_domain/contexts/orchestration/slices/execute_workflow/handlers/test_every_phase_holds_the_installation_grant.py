"""Every phase holds the same GitHub credential: the installation's grant, scoped by repo (#1477).

#1197 handed every phase except `open_pr` a token with `pull_requests: read`, to
stop `implement` publishing early. GitHub cannot express "may comment but may
not open a PR", so that token also refused every PR comment, through GraphQL
`addComment` and the REST issues endpoint alike (measured 2026-10-01). Phases
are ephemeral and open their own PRs, so the downgrade is gone.

These drive the real `sdlc/implement` workflow file through the real chain and
assert on the bash the workspace executes and the env the agent is handed:
- every phase mints with no permission subset, scoped to its repositories (#725);
- hosts.yml is still the ONLY route `gh` gets a credential by (#725).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api._wiring import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)
from syn_shared.env_constants import ENV_GITHUB_TOKEN

if TYPE_CHECKING:
    from collections.abc import Collection

    from syn_domain.contexts._shared.maintenance import AdmissionTicket
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        SourceCommit,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[9]
_IMPLEMENT_YAML = _REPO_ROOT / "workflows" / "sdlc" / "implement" / "workflow.yaml"
_REPO_URL = "https://github.com/syntropic137/syntropic137"

_TOKEN = "ghs_installation_grant"


class _FakeGitHubClient:
    """Records every mint, with the repositories it was scoped to."""

    mints: ClassVar[list[tuple[str, tuple[str, ...] | None]]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FakeGitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_installation_for_repo(self, full_name: str) -> str:
        del full_name
        return "inst-1"

    async def mint_agent_token(
        self,
        installation_id: str,
        *,
        repositories: Collection[str] | None = None,
    ) -> _Minted:
        type(self).mints.append(
            (installation_id, None if repositories is None else tuple(repositories))
        )
        return _Minted(_TOKEN)

    async def revoke_installation_token(self, token: str) -> None:
        del token

    async def close(self) -> None:
        return None


@dataclass(frozen=True)
class _Minted:
    token: str
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(hours=1))


async def _executable_phases() -> dict[str, ExecutablePhase]:
    """The phases production would run, through a real event round trip.

    The round trip matters: `WorkflowTemplateCreated` is what the event store
    holds, and phases come back out of it as plain dicts. A field the event
    does not carry is lost on the restart path only - green tests, and a
    publishing `implement` the next time the API restarts.
    """
    definition = WorkflowDefinition.from_file(_IMPLEMENT_YAML)
    origin = WorkflowTemplateAggregate()
    origin.create_workflow(build_command_from_definition(definition))
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event
    serialized = type(created).model_validate(created.model_dump(mode="json"))
    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(serialized)

    captured: list[ExecutablePhase] = []

    class _Processor:
        async def run(
            self,
            *,
            workflow_id: str,
            workflow_name: str,
            phases: list[ExecutablePhase],
            inputs: dict[str, str],
            execution_id: str,
            repos: list[RepositoryRef],
            admitted: AdmissionTicket | None = None,
            source_commits: list[SourceCommit] | None = None,
            tags: object = None,
            launch_eval: object = None,
        ) -> WorkflowExecutionResult:
            del workflow_name, inputs, repos, admitted
            captured.extend(phases)
            return WorkflowExecutionResult(
                workflow_id=workflow_id,
                execution_id=execution_id,
                status="completed",
                started_at=datetime.now(UTC),
            )

    class _Repo:
        async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
            return rehydrated if aggregate_id == definition.id else None

    handler = ExecuteWorkflowHandler(
        processor=_Processor(),  # type: ignore[arg-type]
        workflow_repository=_Repo(),  # type: ignore[arg-type]
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=definition.id))

    assert [p.phase_id for p in captured] == [
        "premise",
        "implement",
        "verify",
        "fix",
        "reverify",
        "open_pr",
    ], "the workflow's phase list changed; these assertions name phases by id"
    return {p.phase_id: p for p in captured}


class _Provisioned:
    def __init__(self, setup_script: str, agent_env: dict[str, str]) -> None:
        self.setup_script = setup_script
        self.agent_env = agent_env


async def _provision(phase: ExecutablePhase) -> _Provisioned:
    """Run the REAL provision handler for one phase against a fake workspace.

    Only the GitHub client is faked. `SetupPhaseSecrets.create` and the
    credential routing inside it run for real, because they are the hops under
    test - patching them would replace the thing this file exists to check.
    """
    _FakeGitHubClient.mints = []

    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1197"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()

    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_agent_command,
    )
    todo = TodoItem(
        execution_id="exec-1197",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id=phase.phase_id,
    )

    settings = MagicMock()
    settings.is_configured = True
    settings.bot_name = "syn-bot"
    settings.bot_email = "bot@example.com"

    with (
        patch("syn_adapters.github.GitHubAppClient", _FakeGitHubClient),
        patch("syn_shared.settings.github.GitHubAppSettings", return_value=settings),
        patch(
            "syn_adapters.github.client_endpoints.get_installation_for_repo",
            AsyncMock(return_value="inst-1"),
        ),
    ):
        result = await handler.handle(
            todo=todo,
            phase=phase,
            workflow_id="sdlc-implement-v1",
            session_id=f"sess-{phase.phase_id}",
            repos=[_REPO_URL],
            artifacts=None,
            completed_phase_ids=[],
        )

    (secrets,) = workspace.run_setup_phase.call_args.args
    return _Provisioned(secrets.build_setup_script(), dict(result.agent_env))


_ALL_PHASES = ["premise", "implement", "verify", "fix", "reverify", "open_pr"]


class TestEveryPhaseHoldsTheInstallationGrant:
    @pytest.mark.parametrize("phase_id", _ALL_PHASES)
    async def test_every_phase_gets_the_credential_gh_uses(self, phase_id: str) -> None:
        """hosts.yml carries the token, so `gh pr comment` and `gh pr create` both work."""
        provisioned = await _provision((await _executable_phases())[phase_id])

        assert f"oauth_token: {_TOKEN}" in provisioned.setup_script

    @pytest.mark.parametrize("phase_id", _ALL_PHASES)
    async def test_every_mint_is_scoped_to_the_phase_repository(self, phase_id: str) -> None:
        """WHAT is the installation's grant; WHERE is still the provisioned repo (#725)."""
        await _provision((await _executable_phases())[phase_id])

        assert _FakeGitHubClient.mints, "no token was minted at all"
        assert all(repos == ("syntropic137",) for _, repos in _FakeGitHubClient.mints)

    async def test_hosts_yml_is_still_the_only_route(self) -> None:
        """`gh` prefers $GITHUB_TOKEN; an env var cannot be renewed, so there is none (#725)."""
        provisioned = await _provision((await _executable_phases())["implement"])

        assert ENV_GITHUB_TOKEN not in provisioned.agent_env
