"""`open_pr` must be provisioned without a checkout, and still able to refuse (#1187).

WHAT WAS WRONG. Provisioning was phase-blind. `WorkflowExecutionProcessor`
built one repo list from the workflow and handed it to every phase, and
`SetupPhaseSecrets` cloned whatever it was handed, so `open_pr` -- which reads
one artifact, checks a remote ref and calls `gh pr create` -- paid the same
clone plus recursive submodule init as `implement`, under the shortest budget
in the workflow. It timed out in roughly a third of runs.

WHY THIS FILE DRIVES THE WHOLE CHAIN. The value starts in `workflow.yaml` and
is only useful at the far end, in the bash the workspace actually executes.
Between the two it crosses `PhaseYamlDefinition`, `PhaseDefinition`, a
serialized `WorkflowTemplateCreated` event, `ExecutablePhase`,
`WorkspaceProvisionHandler` and `SetupPhaseSecrets` -- six hops, each of them
a constructor or a serializer that can drop a field while both ends still look
correct. Asserting `phase.clone_repos is False` would pass with the last four
hops deleted. So the assertions here are on the SETUP SCRIPT and the ARGV,
built from the real workflow file on disk.

WHY THE REFUSAL ASSERTIONS ARE IN THE SAME FILE. The phase's value is that it
declines to open a PR when verification found a blocking defect; it has done
so correctly on real runs. Removing the clone must not remove that, and the
two things it depends on are exactly the two a provisioning change could break:
the verify artifact reaching the workspace, and the refusal instruction
reaching the agent. Neither travels with the clone, but "neither travels with
the clone" is a claim, and this is the file that has to prove it.
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

#: Resolved from this file, not the process cwd, so moving the workflow fails
#: loudly here instead of silently skipping.
_REPO_ROOT = Path(__file__).resolve().parents[9]
_IMPLEMENT_YAML = _REPO_ROOT / "workflows" / "sdlc" / "implement" / "workflow.yaml"

_REPO_URL = "https://github.com/syntropic137/syntropic137"

#: What a verify phase writes when it finds a release blocker. The point is
#: that this reaches the agent verbatim: the refusal is the agent reading THIS
#: and declining, so a test that injected a bland placeholder would prove
#: nothing about the decision it is supposed to protect.
_BLOCKING_VERIFY_REPORT = """# Verification report

**Verdict: BLOCKING DEFECT.** The migration drops the `session_id` column
before the projection has been rebuilt, so every in-flight execution loses its
attribution. Do not open a PR for this.
"""


class _CapturingProcessor:
    """Reads back the `ExecutablePhase` objects the real handler built.

    Not a shortcut around the processor -- the point is to provision the
    phases production would have provisioned, rather than ones this file
    constructed and could therefore get wrong in the same direction as the
    code under test.
    """

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


def _stored_template_after_an_event_round_trip() -> tuple[WorkflowTemplateAggregate, str]:
    """Install the real YAML, then rehydrate it from its own serialized event.

    The round trip is the reason this helper exists rather than returning the
    aggregate `create_workflow` produced. `WorkflowTemplateCreated` is what the
    event store holds, and phases come back out of it as plain dicts fed to
    `PhaseDefinition(**item)`. A field the event does not carry is therefore
    lost silently, on the restart path only -- green tests, wrong behaviour in
    production the next time the API restarts.
    """
    definition = WorkflowDefinition.from_file(_IMPLEMENT_YAML)
    command = build_command_from_definition(definition)

    origin = WorkflowTemplateAggregate()
    origin.create_workflow(command)
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event

    # Through JSON, not a copy: `model_dump(mode="json")` is what the store
    # persists, so this is the shape rehydration really sees.
    serialized = type(created).model_validate(created.model_dump(mode="json"))

    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(serialized)
    return rehydrated, definition.id


async def _executable_phases() -> dict[str, ExecutablePhase]:
    """The phases production would run, keyed by id."""
    aggregate, workflow_id = _stored_template_after_an_event_round_trip()
    processor = _CapturingProcessor()
    handler = ExecuteWorkflowHandler(
        processor=processor,  # type: ignore[arg-type]
        workflow_repository=_WorkflowRepositoryStub(aggregate, workflow_id),
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))

    assert [p.phase_id for p in processor.phases] == [
        "bootstrap",
        "implement",
        "verify",
        "open_pr",
    ], "the workflow's phase list changed; these assertions name phases by id"
    return {p.phase_id: p for p in processor.phases}


class _Provisioned:
    """Everything the workspace was actually told to do, for one phase."""

    def __init__(self, setup_script: str, injected: dict[str, bytes], argv: list[str]) -> None:
        self.setup_script = setup_script
        self.injected = injected
        self.argv = argv

    @property
    def prompt(self) -> str:
        """The prompt as the agent receives it: claude's ``-p`` argument.

        Read positionally off the flag rather than taken as the last element,
        because the tool grant is appended after it.
        """
        return self.argv[self.argv.index("-p") + 1]


async def _provision(phase: ExecutablePhase, *, completed: dict[str, str]) -> _Provisioned:
    """Run the REAL provision handler for one phase against a fake workspace.

    `SetupPhaseSecrets.create` is not patched out: only the GitHub App lookup
    inside it is, so the script under assertion is the one the real code
    builds. Patching the whole class -- which the sibling skills tests do,
    correctly, because they assert on something else -- would replace the
    exact object this change alters.
    """
    workspace = AsyncMock()
    workspace.proxy_url = "http://envoy:10000"
    workspace.workspace_id = "ws-1187"
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
        execution_id="exec-1187",
        action=TodoAction.PROVISION_WORKSPACE,
        phase_id=phase.phase_id,
    )

    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_github_auth",
            AsyncMock(return_value=({_REPO_URL: "tok-a"}, "syn-bot", "bot@example.com")),
        ),
        patch(
            "syn_domain.contexts.orchestration.slices.execute_workflow.handlers."
            "WorkspaceProvisionHandler._resolve_github_app_token",
            AsyncMock(return_value="tok-a"),
        ),
    ):
        result = await handler.handle(
            todo=todo,
            phase=phase,
            workflow_id="sdlc-implement-v1",
            session_id=f"sess-{phase.phase_id}",
            repos=[_REPO_URL],
            artifacts=ArtifactCollector(AsyncMock(), AsyncMock(), None),
            completed_phase_ids=list(completed),
            phase_outputs=PhaseOutputCache(primary=dict(completed)),
        )

    (secrets,) = workspace.run_setup_phase.call_args.args
    injected = {
        rel_path: content
        for call in workspace.inject_files.call_args_list
        for rel_path, content in call.args[0]
    }
    return _Provisioned(secrets.build_setup_script(), injected, result.claude_cmd)


class TestTheCheckoutIsGoneForOpenPrAndOnlyForOpenPr:
    """The whole chain, from the file on disk to the bash the workspace runs."""

    async def test_open_pr_setup_script_never_clones(self) -> None:
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})

        assert "git clone" not in provisioned.setup_script
        assert "submodule update" not in provisioned.setup_script
        assert "/workspace/repos" not in provisioned.setup_script

    async def test_implement_still_clones(self) -> None:
        """The negative control.

        Without it the assertion above passes just as well against a change
        that switched cloning off for every phase, which would break the two
        phases that actually edit code.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["implement"], completed={})

        assert "git clone" in provisioned.setup_script
        assert "submodule update --init --recursive" in provisioned.setup_script

    async def test_open_pr_keeps_the_github_credential_its_job_depends_on(self) -> None:
        """No clone is not the same as no GitHub.

        `gh pr create` is the entire point of the phase. The cheap way to skip
        a clone was to pass no repositories, and that would also have dropped
        hosts.yml and the per-repo credential entry -- turning a phase that
        times out sometimes into one that cannot work at all.
        """
        phases = await _executable_phases()
        provisioned = await _provision(phases["open_pr"], completed={})

        assert "~/.config/gh/hosts.yml" in provisioned.setup_script
        assert "oauth_token: tok-a" in provisioned.setup_script
        assert "syntropic137/syntropic137" in provisioned.setup_script

    async def test_no_agents_md_imports_paths_that_were_never_cloned(self) -> None:
        """The synthetic context is @-imports of files under /workspace/repos.

        Injecting it for a phase with no checkout would hand the agent a list
        of paths that do not exist. Claude skips a missing @import silently,
        so nothing would fail - it would just quietly ask for a large file
        that is not there, which is precisely the class of cost this issue is
        about.
        """
        phases = await _executable_phases()
        open_pr = await _provision(phases["open_pr"], completed={})
        implement = await _provision(phases["implement"], completed={})

        assert "AGENTS.md" not in open_pr.injected
        assert "CLAUDE.md" not in open_pr.injected
        assert b"@/workspace/repos/syntropic137/CLAUDE.md" in implement.injected["CLAUDE.md"]


