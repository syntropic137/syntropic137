"""A resume's workspaces are checked out at the commits its parent recorded (#1458).

#1457 recorded the commit each repository was at when an execution started, and
a resume copies those from its parent. Nothing read them: every phase of every
run cloned the default branch's head, so a resume started after `main` moved ran
its remaining phases on code its inherited phases never saw.

These drive the whole chain a pinned commit has to survive, and assert on the
bash the workspace is handed to run:

    parent's start event, stored as JSON and read back
      -> `resume_start_command` -> the child's own start event
      -> `StartPins.checkout_commits` on the child aggregate
      -> `PhaseWorkspace.provision` -> `WorkspaceProvisionHandler`
      -> `SetupPhaseSecrets.create` -> `build_setup_script`
      -> `.setup/setup.sh` in the workspace

Nothing on that chain is a double. The workspace is the in-memory backend, which
stores the script it is given and runs nothing; the agents are doubles that read
that script back out of their own workspace; the GitHub App client is faked so
a token can be "minted" for the repository. A hop that dropped the commit - a
constructor that did not pass it, a serializer that omitted it - turns these red.

What the script then DOES with the commit, against a real git, is pinned beside
it in `syn_adapters/.../test_1458_pinned_checkout_runs_against_git.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    StreamAlreadyExistsError,
    resolve_event_type,
)
from pydantic import ValidationError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.service import (
    PINNED_COMMIT_UNREACHABLE_EXIT_CODE,
    WorkspaceBackend,
    WorkspaceService,
)
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import ArtifactCreatedEvent
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ResumeExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    PinnedCommitUnreachableError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume import StartResumeHandler
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler
from syn_domain.testing.fake_session_repository import FakeSessionRepository
from syn_shared.agents import AgentRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Collection

    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.contexts.orchestration import AgentExecutionResult
    from syn_domain.contexts.orchestration.slices.execute_workflow.agent_launch_observation import (
        AgentLaunchObserver,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
        ObservabilityCollector,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import Runner

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

PARENT = "exec-1458-parent"
CHILD = "exec-1458-child"
WORKFLOW = "wf-1458"
PHASE_IDS = ("research", "plan", "implement")

REPO = "syntropic137/pinned-repo"
DEST = "/workspace/repos/pinned-repo"
#: The commit the parent recorded. A value nothing else in the system could
#: produce, so finding it in a child's setup script can only mean it travelled
#: from the parent's start event.
PINNED = "5e1f0c3a9b2d47e68f01a2b3c4d5e6f708192a3b"


def _phase(phase_id: str, order: int) -> ExecutablePhase:
    return ExecutablePhase(
        phase_id=phase_id,
        name=phase_id.title(),
        order=order,
        agent_config=AgentConfiguration(),
        prompt_template=f"{phase_id} as pinned",
        output_artifact_types=(),
        timeout_seconds=1800,
    )


class _Executions:
    """Execution streams, read back from the JSON they were written as.

    `get_by_id` rehydrates from the stored payloads, the way the event store
    hands a stream back (ADR-023): so the parent the resume is built from has
    been through the serializer, which is a hop `source_commits` could be lost at.
    """

    def __init__(self) -> None:
        self.artifacts = _ProjectedArtifacts()
        self.live: dict[str, WorkflowExecutionAggregate] = {}
        self.written: dict[str, list[tuple[EventMetadata, str]]] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.written.setdefault(aggregate.id or "", []).extend(
            (
                e.metadata.model_copy(update={"event_type": e.event.event_type}),
                json.dumps(e.event.model_dump(mode="json")),
            )
            for e in aggregate.get_uncommitted_events()
        )
        self.live[aggregate.id or ""] = aggregate
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self.live:
            raise StreamAlreadyExistsError(aggregate.id or "", 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        if aggregate_id not in self.written:
            return None
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(
            [
                EventEnvelope(event=_as_stored(metadata, payload), metadata=metadata)
                for metadata, payload in self.written[aggregate_id]
            ]
        )
        return fresh


class _ProjectedArtifacts:
    """The artifact repository, with the real list projection subscribed to it.

    The resume reads the parent's deliverables back through this to hand them
    to the child, as `test_inherited_files_reach_the_resumed_phase` does.
    """

    def __init__(self) -> None:
        self.projection = ArtifactListProjection(InMemoryProjectionStore())

    async def save(self, aggregate: ArtifactAggregate) -> None:
        for envelope in aggregate.get_uncommitted_events():
            if isinstance(envelope.event, ArtifactCreatedEvent):
                await self.projection.on_artifact_created(envelope.event.model_dump(mode="json"))
        aggregate.mark_events_as_committed()

    async def get_by_id(self, aggregate_id: str) -> None:
        del aggregate_id


def _as_stored(metadata: EventMetadata, payload: str) -> DomainEvent:
    """An event as the gRPC store deserialises it (`_proto_to_envelope`)."""
    event_type = metadata.event_type or ""
    concrete = resolve_event_type(event_type)
    if concrete is not None:
        try:
            return concrete.model_validate_json(payload)
        except ValidationError:
            pass
    return GenericDomainEvent(event_type=event_type, **json.loads(payload))


@dataclass
class _ReadsItsSetup:
    """An agent that first reads the setup script its workspace was given.

    The in-memory backend keeps every file injected into a workspace and runs
    no command, so `.setup/setup.sh` is still there to read: the exact bash a
    container would have run before this agent started.
    """

    then: FakeAgentExecutionHandler
    scripts: dict[str, str] = field(default_factory=dict)

    async def handle(
        self,
        todo: TodoItem,
        workspace: ManagedWorkspace,
        agent_env: dict[str, str],
        claude_cmd: list[str],
        session_id: str,
        agent_model: str | None,
        timeout_seconds: int,
        collector: ObservabilityCollector | None = None,
        runner: Runner = AgentRunner.CLAUDE,
        on_launch: AgentLaunchObserver | None = None,
    ) -> AgentExecutionResult:
        ((_, script),) = await workspace.collect_files([".setup/setup.sh"])
        self.scripts[todo.phase_id or ""] = script.decode()
        return await self.then.handle(
            todo,
            workspace,
            agent_env,
            claude_cmd,
            session_id,
            agent_model,
            timeout_seconds,
            collector,
            runner,
            on_launch,
        )


class _FakeGitHubClient:
    """Resolves every repository to one installation and mints a token for it."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FakeGitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_installation_for_repo(self, full_name: str) -> str:
        del full_name
        return "inst-1458"

    async def mint_agent_token(
        self, installation_id: str, *, repositories: Collection[str] | None = None
    ) -> _Minted:
        del installation_id, repositories
        return _Minted("ghs_1458")

    async def revoke_installation_token(self, token: str) -> None:
        del token

    async def close(self) -> None:
        return None


