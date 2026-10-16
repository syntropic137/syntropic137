"""A phase's evidence declaration and the forge's heads reach the event store (plan §A.2).

Drives the text an agent emits through the real processor loop, the real
`PhaseWorkspace` collection and the real aggregate, to the events kept. The
hops checked here are the processor building `EvidenceHeadObserver` from its
`remote_branches`, and collection attaching the heads BEFORE the aggregate is
told. Recorded only: the run's outcome is the same with or without either.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    RemoteBranchReading,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
    ObservedHead,
)
from syn_domain.contexts.orchestration.domain.events.AgentExecutionCompletedEvent import (
    AgentExecutionCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ArtifactsCollectedForPhaseEvent import (
    ArtifactsCollectedForPhaseEvent,
)
from syn_domain.testing.fake_agent_handler import A_DELIVERABLE, FakeAgentExecutionHandler

from .test_processor_smoke import FakeExecutionRepository, _make_processor, _one_phase_workflow

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

pytestmark = pytest.mark.unit

SLUG = "syntropic137/syntropic137"
SHA = "d" * 40
ENTRY = {
    "kind": "mutation",
    "repository": SLUG,
    "branch": "feat/declared",
    "pr": 11,
    "head_sha": SHA,
    "tests": ["tests/test_x.py::test_kills"],
}
SAYS = (
    f"TASK_RESULT: {json.dumps({'success': True, 'comments': 'done', 'evidence': [ENTRY]})}\n"
    "TASK_RESULT_END"
)


class _RecordingRepository(FakeExecutionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[object] = []

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.events.extend(e.event for e in aggregate.get_uncommitted_events())
        await super().save(aggregate)

    def of_type[E](self, kind: type[E]) -> list[E]:
        return [e for e in self.events if isinstance(e, kind)]


@dataclass
class _Forge:
    asked: list[tuple[str, str]] = field(default_factory=list)

    async def read_branch(self, repository: str, branch: str) -> RemoteBranchReading:
        self.asked.append((repository, branch))
        return RemoteBranchReading(
            repository=repository, branch=branch, readable=True, head_sha=SHA, open_pull_request=11
        )


async def _run(*, forge: _Forge | None, execution_id: str) -> tuple[str, _RecordingRepository]:
    repo = _RecordingRepository()
    result = await _make_processor(
        FakeAgentExecutionHandler.success(produces=A_DELIVERABLE, says=SAYS),
        execution_repository=repo,
        remote_branches=forge,
    ).run(
        workflow_id="wf-evidence",
        workflow_name="A phase that declares evidence",
        phases=_one_phase_workflow(),
        inputs={},
        execution_id=execution_id,
    )
    return result.status, repo


async def test_the_declaration_is_recorded_on_agent_execution_completed() -> None:
    _, repo = await _run(forge=None, execution_id="exec-ev-declared")

    [completed] = repo.of_type(AgentExecutionCompletedEvent)
    [declared] = completed.reported_evidence
    assert declared.request is not None
    assert declared.request.branch == "feat/declared"


async def test_the_declared_branch_head_is_recorded_on_collection() -> None:
    forge = _Forge()
    status, repo = await _run(forge=forge, execution_id="exec-ev-observed")

    assert status == "completed"
    [collected] = repo.of_type(ArtifactsCollectedForPhaseEvent)
    assert collected.observed_heads == [
        ObservedHead(
            repository=SLUG,
            branch="feat/declared",
            readable=True,
            head_sha=SHA,
            mutation_patches_present=None,
            open_pr_number=11,
        )
    ]
    assert forge.asked == [(SLUG, "feat/declared")]


async def test_without_a_forge_nothing_is_observed_and_the_run_is_unchanged() -> None:
    status, repo = await _run(forge=None, execution_id="exec-ev-no-forge")

    assert status == "completed"
    [collected] = repo.of_type(ArtifactsCollectedForPhaseEvent)
    assert collected.observed_heads == []
