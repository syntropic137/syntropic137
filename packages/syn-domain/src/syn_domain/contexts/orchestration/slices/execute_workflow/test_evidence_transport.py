"""A phase's `evidence` declaration and the forge's heads reach the command (plan §A.2, PR 5a).

Two hops the aggregate-level tests cannot see: the parse out of `TASK_RESULT`
into `AgentVerdict`, and the real `AgentExecutionHandler` copying it onto the
command it reports. Then the observer, which reads the forge host-side.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceKind
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    ContinuedBranch,
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    AgentExecutionCompletedCommand,
    RecordPhasePushCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
    DeclaredEvidence,
    ObservedHead,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import StartPins
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    SourceCommit,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EventStreamProcessor import (
    StreamResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.evidence_heads import (
    MUTATIONS_PATH,
    EvidenceHeadObserver,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler import (
    AgentExecutionHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
    VerdictStatus,
)

pytestmark = pytest.mark.unit

SLUG = "syntropic137/syntropic137"
SHA = "b" * 40
ENTRY = {
    "kind": "integration",
    "repository": SLUG,
    "branch": "feat/declared",
    "pr": 7,
    "head_sha": SHA,
    "tests": ["tests/test_x.py::test_y"],
}


def _block(**body: object) -> str:
    return f"TASK_RESULT: {json.dumps(body)}\nTASK_RESULT_END"


class TestTheParse:
    def test_a_well_formed_entry_becomes_a_request(self) -> None:
        verdict = AgentVerdict.from_agent_text(_block(success=True, evidence=[ENTRY]))

        assert verdict.status is VerdictStatus.SUCCESS
        [declared] = verdict.reported_evidence
        assert declared.request is not None
        assert declared.request.kind is EvidenceKind.INTEGRATION
        assert declared.request.head_sha == SHA

    def test_the_status_alias_reads_it_too(self) -> None:
        verdict = AgentVerdict.from_agent_text(_block(status="completed", evidence=[ENTRY]))

        assert verdict.via_status_alias
        assert [d.request for d in verdict.reported_evidence if d.request is not None]

    def test_a_malformed_entry_is_kept_as_unreadable_not_dropped(self) -> None:
        verdict = AgentVerdict.from_agent_text(
            _block(success=True, evidence=[ENTRY, {**ENTRY, "tests": []}])
        )

        assert verdict.status is VerdictStatus.SUCCESS, "a bad entry must not cost the verdict"
        assert [d.request is None for d in verdict.reported_evidence] == [False, True]
        assert verdict.reported_evidence[1].unreadable

    def test_a_string_pr_number_is_not_coerced(self) -> None:
        """Strict: `"7"` is a string, not a pull request number."""
        [declared] = DeclaredEvidence.from_reported([{**ENTRY, "pr": "7"}])

        assert declared.request is None

    def test_an_evidence_value_that_is_not_a_list_is_one_unreadable_declaration(self) -> None:
        verdict = AgentVerdict.from_agent_text(_block(success=True, evidence={"kind": "mutation"}))

        assert verdict.status is VerdictStatus.SUCCESS
        [declared] = verdict.reported_evidence
        assert declared.request is None
        assert declared.unreadable

    def test_no_evidence_key_declares_nothing(self) -> None:
        assert AgentVerdict.from_agent_text(_block(success=True)).reported_evidence == ()


@pytest.mark.anyio
async def test_the_handler_copies_the_declaration_onto_its_command() -> None:
    declared = DeclaredEvidence.from_reported([ENTRY])
    workspace = MagicMock()
    workspace.last_stream_exit_code = 0
    workspace.collect_files = AsyncMock(return_value=[])
    stream_result = StreamResult(
        line_count=3,
        interrupt_requested=False,
        interrupt_reason=None,
        verdict=AgentVerdict(VerdictStatus.SUCCESS, reported_evidence=declared),
    )
    with patch(
        "syn_domain.contexts.orchestration.slices.execute_workflow.handlers.AgentExecutionHandler.CodexStreamProcessor"
    ) as processor:
        processor.return_value.process_stream = AsyncMock(return_value=stream_result)
        result = await AgentExecutionHandler(controller=None).handle(
            todo=TodoItem(
                execution_id="exec-ev", action=TodoAction.RUN_AGENT, phase_id="implement"
            ),
            workspace=workspace,
            agent_env={},
            claude_cmd=["codex", "exec", "--json", "implement"],
            session_id="s1",
            agent_model="gpt-sol",
            timeout_seconds=3600,
            collector=AsyncMock(),
            runner="codex",
        )

    assert result.command.reported_evidence == declared


@dataclass
class _Forge:
    """Every branch exists at ``SHA`` with PR 7 open, unless named unreadable."""

    unreadable: set[str] = field(default_factory=set)
    asked: list[tuple[str, str]] = field(default_factory=list)

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        self.asked.append((repository, branch))
        if branch in self.unreadable:
            return RemoteBranchReading(repository=repository, branch=branch, readable=False)
        return RemoteBranchReading(
            repository=repository,
            branch=branch,
            readable=True,
            head_sha=SHA,
            open_pull_request=7,
        )


@dataclass
class _Tree:
    asked: list[tuple[str, str, str]] = field(default_factory=list)

    async def has_path(self, repository: str, sha: str, path: str) -> bool | None:
        self.asked.append((repository, sha, path))
        return True


def _aggregate(
    *, declared: list[object], continued: str | None = None
) -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id="exec-ev",
            workflow_id="wf",
            workflow_name="evidence",
            total_phases=1,
            inputs={},
            phase_definitions=[PhaseDefinition(phase_id="implement", name="implement", order=1)],
            source_commits=[SourceCommit(repository=SLUG, sha="c" * 40)],
        )
    )
    if continued is not None:
        # A resume's inherited branch arrives on its start pins, not as a push.
        aggregate._pins = StartPins(
            source_commits=aggregate.start_pins.source_commits,
            continued_branches=[ContinuedBranch(repository=SLUG, branch=continued, head_sha=SHA)],
        )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id="exec-ev",
            workflow_id="wf",
            phase_id="implement",
            phase_name="implement",
            phase_order=1,
        )
    )
    aggregate.record_phase_push(
        RecordPhasePushCommand(
            execution_id="exec-ev",
            phase_id="implement",
            repository="syntropic137",
            branch="feat/pushed",
            sha=SHA,
        )
    )
    aggregate.agent_execution_completed(
        AgentExecutionCompletedCommand(
            execution_id="exec-ev",
            phase_id="implement",
            session_id="s",
            reported_evidence=DeclaredEvidence.from_reported(declared),
        )
    )
    return aggregate


@pytest.mark.anyio
class TestTheObserver:
    async def test_pushed_inherited_and_declared_branches_are_each_read_once(self) -> None:
        forge = _Forge()
        aggregate = _aggregate(
            declared=[ENTRY, {**ENTRY, "branch": "feat/pushed"}], continued="feat/inherited"
        )

        heads = await EvidenceHeadObserver(forge).observe(aggregate, "implement")

        assert [h.branch for h in heads] == ["feat/pushed", "feat/inherited", "feat/declared"]
        assert all(h.repository == SLUG for h in heads), "the clone name maps to its slug"
        assert len(forge.asked) == 3

    async def test_a_readable_head_records_its_sha_pr_and_patch_presence(self) -> None:
        tree = _Tree()
        heads = await EvidenceHeadObserver(_Forge(), tree).observe(
            _aggregate(declared=[]), "implement"
        )

        assert heads == (
            ObservedHead(
                repository=SLUG,
                branch="feat/pushed",
                readable=True,
                head_sha=SHA,
                mutation_patches_present=True,
                open_pr_number=7,
            ),
        )
        assert tree.asked == [(SLUG, SHA, MUTATIONS_PATH)]

    async def test_without_a_tree_port_patch_presence_is_unknown_not_absent(self) -> None:
        [head] = await EvidenceHeadObserver(_Forge()).observe(_aggregate(declared=[]), "implement")

        assert head.mutation_patches_present is None

    async def test_an_unreadable_forge_is_recorded_unreadable_and_the_tree_is_not_asked(
        self,
    ) -> None:
        tree = _Tree()
        [head] = await EvidenceHeadObserver(_Forge(unreadable={"feat/pushed"}), tree).observe(
            _aggregate(declared=[]), "implement"
        )

        assert (head.readable, head.head_sha, head.mutation_patches_present) == (False, None, None)
        assert tree.asked == []