@dataclass(frozen=True)
class _Minted:
    token: str
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(hours=1))


@pytest.fixture(autouse=True)
def _github_app() -> AsyncIterator[None]:
    settings = MagicMock()
    settings.is_configured = True
    settings.bot_name = "syn-bot"
    settings.bot_email = "bot@example.com"
    with (
        patch("syn_adapters.github.GitHubAppClient", _FakeGitHubClient),
        patch("syn_shared.settings.github.GitHubAppSettings", return_value=settings),
        patch(
            "syn_adapters.github.client_endpoints.get_installation_for_repo",
            AsyncMock(return_value="inst-1458"),
        ),
    ):
        yield


async def _prompt(
    phase: ExecutablePhase,
    execution_id: str,
    workflow_id: str,
    repo_url: str | None,
    phase_outputs: dict[str, str],
    inputs: object,
) -> str:
    del execution_id, workflow_id, repo_url, phase_outputs, inputs
    return phase.prompt_template


def _command(phase: ExecutablePhase, prompt: str) -> list[str]:
    del phase
    return ["echo", prompt]


def _processor(executions: _Executions, agent: _ReadsItsSetup) -> WorkflowExecutionProcessor:
    return WorkflowExecutionProcessor(
        execution_repository=executions,
        session_repository=FakeSessionRepository(),
        workspace_service=WorkspaceService.create(backend=WorkspaceBackend.MEMORY),
        artifact_repository=executions.artifacts,
        artifact_content_storage=None,
        artifact_query=ArtifactQueryService(executions.artifacts.projection),
        conversation_storage=None,
        observability_writer=None,
        controller=None,
        prompt_builder=_prompt,
        command_builder=_command,
        todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
        agent_handler=agent,
    )


