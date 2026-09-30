"""Only the publication phase may hold a token that can open a PR (#1197).

WHAT WENT WRONG. On `exec-0bac0e1ed2b2` the `implement` phase called
`gh pr create` at 02:37:40 - four minutes before it finished, fourteen before
the verifier started - and `open_pr` never ran at all. The verifier then
crashed without rendering a verdict, so PR #1193 was indistinguishable from
one that had passed. `open_pr` refuses to publish when verification finds a
blocking defect, and has done so correctly on real runs; that refusal is worth
nothing if an earlier phase can publish before the gate is consulted.

WHY THE ASSERTIONS ARE WHERE THEY ARE. The implement prompt already said "Do
not open a PR - that is the last phase's job", in those words, so a test that
checked the prompt would have passed on the run that broke. What decides the
outcome is the credential. It used to reach the agent by two independent
routes - the `gh` hosts.yml entry the setup script writes, and a
`GITHUB_TOKEN` environment variable `gh` preferred - and both had to be
scoped or the boundary was decorative. Since #725 hosts.yml is the only
route (an env var cannot be renewed), and that is asserted here too: a
second route coming back would reopen the question.

So these drive the real workflow file through the real chain and assert on the
bash the workspace executes and the env the agent is handed. `can_open_pr` is
asserted on the phase objects too, but only as a locator: it is true at the
top of six hops, any of which could drop it while both ends still look right.
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

#: Distinguishable on sight, so an assertion cannot pass on the wrong one.
_PUBLISHING_TOKEN = "ghs_may_open_pull_requests"
_SCOPED_TOKEN = "ghs_pull_requests_read_only"


class _FakeGitHubClient:
    """One fake for both credential paths, so they cannot silently diverge.

    Records every mint. `mint_agent_token` is the single place a phase's
    entitlement turns into a token, which is why both routes are made to go
    through it rather than each deciding for itself.
    """

    mints: ClassVar[list[tuple[str, bool]]] = []

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
        can_open_pr: bool,
        repositories: Collection[str] | None = None,
    ) -> _Minted:
        del repositories
        type(self).mints.append((installation_id, can_open_pr))
        return _Minted(_PUBLISHING_TOKEN if can_open_pr else _SCOPED_TOKEN)

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


class TestOnlyOpenPrCanPublish:
    """The reproduction, at every hop that could have stopped it."""

    async def test_implements_gh_credential_cannot_create_a_pull_request(self) -> None:
        """The bash the workspace actually runs, for the phase that published."""
        provisioned = await _provision((await _executable_phases())["implement"])

        assert f"oauth_token: {_SCOPED_TOKEN}" in provisioned.setup_script
        assert _PUBLISHING_TOKEN not in provisioned.setup_script

    async def test_implements_github_token_env_cannot_either(self) -> None:
        """`gh` prefers $GITHUB_TOKEN, so a token there would outrank hosts.yml (#725).

        There is none: hosts.yml is the only credential `gh` is given, so its
        scoping above is the whole of the boundary.
        """
        provisioned = await _provision((await _executable_phases())["implement"])

        assert ENV_GITHUB_TOKEN not in provisioned.agent_env

    async def test_open_pr_still_gets_the_token_its_whole_job_needs(self) -> None:
        """The negative control.

        Without it, everything above passes just as well against a change that
        took publication away from every phase - which would break the gate
        itself rather than enforce it.
        """
        provisioned = await _provision((await _executable_phases())["open_pr"])

        assert f"oauth_token: {_PUBLISHING_TOKEN}" in provisioned.setup_script
        assert _SCOPED_TOKEN not in provisioned.setup_script

    @pytest.mark.parametrize("phase_id", ["premise", "implement", "verify"])
    async def test_no_earlier_phase_asks_for_publication(self, phase_id: str) -> None:
        """Every mint this phase performs states it may not publish.

        Asserted on the mint calls rather than the returned token so that a
        second, unscoped credential path added later fails here instead of
        going unnoticed because the first one happened to be right.
        """
        await _provision((await _executable_phases())[phase_id])

        assert _FakeGitHubClient.mints, "no token was minted at all"
        assert all(not can_open_pr for _, can_open_pr in _FakeGitHubClient.mints)

    async def test_the_entitlement_survives_the_event_round_trip(self) -> None:
        """The locator assertion: six hops separate the YAML from the mint.

        `verify` runs on codex, where a tool allowlist would not have applied
        at all - which is why the entitlement rides the credential and this
        assertion covers it alongside the claude phases.
        """
        phases = await _executable_phases()

        assert [p.phase_id for p in phases.values() if p.can_open_pr] == ["open_pr"]
