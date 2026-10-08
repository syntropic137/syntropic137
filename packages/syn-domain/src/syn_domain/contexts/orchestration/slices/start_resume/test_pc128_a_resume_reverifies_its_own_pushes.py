"""A resume continues at commits its own interrupted phase pushed (PC-128).

A deploy orphaned runs mid-fix after the fix phase had pushed. The failure
reconciliation writes observes nothing, the fix phase's branch existed before
the phase started, so nothing said the run had moved the branch - and the
resumed fix saw a head past its verified SHA and refused. Each cost a fresh
reverify-pr run (exec-26837be532a8, exec-5aa538f2f450, exec-051e420018d5).

These drive the parent's push in through the production path - the workspace
hook's `git_push` line in a tool result, read by the real `EmbeddedEventScanner`
and recorded by `push_recorder` through the real `ExecutionJournal` - then fail
it the way `reconciliation._reconcile_one` does, with no observed branches,
store everything through JSON, and start the resume through the real
`StartResumeHandler`. Only the forge (one branch reading) and the processor's
`run_resume` (which here only starts the child aggregate) are doubles.

    hook line -> EmbeddedEventScanner -> push_recorder -> PhaseCommitPushed
      -> OrphanedByRestart failure -> left branches -> resume candidates
      -> StartResumeHandler asks the forge -> child's start event
      -> StartPins.checkout_for -> record_continuation (what the phase is told)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, StreamAlreadyExistsError

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    SourceCommit,
    phase_definitions_of,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    CompletePhaseCommand,
    FailExecutionCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.EmbeddedEventScanner import (
    EmbeddedEventScanner,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
    ExecutionJournal,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ObservabilityCollector import (
    ObservabilityCollector,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_push import push_recorder
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    PhaseOutputCache,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.resume_handoff import (
    CONTINUATION_OUTPUT_ID,
    OWN_UNVERIFIED_PUSH,
    record_continuation,
)
from syn_domain.contexts.orchestration.slices.execution_todo.projection import (
    ExecutionTodoProjection,
)
from syn_domain.contexts.orchestration.slices.start_resume import StartResumeHandler

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
        StartResumeCommand,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
        StartPins,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

PARENT = "exec-pc128-parent"
CHILD = "exec-pc128-child"
WORKFLOW = "wf-pc128"
PHASE_IDS = ("verify", "fix", "finalize")
REPO = "acme/widgets"
BRANCH = "fix/1738-the-pr-under-review"
PR = 1738
#: The SHA the verify phase certified; the fix phase starts here.
VERIFIED = "a128a128a128a128a128a128a128a128a128a128"
#: The two commits the parent's fix phase pushed before the deploy killed it.
FIRST_PUSH = "b128b128b128b128b128b128b128b128b128b128"
LAST_PUSH = "c128c128c128c128c128c128c128c128c128c128"
#: A commit somebody else pushed to the branch after the run died.
FOREIGN = "f128f128f128f128f128f128f128f128f128f128"


class _Store:
    """Execution streams, every save read back through JSON as the store would."""

    def __init__(self) -> None:
        self.events: dict[str, list[EventEnvelope[DomainEvent]]] = {}

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.setdefault(aggregate.id or "", []).extend(
            EventEnvelope(
                event=type(e.event).model_validate_json(e.event.model_dump_json()),
                metadata=e.metadata,
            )
            for e in aggregate.get_uncommitted_events()
        )
        aggregate.mark_events_as_committed()

    async def save_new(self, aggregate: WorkflowExecutionAggregate) -> None:
        if aggregate.id in self.events:
            raise StreamAlreadyExistsError(aggregate.id or "", 0)
        await self.save(aggregate)

    async def get_by_id(self, aggregate_id: str) -> WorkflowExecutionAggregate | None:
        if aggregate_id not in self.events:
            return None
        fresh = WorkflowExecutionAggregate()
        fresh.rehydrate(list(self.events[aggregate_id]))
        return fresh


class _Forge:
    """Where origin has the branch now, and the PR open from it."""

    def __init__(self, head_sha: str) -> None:
        self.head_sha = head_sha

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        return RemoteBranchReading(
            repository=repository,
            branch=branch,
            readable=True,
            head_sha=self.head_sha,
            open_pull_request=PR,
        )


class _StartsTheChild:
    """`run_resume`, reduced to the start the processor would open the child with."""

    def __init__(self, store: _Store) -> None:
        self._store = store

    async def run_resume(self, command: StartResumeCommand, **_: object) -> None:
        child = WorkflowExecutionAggregate()
        child.start_resume(command)
        await self._store.save_new(child)


def _phases() -> list[ExecutablePhase]:
    return [
        ExecutablePhase(
            phase_id=p,
            name=p.title(),
            order=i + 1,
            agent_config=AgentConfiguration(),
            prompt_template=f"{p} prompt",
            timeout_seconds=1800,
        )
        for i, p in enumerate(PHASE_IDS)
    ]


def _hook_line(sha: str) -> str:
    """What the workspace's pre-push hook prints into the tool result."""
    return json.dumps(
        {
            "event_type": "git_push",
            "timestamp": "2026-10-08T01:00:00+00:00",
            "session_id": "sess-pc128",
            "provider": "claude",
            "context": {
                "git": {
                    "operation": "push",
                    "remote": "origin",
                    "branch": BRANCH,
                    "sha": sha,
                    "repo": "widgets",
                    "commits_count": 1,
                }
            },
            "metadata": None,
        }
    )