async def _parent_failed_in_plan(executions: _Executions, sha: str | None) -> _ReadsItsSetup:
    """A fresh run that recorded ``sha`` for REPO, completed research and failed in plan."""
    agent = _ReadsItsSetup(
        FakeAgentExecutionHandler.scripted(
            FakeAgentExecutionHandler.success(produces=A_DELIVERABLE),
            FakeAgentExecutionHandler.failed(exit_code=1),
        )
    )
    result = await _processor(executions, agent).run(
        workflow_id=WORKFLOW,
        workflow_name="Resume me on my own code",
        phases=[_phase(p, i + 1) for i, p in enumerate(PHASE_IDS)],
        inputs={"task": "resume me"},
        execution_id=PARENT,
        repos=[RepositoryRef.from_slug(REPO)],
        source_commits=[SourceCommit(repository=REPO, sha=sha)],
    )
    assert result.status == "failed", result
    return agent


async def _resumed_child(executions: _Executions) -> _ReadsItsSetup:
    parent = await executions.get_by_id(PARENT)
    assert parent is not None
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=PARENT, resume_execution_id=CHILD, acknowledge_external_effects=True
        )
    )
    await executions.save(parent)

    child = _ReadsItsSetup(FakeAgentExecutionHandler.success(produces=A_DELIVERABLE))
    handler = StartResumeHandler(_processor(executions, child), executions)
    await handler.validate(PARENT)
    result = await handler.handle(PARENT)
    assert result is not None
    assert result.status == "completed", result
    return child


def _checkout_line(sha: str) -> str:
    return f"git -C {DEST} -c advice.detachedHead=false checkout --quiet --detach {sha}"


class TestAResumeIsProvisionedAtItsParentsCommit:
    async def test_every_phase_the_child_runs_checks_out_the_recorded_commit(self) -> None:
        """RED before #1458: the child's script cloned the default branch and stopped."""
        executions = _Executions()
        await _parent_failed_in_plan(executions, PINNED)

        child = await _resumed_child(executions)

        assert list(child.scripts) == ["plan", "implement"]
        for phase_id, script in child.scripts.items():
            assert _checkout_line(PINNED) in script.splitlines(), phase_id

    async def test_the_checkout_lands_between_the_clone_and_the_submodules(self) -> None:
        """Submodules follow the PINNED commit's gitlinks, not the default branch's."""
        executions = _Executions()
        await _parent_failed_in_plan(executions, PINNED)

        lines = (await _resumed_child(executions)).scripts["plan"].splitlines()

        clone = next(i for i, ln in enumerate(lines) if "git clone " in ln and DEST in ln)
        checkout = lines.index(_checkout_line(PINNED))
        submodules = next(i for i, ln in enumerate(lines) if "submodule update" in ln)
        assert clone < checkout < submodules

    async def test_the_checkout_is_guarded_by_a_refusal_naming_the_repo_and_commit(self) -> None:
        """The refusal exits with the code the provision handler classifies on."""
        executions = _Executions()
        await _parent_failed_in_plan(executions, PINNED)

        script = (await _resumed_child(executions)).scripts["plan"]

        (guard,) = [ln for ln in script.splitlines() if ln.startswith("if ! git")]
        assert f"cat-file -e {PINNED}^{{commit}}" in guard
        assert f"{REPO} cannot be provisioned at its recorded commit {PINNED}" in guard
        assert guard.endswith(f"exit {PINNED_COMMIT_UNREACHABLE_EXIT_CODE}; fi")