class TestTheRefusalSurvivesTheChange:
    """A verify report naming a blocking defect must still stop the PR.

    Refusal is the agent's decision, and this file cannot make the agent
    decide. What it CAN pin is the two inputs that decision needs, both of
    which pass through the provisioning code this change edits: the report has
    to be in the workspace, and the instruction has to be in the prompt. If
    either is missing the agent cannot refuse for the right reason, whatever
    it happens to do.
    """

    async def test_the_blocking_verify_report_is_in_the_workspace(self) -> None:
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": _BLOCKING_VERIFY_REPORT},
        )

        verify_inputs = {
            path: body
            for path, body in provisioned.injected.items()
            if path.startswith("artifacts/input/verify")
        }
        assert verify_inputs, (
            "the phase was given no verify artifact, so it has nothing to refuse on"
        )
        assert any(b"BLOCKING DEFECT" in body for body in verify_inputs.values())

    async def test_the_refusal_instruction_reaches_the_agent(self) -> None:
        """Asserted on the ARGV, not on the prompt file.

        The prompt is read from disk, substituted, and passed to the command
        builder. Reading `open_pr.md` here would test the file; reading the
        command tests what the agent is actually launched with, which is one
        hop further along and the only one that matters.
        """
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": _BLOCKING_VERIFY_REPORT},
        )

        assert "If verification failed, or found a defect, do not open a PR." in provisioned.prompt

    async def test_the_happy_path_opens_a_pr_from_the_remote_branch_without_pushing(
        self,
    ) -> None:
        """The other side of the gate, and the reason no-clone is coherent.

        The phase is told the branch is already on origin and that it must not
        push. That instruction is what makes a workspace with no working tree
        sufficient: there is nothing to push FROM, and nothing to push. This
        asserts the instruction survives into the launched command, alongside
        the tool grant (`Bash`) the phase needs to call `gh` at all.
        """
        phases = await _executable_phases()
        provisioned = await _provision(
            phases["open_pr"],
            completed={"verify": "# Verification report\n\nVerdict: PASS. No defects.\n"},
        )

        assert "existing remote branch" in provisioned.prompt
        assert "you do not need to push anything" in provisioned.prompt
        assert "Never force push, never rebase." in provisioned.prompt
        # Comma-joined into a single `--tools` value, not one argv element per
        # tool - so this reads the grant the CLI actually parses.
        assert "Bash" in provisioned.argv[provisioned.argv.index("--tools") + 1].split(",")
