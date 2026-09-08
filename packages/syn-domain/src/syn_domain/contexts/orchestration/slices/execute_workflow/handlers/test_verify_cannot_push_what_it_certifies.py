"""`can_push: false` survives every hop from the YAML to the mint call (#1161).

WHAT WAS WRONG. The `verify` phase of `sdlc-implement-v1` implemented and
pushed the change it then certified, on exec-dff4ff410bb1, exec-de6c57f57984
and exec-b681ba61c9b7. Its prompt forbids this and each of those runs declared
the commit in its own report, so the prompt was read and the phase acted
anyway. A gate that asks nicely is not a gate.

WHY THIS FILE EXISTS SEPARATELY FROM THE TESTS BESIDE `client_token`. Those
pin the HTTP request. This one pins the CHAIN, because that is where a value
of this shape dies: `workflow.yaml` -> `PhaseYamlDefinition` -> a serialized
`WorkflowTemplateCreated` event -> `PhaseDefinition` -> `ExecutablePhase` ->
`WorkspaceProvisionHandler` -> `SetupPhaseSecrets` -> the access-tokens POST.
Seven hops, each a constructor that can drop a field while both ends still
look correct.

That is not hypothetical here. Written first, this file's assertions stopped
at `SetupPhaseSecrets.create`, and deleting `can_push=phase.can_push` from
BOTH `ExecuteWorkflowHandler` and `WorkspaceProvisionHandler` left every test
in this repository passing - a verify phase with full push access and a
workflow file that says otherwise. So the assertion is on the scope the GitHub
client is actually asked for, driven from the real file on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
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
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = pytest.mark.unit

#: Resolved from this file, not the process cwd, so moving a workflow fails
#: loudly here instead of silently skipping.
_REPO_ROOT = Path(__file__).resolve().parents[9]
_WORKFLOWS = _REPO_ROOT / "workflows"

_REPO_URL = "https://github.com/syntropic137/syntropic137"


class _CapturingProcessor:
    """Reads back the `ExecutablePhase` objects the real handler built."""

    def __init__(self) -> None:
        self.phases: list[ExecutablePhase] = []

    async def run(
        self,
        *,
        workflow_id: str,
        workflow_name: str,
        phases: list[ExecutablePhase],
        inputs: dict[str, str],
        execution_id: str,
        repos: list[RepositoryRef],
    ) -> WorkflowExecutionResult:
        del workflow_name, inputs, repos
        self.phases = list(phases)
        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            execution_id=execution_id,
            status="completed",
            started_at=datetime.now(UTC),
        )


class _WorkflowRepositoryStub:
    def __init__(self, aggregate: WorkflowTemplateAggregate, workflow_id: str) -> None:
        self._aggregate = aggregate
        self._workflow_id = workflow_id

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self._aggregate if aggregate_id == self._workflow_id else None


async def _executable_phases(workflow: str) -> dict[str, ExecutablePhase]:
    """The phases production would run, keyed by id, after an event round trip.

    The round trip is the point. `WorkflowTemplateCreated` is what the event
    store holds, and phases come back out of it as plain dicts fed to
    `PhaseDefinition(**item)`, so a field the event does not carry is lost
    silently on the restart path only - green tests, and a verify phase that
    can push again the next time the API restarts.
    """
    definition = WorkflowDefinition.from_file(_WORKFLOWS / workflow / "workflow.yaml")
    origin = WorkflowTemplateAggregate()
    origin.create_workflow(build_command_from_definition(definition))
    (envelope,) = origin.get_uncommitted_events()

    # Through JSON, not a copy: `model_dump(mode="json")` is what the store
    # persists, so this is the shape rehydration really sees.
    created = envelope.event
    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(type(created).model_validate(created.model_dump(mode="json")))

    processor = _CapturingProcessor()
    handler = ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_WorkflowRepositoryStub(rehydrated, definition.id),
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=definition.id))
    return {p.phase_id: p for p in processor.phases}


async def _read_only_token_requested(phase: ExecutablePhase) -> bool:
    """Provision one phase for real and report the scope GitHub was asked for.

    `SetupPhaseSecrets.create` and `_resolve_github_auth` both run unpatched -
    only the App client and its settings are doubles. Patching either would
    replace the exact code this change alters, which is how a chain test ends
    up asserting on its own fixture.
    """
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1161"
    workspace.run_setup_phase = AsyncMock(return_value=MagicMock(exit_code=0))
    workspace.inject_files = AsyncMock()

    workspace_cm = AsyncMock()
    workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
    workspace_service = MagicMock()
    workspace_service.create_workspace.return_value = workspace_cm

    app_client = MagicMock()
    app_client.get_installation_for_repo = AsyncMock(return_value="12345")
    app_client.get_installation_token = AsyncMock(return_value="ghs_x")

    app_settings = MagicMock()
    app_settings.is_configured = True
    app_settings.bot_name = "syntropic137-swe-mini[bot]"
    app_settings.bot_email = "bot@example.com"

    handler = WorkspaceProvisionHandler(
        workspace_service=workspace_service,
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_agent_command,
    )

    with (
        patch("syn_adapters.github.GitHubAppClient", return_value=app_client),
        patch("syn_shared.settings.github.GitHubAppSettings", return_value=app_settings),
        patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers."
            "WorkspaceProvisionHandler._resolve_github_app_token",
            AsyncMock(return_value="tok-a"),
        ),
    ):
        await handler.handle(
            todo=TodoItem(
                execution_id="exec-1161",
                action=TodoAction.PROVISION_WORKSPACE,
                phase_id=phase.phase_id,
            ),
            phase=phase,
            workflow_id="wf-1161",
            session_id=f"sess-{phase.phase_id}",
            repos=[_REPO_URL],
            artifacts=ArtifactCollector(AsyncMock(), AsyncMock(), None),
            completed_phase_ids=[],
            phase_outputs=PhaseOutputCache(primary={}),
        )

    app_client.get_installation_token.assert_awaited_once()
    return bool(app_client.get_installation_token.await_args.kwargs["read_only"])


class TestTheDeclarationReachesTheCredential:
    """From `workflow.yaml` on disk to the scope of the token that is minted."""

    @pytest.mark.parametrize(
        ("workflow", "phase_id"),
        [
            ("sdlc/implement", "verify"),
            ("sdlc/pr-review", "investigate"),
            ("sdlc/pr-review", "verify"),
            # The bake-off workflows are clones of sdlc-implement-v1 with one
            # model swapped, so the defect was in four files, not one.
            ("custom/bake-haiku", "verify"),
            ("custom/bake-opus", "verify"),
            ("custom/bake-sonnet", "verify"),
        ],
    )
    async def test_a_phase_that_declared_no_push_is_given_a_read_only_token(
        self, workflow: str, phase_id: str
    ) -> None:
        """All three declaring phases, not just the one that was caught.

        `sdlc-pr-review-v1`'s two phases and the three bake-off clones have
        not been observed pushing, but nothing was stopping them, and a fix
        that covers only the reproduction leaves the same hole in four files
        one directory over.
        """
        phases = await _executable_phases(workflow)
        phase = phases[phase_id]

        assert phase.can_push is False, "the declaration was lost before provisioning"
        assert await _read_only_token_requested(phase) is True

    @pytest.mark.parametrize(
        ("workflow", "phase_id"),
        [
            ("sdlc/implement", "implement"),
            ("sdlc/implement", "open_pr"),
            ("sdlc/pr-review", "report"),
            ("custom/bake-opus", "implement"),
            ("custom/bake-opus", "open_pr"),
        ],
    )
    async def test_a_phase_whose_job_is_to_publish_still_gets_a_writing_token(
        self, workflow: str, phase_id: str
    ) -> None:
        """The negative control, and it is not a formality.

        `open_pr` runs `gh pr create` and `report` runs `gh pr comment`;
        publishing IS their job. The first version of this fix deleted
        `~/.git-credentials` outright, which would have disarmed both while
        looking like a tightening - the v0.28.0-beta.5 failure mode arriving
        from the other direction.
        """
        phases = await _executable_phases(workflow)
        phase = phases[phase_id]

        assert phase.can_push is True
        assert await _read_only_token_requested(phase) is False