class TestARunThatIsNotAResumeIsUnchanged:
    async def test_the_parent_clones_the_default_branch_and_checks_out_nothing(self) -> None:
        """A fresh run records its commits too, and is NOT pinned to them."""
        executions = _Executions()
        parent = await _parent_failed_in_plan(executions, PINNED)

        assert list(parent.scripts) == ["research", "plan"]
        for phase_id, script in parent.scripts.items():
            assert f"git clone https://github.com/{REPO} {DEST}" in script, phase_id
            assert PINNED not in script, phase_id
            assert "checkout --quiet --detach" not in script, phase_id

    async def test_a_resume_whose_parent_recorded_no_commit_clones_the_default_branch(
        self,
    ) -> None:
        """`sha=None` is "nothing could resolve it": there is no commit to hold to."""
        executions = _Executions()
        await _parent_failed_in_plan(executions, None)

        child = await _resumed_child(executions)

        for phase_id, script in child.scripts.items():
            assert f"git clone https://github.com/{REPO} {DEST}" in script, phase_id
            assert "checkout --quiet --detach" not in script, phase_id


class TestAnUnreachableCommitRefusesThePhase:
    """The setup script's refusal reaches the phase as its own, typed failure."""

    @staticmethod
    async def _provision(exit_code: int, stderr: str) -> BaseException:
        workspace = MagicMock()
        workspace.run_setup_phase = AsyncMock(
            return_value=MagicMock(
                exit_code=exit_code, stderr=stderr, timed_out=False, signal_death=None
            )
        )
        workspace_cm = AsyncMock()
        workspace_cm.__aenter__ = AsyncMock(return_value=workspace)
        workspace_service = MagicMock()
        workspace_service.create_workspace.return_value = workspace_cm
        handler = WorkspaceProvisionHandler(
            workspace_service=workspace_service,
            prompt_builder=_prompt,
            command_builder=_command,
        )
        with pytest.raises(NonZeroExitError) as raised:
            await handler.handle(
                todo=TodoItem(
                    execution_id=CHILD, action=TodoAction.PROVISION_WORKSPACE, phase_id="plan"
                ),
                phase=_phase("plan", 2),
                workflow_id=WORKFLOW,
                session_id="sess-1458",
                repos=[f"https://github.com/{REPO}"],
                pinned_commits=[SourceCommit(repository=REPO, sha=PINNED)],
            )
        # The workspace the phase never got to use is torn down, not leaked.
        workspace_cm.__aexit__.assert_awaited_once()
        return raised.value

    async def test_it_is_raised_as_its_own_error_naming_the_repo_and_commit(self) -> None:
        refusal = f"ERROR: {REPO} cannot be provisioned at its recorded commit {PINNED}: ..."

        error = await self._provision(PINNED_COMMIT_UNREACHABLE_EXIT_CODE, refusal)

        assert isinstance(error, PinnedCommitUnreachableError)
        assert REPO in str(error)
        assert PINNED in str(error)
        assert "Phase 'Plan' will not be run" in str(error)

    async def test_any_other_setup_failure_is_not_mistaken_for_it(self) -> None:
        error = await self._provision(128, "fatal: could not read Username")

        assert not isinstance(error, PinnedCommitUnreachableError)


class TestTheDecisionIsTheExecutions:
    """`StartPins.checkout_commits` - which runs pin, and to what."""

    _commits: ClassVar[list[SourceCommit]] = [
        SourceCommit(repository=REPO, sha=PINNED),
        SourceCommit(repository="syntropic137/unresolved", sha=None),
    ]

    async def test_a_fresh_run_pins_nothing(self) -> None:
        executions = _Executions()
        await _parent_failed_in_plan(executions, PINNED)

        parent = await executions.get_by_id(PARENT)

        assert parent is not None
        assert parent.start_pins.source_commits == [SourceCommit(repository=REPO, sha=PINNED)]
        assert parent.start_pins.checkout_commits() == []

    async def test_a_resume_pins_what_its_parent_recorded_and_skips_the_unknown(self) -> None:
        executions = _Executions()
        await _parent_failed_in_plan(executions, PINNED)
        await _resumed_child(executions)

        child = await executions.get_by_id(CHILD)

        assert child is not None
        assert child.start_pins.checkout_commits() == [SourceCommit(repository=REPO, sha=PINNED)]
        pins = child.start_pins.model_copy(update={"source_commits": self._commits})
        assert pins.checkout_commits() == [SourceCommit(repository=REPO, sha=PINNED)]
