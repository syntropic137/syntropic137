"""A refused PR comment beside a finished deliverable is a completed phase.

THE INCIDENT. A review canary wrote its review to `artifacts/output/`, was then
refused the PR comment (403), and - because `success` was the only word it had
for both facts - reported `success: false`. The phase failed on its own report,
and 17 runs with finished reviews on disk were recorded as failures.

WHAT THESE DRIVE. The text an agent emits, through the real `VerdictReader`,
the real processor loop and the real aggregate, to the events the store keeps.
`side_effects` is the agent's word about its write-backs; it must reach the
record and must never decide whether the phase completes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.workspace_backends.memory import MemoryEventStreamAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
    CompletePhaseCommand,
    StartExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    SideEffectStatus,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
    VerdictStatus,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
    WorkflowExecutionProcessor,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.workspace_prompt import (
    render_workspace_prompt,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler
from syn_domain.testing.fake_session_repository import FakeSessionRepository

from .test_processor_smoke import (
    FakeArtifactRepository,
    FakeExecutionRepository,
    _make_processor,
    _noop_command_builder,
    _noop_prompt_builder,
    _one_phase_workflow,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationHandle,
    )

pytestmark = pytest.mark.unit

DENIED_BESIDE_A_DELIVERABLE = (
    'TASK_RESULT: {"success": true, "side_effects": "denied", '
    '"comments": "Review written; gh pr comment refused: 403 Resource not accessible"}\n'
    "TASK_RESULT_END"
)


class _RecordingRepository(FakeExecutionRepository):
    """The smoke repository, keeping every event it was asked to persist."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[object] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(aggregate.get_uncommitted_events())
        await super().save(aggregate)


def _payloads_of(repo: _RecordingRepository, kind: type) -> list[object]:
    out: list[object] = []
    for envelope in repo.events:
        payload = getattr(envelope, "event", envelope)
        if isinstance(payload, kind):
            out.append(payload)
    return out


async def _run(says: str, execution_id: str) -> tuple[str, list[PhaseCompletedEvent]]:
    repo = _RecordingRepository()
    result = await _make_processor(
        FakeAgentExecutionHandler.success(says=says), execution_repository=repo
    ).run(
        workflow_id="wf-side-effects",
        workflow_name="A review whose comment was refused",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id=execution_id,
    )
    completed = [
        e for e in _payloads_of(repo, PhaseCompletedEvent) if isinstance(e, PhaseCompletedEvent)
    ]
    return result.status, completed


class TestTheRunCompletesAndSaysWhatWasRefused:
    async def test_a_denied_write_back_completes_the_phase(self) -> None:
        status, _ = await _run(DENIED_BESIDE_A_DELIVERABLE, "exec-se-complete")

        assert status == "completed", "a refused PR comment failed a finished deliverable"

    async def test_the_refusal_reaches_the_recorded_phase(self) -> None:
        _, completed = await _run(DENIED_BESIDE_A_DELIVERABLE, "exec-se-recorded")

        assert [e.reported_side_effects for e in completed] == [SideEffectStatus.DENIED]

    async def test_side_effects_cannot_rescue_a_reported_failure(self) -> None:
        """The word is beside `success`, never above it."""
        says = (
            'TASK_RESULT: {"success": false, "side_effects": "succeeded", '
            '"comments": "the deliverable could not be produced"}\nTASK_RESULT_END'
        )
        status, completed = await _run(says, "exec-se-no-rescue")

        assert status == "failed"
        assert completed == []

    async def test_an_unknown_word_costs_the_word_not_the_run(self) -> None:
        says = (
            'TASK_RESULT: {"success": true, "side_effects": "kinda", '
            '"comments": "done"}\nTASK_RESULT_END'
        )
        status, completed = await _run(says, "exec-se-unknown")

        assert status == "completed"
        assert [e.reported_side_effects for e in completed] == [None]

    async def test_a_report_without_the_key_records_nothing(self) -> None:
        """Every phase written before the key existed reads as not reported."""
        says = 'TASK_RESULT: {"success": true, "comments": "done"}\nTASK_RESULT_END'
        _, completed = await _run(says, "exec-se-absent")

        assert [e.reported_side_effects for e in completed] == [None]


class TestTheFenceTheAgentCopies:
    @pytest.mark.parametrize("clone_repos", [True, False])
    def test_the_success_fence_copied_verbatim_reads_as_no_writes(self, clone_repos: bool) -> None:
        """The WHOLE fenced block, as an agent copies it, closing line included."""
        prompt = render_workspace_prompt(clone_repos=clone_repos)
        blocks = [
            body.strip()
            for i, body in enumerate(prompt.split("```"))
            if i % 2 == 1 and '"success": true' in body
        ]
        assert len(blocks) == 1, f"expected one success fence, got {blocks}"
        (block,) = blocks
        assert block.count("TASK_RESULT:") == 1
        assert block.count("TASK_RESULT_END") == 1

        verdict = AgentVerdict.from_agent_text(block)

        assert verdict.status is VerdictStatus.SUCCESS
        assert verdict.reported_side_effects is SideEffectStatus.NONE

    @pytest.mark.parametrize("word", [m.value for m in SideEffectStatus])
    def test_every_word_the_prompt_offers_is_read(self, word: str) -> None:
        prompt = render_workspace_prompt(clone_repos=True)
        assert f"| `{word}` |" in prompt, f"the prompt does not offer {word!r}"

        verdict = AgentVerdict.from_agent_text(
            f'TASK_RESULT: {{"success": true, "side_effects": "{word}", "comments": "x"}}\n'
            "TASK_RESULT_END"
        )

        assert verdict.reported_side_effects is SideEffectStatus(word)
        assert not verdict.refuses_completion

    def test_the_status_alias_carries_it_too(self) -> None:
        verdict = AgentVerdict.from_agent_text(
            'TASK_RESULT: {"status": "completed", "side_effects": "denied", "comments": "x"}\n'
            "TASK_RESULT_END"
        )

        assert verdict.status is VerdictStatus.SUCCESS
        assert verdict.reported_side_effects is SideEffectStatus.DENIED


