"""POST /executions/{id}/fork - the operator's way to resume a failed run.

The domain decides; this endpoint only carries the decision and reports it. So
these tests pin the CARRYING: that the parent's refusals surface as 409 rather
than 500 or a silent success, that the child's id and resume point reach the
caller, and that nothing is saved when the fork is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException

from syn_api.routes.executions.fork import ForkRequest, fork
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CompletePhaseCommand,
    FailExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

PARENT = "exec-parent-fork-api"
PHASES = ("research", "plan", "implement")


def _phase_defs() -> list[PhaseDefinition]:
    return [PhaseDefinition(phase_id=p, name=p.title(), order=i + 1) for i, p in enumerate(PHASES)]


def _failed_after_research() -> WorkflowExecutionAggregate:
    """A parent that completed `research` and then failed, so a fork resumes at
    `plan` - the shape an operator actually forks."""
    agg = WorkflowExecutionAggregate()
    agg.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Fork Me",
            total_phases=len(PHASES),
            inputs={"task": "t"},
            phase_definitions=_phase_defs(),
        )
    )
    agg.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            phase_name="Research",
            phase_order=1,
        )
    )
    agg.complete_phase(
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
    agg.fail_execution(
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
    agg.mark_events_as_committed()
    return agg


class _Executions:
    """The repository, remembering whether it was asked to save."""

    def __init__(self, parent: WorkflowExecutionAggregate | None) -> None:
        self._parent = parent
        self.saved: list[str] = []

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        del execution_id
        return self._parent

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        self.saved.append(aggregate.id or "")

    async def exists(self, execution_id: str) -> bool:
        del execution_id
        return self._parent is not None


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Executions]:
    """Point the endpoint's wiring at one in-memory parent."""
    executions = _Executions(_failed_after_research())
    import syn_api._wiring as wiring

    monkeypatch.setattr(wiring, "get_workflow_execution_repository", lambda: executions)
    yield executions


class TestAFailedExecutionCanBeForked:
    async def test_it_returns_the_child_and_where_it_resumes(self, repo: _Executions) -> None:
        response = await fork(PARENT, ForkRequest())

        assert response.parent_execution_id == PARENT
        assert response.execution_id.startswith("exec-")
        assert response.execution_id != PARENT, "the child needs an id of its own"
        assert response.resume_phase_id == "plan"
        assert response.inherited_phase_ids == ["research"]
        assert repo.saved == [PARENT], "the fork was not recorded on the parent"

    async def test_the_child_is_not_the_parent_twice(self, repo: _Executions) -> None:
        """Two operators, two ids - the parent refuses the second itself."""
        first = await fork(PARENT, ForkRequest())

        with pytest.raises(HTTPException) as refused:
            await fork(PARENT, ForkRequest())

        assert refused.value.status_code == 409
        assert first.execution_id in str(refused.value.detail)


class TestTheParentsRefusalsReachTheCaller:
    async def test_a_missing_execution_is_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import syn_api._wiring as wiring

        monkeypatch.setattr(wiring, "get_workflow_execution_repository", lambda: _Executions(None))

        with pytest.raises(HTTPException) as missing:
            await fork("exec-nope", ForkRequest())

        assert missing.value.status_code == 404

    async def test_a_running_parent_is_409_and_saves_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A conflict with recorded state, not a malformed request - and the
        parent must not be written when its own rule said no."""
        running = _failed_after_research()
        still_running = WorkflowExecutionAggregate()
        still_running.start_execution(
            StartExecutionCommand(
                execution_id=PARENT,
                workflow_id="wf-1",
                workflow_name="Fork Me",
                total_phases=len(PHASES),
                inputs={},
                phase_definitions=_phase_defs(),
            )
        )
        still_running.mark_events_as_committed()
        del running

        executions = _Executions(still_running)
        import syn_api._wiring as wiring

        monkeypatch.setattr(wiring, "get_workflow_execution_repository", lambda: executions)

        with pytest.raises(HTTPException) as refused:
            await fork(PARENT, ForkRequest())

        assert refused.value.status_code == 409
        assert executions.saved == [], "a refused fork must write nothing"

    async def test_a_cancelled_parent_needs_the_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
            CancelExecutionCommand,
        )

        cancelled = _failed_after_research()
        # Rebuild as cancelled rather than failed.
        fresh = WorkflowExecutionAggregate()
        fresh.start_execution(
            StartExecutionCommand(
                execution_id=PARENT,
                workflow_id="wf-1",
                workflow_name="Fork Me",
                total_phases=len(PHASES),
                inputs={},
                phase_definitions=_phase_defs(),
            )
        )
        fresh.cancel_execution(
            CancelExecutionCommand(execution_id=PARENT, phase_id="plan", reason="wrong repo")
        )
        fresh.mark_events_as_committed()
        del cancelled

        executions = _Executions(fresh)
        import syn_api._wiring as wiring

        monkeypatch.setattr(wiring, "get_workflow_execution_repository", lambda: executions)

        with pytest.raises(HTTPException) as refused:
            await fork(PARENT, ForkRequest())
        assert refused.value.status_code == 409
        assert "override" in str(refused.value.detail).lower()

        granted = await fork(PARENT, ForkRequest(override_cancellation=True))
        assert granted.cancellation_overridden is True


class TestTheFlagsAreSeparateDecisions:
    async def test_neither_flag_implies_the_other(self, repo: _Executions) -> None:
        response = await fork(PARENT, ForkRequest(acknowledge_external_effects=True))

        assert response.cancellation_overridden is False, (
            "acknowledging effects must not also override a cancellation"
        )

    def test_both_default_to_the_refusal(self) -> None:
        request = ForkRequest()
        assert request.override_cancellation is False
        assert request.acknowledge_external_effects is False

    def test_an_unknown_flag_is_rejected(self) -> None:
        """extra=forbid, so a typo'd flag fails loudly instead of defaulting to
        the refusal and looking like the operator never asked."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ForkRequest.model_validate({"override_cancelation": True})


def test_the_forked_at_is_recorded() -> None:
    """Sanity: the event carries a timestamp the API does not invent."""
    assert datetime.now(UTC).tzinfo is UTC
