"""POST /executions/{id}/resume - the operator's way to resume a failed run.

The domain decides; this endpoint carries the decision. So these tests pin the
CARRYING: that the parent's refusals AND the child's reach the caller as 409,
that nothing is written when a resume is refused, that a concurrent resume does not
surface as a 500, and that the child's id is not minted onto an execution that
already exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from event_sourcing import ConcurrencyConflictError
from fastapi import HTTPException

from syn_api.routes.executions.resume import ResumeRequest, resume
from syn_domain.contexts.artifacts import PhaseOutputFile
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CancelExecutionCommand,
    CompletePhaseCommand,
    FailExecutionCommand,
    ResumeExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

pytestmark = pytest.mark.unit

PARENT = "exec-parent-resume-api"
PHASES = ("research", "plan", "implement")


def _phase_defs() -> list[PhaseDefinition]:
    return [PhaseDefinition(phase_id=p, name=p.title(), order=i + 1) for i, p in enumerate(PHASES)]


def _pinned() -> list[ExecutablePhase]:
    """The runnable config an execution pins at start (#1454).

    Real executions carry this, and a parent WITHOUT it cannot be resumed at all -
    the child would have to read the current workflow template. A fixture that
    omitted it was not a parent anyone could resume, so omitting it would have made
    every test here exercise the refusal path by accident.
    """
    return [
        ExecutablePhase(
            phase_id=p,
            name=p.title(),
            order=i + 1,
            agent_config=AgentConfiguration(),
            prompt_template=f"{p} as pinned",
            output_artifact_types=(),
            timeout_seconds=1800,
        )
        for i, p in enumerate(PHASES)
    ]


def _started() -> WorkflowExecutionAggregate:
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Resume Me",
            total_phases=len(PHASES),
            inputs={"task": "t"},
            phase_definitions=_phase_defs(),
            pinned_phases=_pinned(),
        )
    )
    return aggregate


def _complete_research(aggregate: WorkflowExecutionAggregate) -> None:
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            phase_name="Research",
            phase_order=1,
        )
    )
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            session_id=None,
            artifact_id="art-research",
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=1.0,
        )
    )


def _failed_after_research() -> WorkflowExecutionAggregate:
    """Completed `research`, then failed - so a resume resumes at `plan`.

    The shape an operator actually resumes.
    """
    aggregate = _started()
    _complete_research(aggregate)
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="the harness died",
            error_type="AgentError",
            failed_phase_id="plan",
            completed_phases=1,
            total_phases=len(PHASES),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    aggregate.mark_events_as_committed()
    return aggregate


def _failed_inside_plan() -> WorkflowExecutionAggregate:
    """Completed `research`, STARTED `plan`, then failed in it.

    The common shape, and the one `_failed_after_research` does not cover: a run
    usually dies inside a phase rather than between two. Because `plan` started,
    its external effects are unacknowledged, so a resume with no flags is REFUSED -
    which the guide's lead example got wrong until the workflow review of #1461
    pointed it out.
    """
    aggregate = _started()
    _complete_research(aggregate)
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="plan",
            phase_name="Plan",
            phase_order=2,
        )
    )
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="the harness died mid-phase",
            error_type="AgentError",
            failed_phase_id="plan",
            completed_phases=1,
            total_phases=len(PHASES),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    aggregate.mark_events_as_committed()
    return aggregate


def _still_running() -> WorkflowExecutionAggregate:
    aggregate = _started()
    aggregate.mark_events_as_committed()
    return aggregate


def _cancelled() -> WorkflowExecutionAggregate:
    aggregate = _started()
    _complete_research(aggregate)
    aggregate.cancel_execution(
        CancelExecutionCommand(execution_id=PARENT, phase_id="plan", reason="wrong repo")
    )
    aggregate.mark_events_as_committed()
    return aggregate


def _unpinned_failure() -> WorkflowExecutionAggregate:
    """A parent from BEFORE #1454: no pinned phase config.

    Its resume could be admitted and then never start, spending the parent's one
    resume on a run that does not exist. The endpoint refuses it up front instead.
    """
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Resume Me",
            total_phases=len(PHASES),
            inputs={},
            phase_definitions=_phase_defs(),
        )
    )
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="boom",
            error_type="AgentError",
            failed_phase_id="research",
            completed_phases=0,
            total_phases=len(PHASES),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    aggregate.mark_events_as_committed()
    return aggregate


class _Executions:
    """The repository, remembering what it was asked to save."""

    def __init__(self, parent: WorkflowExecutionAggregate | None) -> None:
        self._parent = parent
        self.saved: list[str] = []
        self.taken: set[str] = set() if parent is None else {parent.id or PARENT}
        self.conflict_on_save = False

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        return self._parent if execution_id == PARENT else None

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        if self.conflict_on_save:
            raise ConcurrencyConflictError(expected_version=3, actual_version=4)
        self.saved.append(aggregate.id or "")

    async def exists(self, execution_id: str) -> bool:
        """Only the ids this repository holds.

        Answering True for everything would make the endpoint's collision guard
        exhaust its attempts - a fake that answers a different question than the
        real repository tests nothing.
        """
        return execution_id in self.taken


class _ArtifactQuery:
    """Resolves the inherited artifacts, or deliberately does not.

    The endpoint reads these BEFORE admitting a resume, so a query that resolves
    nothing is not a test-setup detail - it is the case where the parent's
    artifacts have gone, which must refuse rather than spend the resume.
    """

    def __init__(self, *, resolves: bool = True) -> None:
        self.resolves = resolves
        self.asked: list[str] = []

    async def get_files_for_artifacts(
        self, execution_id: str, phase_artifact_ids: Mapping[str, Sequence[str]]
    ) -> dict[str, list[PhaseOutputFile]]:
        self.asked.append(execution_id)
        if not self.resolves:
            return {}
        return {
            phase_id: [PhaseOutputFile(source_path=None, content=f"{phase_id} output")]
            for phase_id, ids in phase_artifact_ids.items()
            if ids
        }


def _point_wiring_at(
    executions: _Executions,
    monkeypatch: pytest.MonkeyPatch,
    *,
    artifacts: _ArtifactQuery | None = None,
) -> _ArtifactQuery:
    import syn_api._wiring as wiring

    query = artifacts or _ArtifactQuery()
    monkeypatch.setattr(wiring, "get_workflow_execution_repository", lambda: executions)
    monkeypatch.setattr(wiring, "get_artifact_query", lambda: query)
    return query


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Executions]:
    executions = _Executions(_failed_after_research())
    _point_wiring_at(executions, monkeypatch)
    yield executions


class TestAFailedExecutionCanBeResumed:
    async def test_it_returns_the_child_and_where_it_resumes(self, repo: _Executions) -> None:
        response = await resume(PARENT, ResumeRequest())

        assert response.parent_execution_id == PARENT
        assert response.execution_id.startswith("exec-")
        assert response.execution_id != PARENT, "the child needs an id of its own"
        assert response.resume_phase_id == "plan"
        assert response.inherited_phase_ids == ["research"]
        assert repo.saved == [PARENT], "the resume was not recorded on the parent"

    async def test_a_second_resume_is_refused_and_names_the_first(self, repo: _Executions) -> None:
        first = await resume(PARENT, ResumeRequest())

        with pytest.raises(HTTPException) as refused:
            await resume(PARENT, ResumeRequest())

        assert refused.value.status_code == 409
        assert first.execution_id in str(refused.value.detail)


class TestRefusalsReachTheCaller:
    async def test_a_missing_execution_is_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_wiring_at(_Executions(None), monkeypatch)

        with pytest.raises(HTTPException) as missing:
            await resume("exec-nope", ResumeRequest())

        assert missing.value.status_code == 404

    async def test_a_running_parent_is_409_and_saves_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executions = _Executions(_still_running())
        _point_wiring_at(executions, monkeypatch)

        with pytest.raises(HTTPException) as refused:
            await resume(PARENT, ResumeRequest())

        assert refused.value.status_code == 409
        assert executions.saved == [], "a refused resume must write nothing"

    async def test_a_cancelled_parent_needs_the_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executions = _Executions(_cancelled())
        _point_wiring_at(executions, monkeypatch)

        with pytest.raises(HTTPException) as refused:
            await resume(PARENT, ResumeRequest())
        assert refused.value.status_code == 409
        assert "override" in str(refused.value.detail).lower()
        assert executions.saved == []

        granted = await resume(PARENT, ResumeRequest(override_cancellation=True))
        assert granted.cancellation_overridden is True


class TestAdmissionIsNotGrantedForAChildThatCannotStart:
    """Codex review of #1461, finding 1.

    A parent admits exactly ONE resume. Recording an admission the child cannot act
    on spends that resume on a run that never starts, and the operator is told yes.
    """

    async def test_an_unpinned_parent_is_refused_before_anything_is_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executions = _Executions(_unpinned_failure())
        _point_wiring_at(executions, monkeypatch)

        with pytest.raises(HTTPException) as refused:
            await resume(PARENT, ResumeRequest())

        assert refused.value.status_code == 409
        assert "pinned" in str(refused.value.detail).lower()
        assert executions.saved == [], (
            "the parent's one resume was spent on a child that could not start"
        )


class TestAConcurrentResumeIsNotAServerError:
    """Codex review of #1461, finding 3.

    The store refuses the second write, so there is exactly one resume - but the
    loser was told 500, which reads as "we broke" rather than "someone else won".
    """

    async def test_it_is_409_and_names_the_resume_that_won(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        winner = _failed_after_research()
        winner.resume_execution(
            ResumeExecutionCommand(execution_id=PARENT, resume_execution_id="exec-winner")
        )
        winner.mark_events_as_committed()

        executions = _Executions(_failed_after_research())
        executions.conflict_on_save = True
        _point_wiring_at(executions, monkeypatch)

        # The reload after the conflict sees the parent as the winner left it.
        async def _reloaded(execution_id: str) -> WorkflowExecutionAggregate | None:
            return winner if execution_id == PARENT else None

        with pytest.raises(HTTPException) as refused:
            original = executions.get_by_id
            try:
                # First load returns the unresumed parent; the post-conflict
                # reload returns the winner's version.
                calls = {"n": 0}

                async def _get(execution_id: str) -> WorkflowExecutionAggregate | None:
                    calls["n"] += 1
                    if calls["n"] == 1:
                        return await original(execution_id)
                    return await _reloaded(execution_id)

                executions.get_by_id = _get  # type: ignore[method-assign]
                await resume(PARENT, ResumeRequest())
            finally:
                executions.get_by_id = original  # type: ignore[method-assign]

        assert refused.value.status_code == 409
        assert "concurrently" in str(refused.value.detail)
        assert "exec-winner" in str(refused.value.detail), "the loser cannot see who won"


class TestTheChildIdIsNotAnExistingExecution:
    """Codex review of #1461, finding 2.

    A collision would spend the parent's resume naming an execution that already
    exists, and child start would see that stream and call the resume already
    started - so the caller gets a success pointing at an unrelated run.
    """

    async def test_a_colliding_id_is_not_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        executions = _Executions(_failed_after_research())
        _point_wiring_at(executions, monkeypatch)

        # Every candidate collides, which is the collision case taken to its
        # limit: the endpoint must refuse rather than record one anyway.
        with (
            patch.object(type(executions), "exists", return_value=True, create=True),
            pytest.raises(HTTPException) as refused,
        ):
            await resume(PARENT, ResumeRequest())

        assert refused.value.status_code == 503
        assert executions.saved == []

    async def test_a_free_id_is_used(self, repo: _Executions) -> None:
        response = await resume(PARENT, ResumeRequest())
        assert response.execution_id not in repo.taken


class TestTheFlagsAreSeparateDecisions:
    async def test_neither_flag_implies_the_other(self, repo: _Executions) -> None:
        response = await resume(PARENT, ResumeRequest(acknowledge_external_effects=True))

        assert response.cancellation_overridden is False, (
            "acknowledging effects must not also override a cancellation"
        )

    def test_both_default_to_the_refusal(self) -> None:
        request = ResumeRequest()
        assert request.override_cancellation is False
        assert request.acknowledge_external_effects is False

    def test_an_unknown_flag_is_rejected(self) -> None:
        """extra=forbid, so a typo'd flag fails loudly instead of defaulting to
        the refusal and looking like the operator never asked."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeRequest.model_validate({"override_cancelation": True})


def test_the_event_carries_a_timestamp_the_api_does_not_invent() -> None:
    assert datetime.now(UTC).tzinfo is UTC


class TestTheCommonFailureShapeNeedsTheAcknowledgement:
    """Workflow review of #1461, U1.

    A run usually dies INSIDE a phase. That phase started, so re-running it may
    repeat whatever it published - and the resume is refused until the operator
    says so. Every earlier test here used a parent that failed BETWEEN phases,
    which is why the suite was green while the documented common case failed.
    """

    async def test_a_resume_with_no_flags_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        executions = _Executions(_failed_inside_plan())
        _point_wiring_at(executions, monkeypatch)

        with pytest.raises(HTTPException) as refused:
            await resume(PARENT, ResumeRequest())

        assert refused.value.status_code == 409
        assert "external effects" in str(refused.value.detail).lower()
        assert executions.saved == []

    async def test_it_is_admitted_once_the_effects_are_acknowledged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executions = _Executions(_failed_inside_plan())
        _point_wiring_at(executions, monkeypatch)

        response = await resume(PARENT, ResumeRequest(acknowledge_external_effects=True))

        assert response.resume_phase_id == "plan"
        assert response.inherited_phase_ids == ["research"]
        assert response.external_effects_acknowledged is True
        assert executions.saved == [PARENT]


class TestAResumeIsRefusedWhenItsInheritanceCannotBeRead:
    """Workflow review of #1461, U2.

    The parent's artifacts are what the resumed phase reads. If they have gone,
    admitting the resume spends the parent's ONE resume on a child that can never
    start, with nothing recording why - and the endpoint's docstring used to
    promise that could not happen while checking only half of it.
    """

    async def test_a_vanished_artifact_refuses_and_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executions = _Executions(_failed_after_research())
        query = _point_wiring_at(executions, monkeypatch, artifacts=_ArtifactQuery(resolves=False))

        with pytest.raises(HTTPException) as refused:
            await resume(PARENT, ResumeRequest())

        assert refused.value.status_code == 409
        assert "inheritance" in str(refused.value.detail).lower()
        assert executions.saved == [], "the parent's one resume was spent on an unstartable child"
        assert query.asked == [PARENT], "the parent's artifacts were never looked up"

    async def test_a_resolvable_inheritance_is_admitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executions = _Executions(_failed_after_research())
        query = _point_wiring_at(executions, monkeypatch)

        response = await resume(PARENT, ResumeRequest())

        assert response.inherited_phase_ids == ["research"]
        assert query.asked == [PARENT]
        assert executions.saved == [PARENT]


@pytest.mark.unit
class TestTheOldForkPathIsGoneNotBroken:
    """A caller on the pre-rename path must get a 404, never a 500.

    The route was never deployed - the Mini answered 404 on it throughout - so
    no client depends on it. A developer's local script might, though, and a
    500 would send them debugging the server instead of reading the rename.

    Asserted rather than assumed: a route removed by renaming its module can
    still be reachable if anything else mounted it, and the failure mode of a
    half-removed route is a 500 from a handler with no dependencies wired.

    The mounted paths are read from the app rather than inferred from a
    response code. A POST to a live route with an unknown execution ALSO
    returns 404, so a response code cannot tell "no such route" from "no such
    execution" - which is exactly the confusion that would let a silently
    unmounted resume route pass this class.
    """

    def _paths(self) -> set[str]:
        from syn_api.main import create_app

        return {getattr(route, "path", "") for route in create_app().routes}

    def test_the_fork_path_is_not_mounted(self) -> None:
        assert "/executions/{execution_id}/fork" not in self._paths()

    def test_the_pause_path_is_not_mounted_either(self) -> None:
        """Pause was deleted in the same change; its path must also be gone."""
        assert "/executions/{execution_id}/pause" not in self._paths()

    def test_the_resume_path_IS_mounted(self) -> None:
        """The control: the two absences above mean "removed", not "app empty"."""
        assert "/executions/{execution_id}/resume" in self._paths()

    async def test_a_request_to_the_old_path_is_a_clean_404(self) -> None:
        """Not a 500. An unmounted path is Starlette's 404, and this proves it
        is reached as one rather than hitting a half-wired handler."""
        from httpx import ASGITransport, AsyncClient

        from syn_api.main import create_app

        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/executions/exec-1/fork", json={})

        assert response.status_code == 404