def _started(execution_id: str) -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id="wf-1",
            workflow_name="W",
            total_phases=1,
            inputs={},
        )
    )
    return aggregate


def _agent_finished(
    aggregate: WorkflowExecutionAggregate, reported: SideEffectStatus | None
) -> None:
    aggregate.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id=aggregate.id,
            phase_id="review",
            session_id="s-1",
            exit_code=0,
            last_agent_message="done",
            reported_side_effects=reported,
        )
    )


def _complete(aggregate: WorkflowExecutionAggregate) -> PhaseCompletedEvent:
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=aggregate.id,
            workflow_id="wf-1",
            phase_id="review",
            session_id="s-1",
            artifact_id="art-1",
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=1.0,
        )
    )
    last = list(aggregate.get_uncommitted_events())[-1]
    payload = getattr(last, "event", last)
    assert isinstance(payload, PhaseCompletedEvent)
    return payload


class TestTheReportSurvivesWhatHappensBetweenTheTwoItems:
    def test_a_process_that_never_heard_the_agent_still_records_it(self) -> None:
        """Agent completion and phase completion are separate to-do items (#1300)."""
        original = _started("exec-restart")
        _agent_finished(original, SideEffectStatus.DENIED)

        rebuilt = WorkflowExecutionAggregate()
        rebuilt.rehydrate(list(original.get_uncommitted_events()))
        rebuilt.mark_events_as_committed()

        assert _complete(rebuilt).reported_side_effects is SideEffectStatus.DENIED

    def test_a_retry_that_said_nothing_does_not_inherit_the_abandoned_report(self) -> None:
        aggregate = _started("exec-retry")
        _agent_finished(aggregate, SideEffectStatus.FAILED)
        _agent_finished(aggregate, None)

        assert _complete(aggregate).reported_side_effects is None


class TestTheExecutionReadsTheWorstPhase:
    @pytest.mark.parametrize(
        ("reported", "expected"),
        [
            ([], None),
            ([None, None], None),
            ([SideEffectStatus.NONE, SideEffectStatus.SUCCEEDED], SideEffectStatus.SUCCEEDED),
            ([SideEffectStatus.DENIED, SideEffectStatus.SUCCEEDED], SideEffectStatus.DENIED),
            ([SideEffectStatus.DENIED, None, SideEffectStatus.FAILED], SideEffectStatus.FAILED),
        ],
    )
    def test_most_severe(
        self, reported: list[SideEffectStatus | None], expected: SideEffectStatus | None
    ) -> None:
        assert SideEffectStatus.most_severe(reported) is expected


class _StreamThatSays(MemoryEventStreamAdapter):
    """A Claude stream whose only assistant turn is `text`, ending with exit 0."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    async def stream(
        self,
        handle: IsolationHandle,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
        wrapper_name: str | None = None,
    ) -> AsyncIterator[str]:
        yield json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": self._text}]}}
        )
        self._last_exit_code = 0


class TestTheRealHandlerCarriesIt:
    """The fake handler builds its own command; this pins the one production builds."""

    @pytest.mark.anyio
    async def test_the_wire_form_of_the_completed_phase_says_denied(self) -> None:
        workspace_service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
        workspace_service._event_stream = _StreamThatSays(DENIED_BESIDE_A_DELIVERABLE)  # pyright: ignore[reportPrivateUsage]
        processor = WorkflowExecutionProcessor(
            execution_repository=FakeExecutionRepository(),
            session_repository=FakeSessionRepository(),
            workspace_service=workspace_service,
            artifact_repository=FakeArtifactRepository(),
            artifact_content_storage=None,
            artifact_query=None,
            conversation_storage=None,
            observability_writer=None,
            controller=None,
            prompt_builder=_noop_prompt_builder,
            command_builder=_noop_command_builder,
            todo_projection=ExecutionTodoProjection(store=InMemoryProjectionStore()),
            agent_handler=None,
        )
        repository = processor._journal._repository  # pyright: ignore[reportPrivateUsage]
        recorded: list[object] = []
        original_save = repository.save

        async def capturing_save(aggregate: object) -> None:
            recorded.extend(e.event for e in aggregate.get_uncommitted_events())  # pyright: ignore[reportAttributeAccessIssue]
            await original_save(aggregate)

        repository.save = capturing_save  # pyright: ignore[reportAttributeAccessIssue]

        result = await processor.run(
            workflow_id="wf-se-real",
            workflow_name="Real handler, refused comment",
            phases=_one_phase_workflow(),
            inputs={},
            execution_id="exec-se-real",
        )

        wire = [
            ExecutionJournal._serialize_event(e)  # pyright: ignore[reportPrivateUsage]
            for e in recorded
            if isinstance(e, PhaseCompletedEvent)
        ]
        assert result.status == "completed"
        assert [w.get("reported_side_effects") for w in wire] == ["denied"]
