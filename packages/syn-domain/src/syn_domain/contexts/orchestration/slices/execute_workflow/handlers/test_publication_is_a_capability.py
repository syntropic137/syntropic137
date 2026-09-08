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
outcome is the credential, and the credential reaches the agent by two
independent routes: the `gh` hosts.yml entry the setup script writes, and the
`GITHUB_TOKEN` environment variable. `gh` prefers the env var, so BOTH have to
be scoped or the boundary is decorative - the same two-paths-must-agree lesson
#1129 drew about which installation they resolve.

So these drive the real workflow file through the real chain and assert on the
bash the workspace executes and the env the agent is handed. `can_open_pr` is
asserted on the phase objects too, but only as a locator: it is true at the
top of six hops, any of which could drop it while both ends still look right.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api._wiring import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (  # noqa: E501
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (  # noqa: E501
    WorkspaceProvisionHandler,
)
from syn_shared.env_constants import ENV_GITHUB_TOKEN

if TYPE_CHECKING:
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

    mints: list[tuple[str, bool]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FakeGitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_installation_for_repo(self, full_name: str) -> str:
        del full_name
        return "inst-1"

    async def mint_agent_token(self, installation_id: str, *, can_open_pr: bool) -> str:
        type(self).mints.append((installation_id, can_open_pr))
        return _PUBLISHING_TOKEN if can_open_pr else _SCOPED_TOKEN


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
        async def run(self, **kwargs: Any) -> Any:
            captured.extend(kwargs["phases"])
            return MagicMock(status="completed")

    class _Repo:
        async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
            return rehydrated if aggregate_id == definition.id else None

    handler = ExecuteWorkflowHandler(
        processor=_Processor(),  # type: ignore[arg-type]
        workflow_repository=_Repo(),  # type: ignore[arg-type]
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=definition.id))

    assert [p.phase_id for p in captured] == ["bootstrap", "implement", "verify", "open_pr"], (
        "the workflow's phase list changed; these assertions name phases by id"
    )
    return {p.phase_id: p for p in captured}


class _Provisioned:
    def __init__(self, setup_script: str, agent_env: dict[str, str]) -> None:
        self.setup_script = setup_script
        self.agent_env = agent_env


async def _provision(phase: ExecutablePhase) -> _Provisioned:
    """Run the REAL provision handler for one phase against a fake workspace.

    Only the GitHub client is faked. `SetupPhaseSecrets.create` and
    `_resolve_github_app_token` both run for real, because they are the two
    hops under test - patching either would replace the thing this file exists
    to check.
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
        """`gh` prefers $GITHUB_TOKEN, so scoping only hosts.yml would change nothing."""
        provisioned = await _provision((await _executable_phases())["implement"])

        assert provisioned.agent_env[ENV_GITHUB_TOKEN] == _SCOPED_TOKEN

    async def test_open_pr_still_gets_the_token_its_whole_job_needs(self) -> None:
        """The negative control.

        Without it, everything above passes just as well against a change that
        took publication away from every phase - which would break the gate
        itself rather than enforce it.
        """
        provisioned = await _provision((await _executable_phases())["open_pr"])

        assert f"oauth_token: {_PUBLISHING_TOKEN}" in provisioned.setup_script
        assert _SCOPED_TOKEN not in provisioned.setup_script

    @pytest.mark.parametrize("phase_id", ["bootstrap", "implement", "verify"])
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