async def _orphaned_mid_fix(store: _Store, *, pushes: tuple[str, ...]) -> None:
    """A parent that verified, pushed ``pushes`` in fix, and was orphaned by a deploy."""
    parent = WorkflowExecutionAggregate()
    phases = _phases()
    parent.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id=WORKFLOW,
            workflow_name="reverify-pr",
            total_phases=len(phases),
            inputs={"pr": str(PR)},
            phase_definitions=phase_definitions_of(phases),
            pinned_phases=phases,
            source_commits=[SourceCommit(repository=REPO, sha=VERIFIED)],
        )
    )
    for order, phase_id in enumerate(("verify", "fix"), start=1):
        parent.start_phase(
            StartPhaseCommand(
                execution_id=PARENT,
                workflow_id=WORKFLOW,
                phase_id=phase_id,
                phase_name=phase_id.title(),
                phase_order=order,
            )
        )
        if phase_id == "verify":
            parent.complete_phase(
                CompletePhaseCommand(
                    execution_id=PARENT,
                    workflow_id=WORKFLOW,
                    phase_id="verify",
                    session_id=None,
                    artifact_id=None,
                    input_tokens=0,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=0,
                    duration_seconds=1.0,
                )
            )
    journal = ExecutionJournal(store, ExecutionTodoProjection(InMemoryProjectionStore()))
    await journal.open(parent)
    scanner = EmbeddedEventScanner(
        collector=ObservabilityCollector(
            writer=None,
            session_id="sess-pc128",
            execution_id=PARENT,
            phase_id="fix",
            workspace_id=None,
            requested_model=None,
        ),
        execution_id=PARENT,
        phase_id="fix",
        on_push=push_recorder(parent, journal, "fix"),
    )
    for sha in pushes:
        await scanner.scan_and_record(f"To github.com:acme/widgets\n{_hook_line(sha)}\n", "Bash")
    # What `reconciliation._reconcile_one` records: no observed branches.
    parent.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="Execution was running when the API restarted",
            error_type="OrphanedByRestart",
            failed_phase_id="fix",
            completed_phases=1,
            total_phases=len(phases),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    parent.resume_execution(
        ResumeExecutionCommand(
            execution_id=PARENT, resume_execution_id=CHILD, acknowledge_external_effects=True
        )
    )
    await journal.append(parent)


async def _resume(store: _Store, forge_head: str) -> StartPins:
    handler = StartResumeHandler(
        processor=_StartsTheChild(store),  # type: ignore[arg-type]
        execution_repository=store,  # type: ignore[arg-type]
        remote_branches=_Forge(forge_head),
    )
    await handler.handle(PARENT)
    child = await store.get_by_id(CHILD)
    assert child is not None
    return child.start_pins


def _told(pins: StartPins) -> str:
    cache = PhaseOutputCache()
    record_continuation(cache, pins)
    return cache.primary.get(CONTINUATION_OUTPUT_ID, "")


class TestOwnPushesAreReverified:
    async def test_a_head_at_the_runs_last_push_is_continued_and_reverified(self) -> None:
        store = _Store()
        await _orphaned_mid_fix(store, pushes=(FIRST_PUSH, LAST_PUSH))

        pins = await _resume(store, forge_head=LAST_PUSH)

        checkout = pins.checkout_for("fix")
        assert checkout.commits[REPO] == LAST_PUSH
        assert checkout.branches[REPO] == BRANCH
        assert pins.abandoned_branches == []
        [continued] = pins.continued_branches
        assert continued.pull_request == PR
        told = _told(pins)
        assert OWN_UNVERIFIED_PUSH in told
        assert LAST_PUSH in told

    async def test_a_head_at_an_earlier_own_push_is_still_the_runs_own(self) -> None:
        """The last push may not have landed; the one before it did."""
        store = _Store()
        await _orphaned_mid_fix(store, pushes=(FIRST_PUSH, LAST_PUSH))

        pins = await _resume(store, forge_head=FIRST_PUSH)

        assert pins.checkout_for("fix").commits[REPO] == FIRST_PUSH
        assert OWN_UNVERIFIED_PUSH in _told(pins)


class TestAForeignHeadIsStillRefused:
    async def test_a_commit_this_run_did_not_push_abandons_the_branch(self) -> None:
        store = _Store()
        await _orphaned_mid_fix(store, pushes=(FIRST_PUSH, LAST_PUSH))

        pins = await _resume(store, forge_head=FOREIGN)

        checkout = pins.checkout_for("fix")
        assert pins.continued_branches == []
        assert REPO not in checkout.branches
        assert checkout.commits[REPO] == VERIFIED
        [abandoned] = pins.abandoned_branches
        assert FOREIGN in abandoned.reason
        assert OWN_UNVERIFIED_PUSH not in _told(pins)


class TestNoPushIsUnchanged:
    async def test_a_fix_that_pushed_nothing_continues_nothing(self) -> None:
        store = _Store()
        await _orphaned_mid_fix(store, pushes=())

        pins = await _resume(store, forge_head=FOREIGN)

        assert pins.continued_branches == []
        assert pins.abandoned_branches == []
        assert pins.checkout_for("fix").commits[REPO] == VERIFIED
        assert _told(pins) == ""


class TestAResumeOfAResumeKeepsEveryOwnPush:
    def test_the_parents_pushes_and_the_childs_are_both_the_runs_own(self) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
            ContinuedBranch,
            PushedCommit,
            branches_left_by,
        )

        continued = ContinuedBranch(
            repository=REPO, branch=BRANCH, head_sha=FIRST_PUSH, pushed_shas=[FIRST_PUSH]
        )
        [left] = branches_left_by(
            None,
            repositories=[REPO],
            continued=[continued],
            pushed=[
                PushedCommit(phase_id="fix", repository="widgets", branch=BRANCH, sha=LAST_PUSH)
            ],
        )

        assert left.head_sha == LAST_PUSH
        assert left.pushed_shas == [FIRST_PUSH, LAST_PUSH]
