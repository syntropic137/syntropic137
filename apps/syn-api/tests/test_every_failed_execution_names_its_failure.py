"""A failed execution, and the phase it failed in, always say why.

Another orchestrator read two failed runs (exec-38ca290f50a6: exit 124;
exec-b633cc744455: codex "Selected model is at capacity") and concluded they
"failed with no error". The text and the classification were both on the
execution; neither was on the PHASE that died, which is where a reader looking
at a phase table goes first.

So this is a sweep, not a scenario: every way a run is known to fail here is
driven through the production chain - exception -> outcome -> aggregate ->
WorkflowFailed -> detail projection -> `GET /executions/{id}` - and every one
must arrive with a non-empty `error_message` and a classification, at the
execution AND on its failed phase. A new failure shape belongs in
`_FAILURES`; a shape that reaches a reader without its reason fails here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
    ReportedFailureReason,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import PhaseStartedEvent
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    NonZeroExitError,
    PhaseReportedFailureError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import VerdictReader
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import ExecutionDetailResponse
    from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
        WorkflowFailedEvent,
    )

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-failure-sweep"
PHASE_ID = "implement"
_STARTED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
_FAILED_AT = datetime(2026, 10, 5, 9, 20, tzinfo=UTC)


def _reported(*messages: str) -> PhaseReportedFailureError:
    """What a phase dies on when its agent's own report ended it, read for real."""
    reader = VerdictReader()
    for message in messages:
        reader.read(message)
    return PhaseReportedFailureError(phase_id=PHASE_ID, verdict=reader.verdict)


#: Every failure shape this sweep knows, keyed by the execution id it runs as.
_FAILURES: dict[str, BaseException] = {
    # exec-38ca290f50a6's shape: the phase hit its wall-clock budget.
    "exec-timeout": NonZeroExitError("agent exited with code 124", exit_code=124),
    # exec-b633cc744455's shape: the harness reported the model unavailable.
    "exec-capacity": RuntimeError(
        "codex: Selected model is at capacity. Please try a different model."
    ),
    "exec-crash": RuntimeError("workspace container exited 137 before the agent reported"),
    "exec-refusal": _reported(
        'TASK_RESULT: {"success": false, "comments": "premise false"}\nTASK_RESULT_END'
    ),
    "exec-task": _reported(
        'TASK_RESULT: {"success": false, "failure_reason": "task", '
        '"comments": "the brief names a module that does not exist"}\nTASK_RESULT_END'
    ),
    "exec-unreadable": _reported("TASK_RESULT: {success: probably not"),
    # A readable report that says "I cannot tell": the one current-code shape
    # that is DELIBERATELY unclassified (`classification_for_reported`).
    "exec-unknown": _reported(
        'TASK_RESULT: {"success": false, "failure_reason": "unknown", '
        '"comments": "the run died and I cannot tell why"}\nTASK_RESULT_END'
    ),
}


def _failed_event(execution_id: str, error: BaseException) -> WorkflowFailedEvent:
    """The WorkflowFailed event the REAL aggregate emits for a run that died on `error`."""
    outcome = failed_phase_outcome(
        error,
        phase_id=PHASE_ID,
        started_at_by_phase={PHASE_ID: _STARTED_AT},
        session_id_by_phase={},
        now=_FAILED_AT,
    )
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=execution_id,
            workflow_id=WORKFLOW_ID,
            workflow_name="implement-verify-report",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.fail_execution(outcome.as_command(execution_id, completed_phases=0, total_phases=1))
    event = aggregate.get_uncommitted_events()[-1].event
    assert event.event_type == "WorkflowFailed", event.event_type
    return event


@dataclass
class _StubProjectionManager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _projections() -> _StubProjectionManager:
    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    for execution_id, error in _FAILURES.items():
        await detail.on_workflow_execution_started(
            WorkflowExecutionStartedEvent(
                workflow_id=WORKFLOW_ID,
                execution_id=execution_id,
                workflow_name="implement-verify-report",
                started_at=_STARTED_AT,
                total_phases=1,
                inputs={},
            ).model_dump()
        )
        # The phase has to be in the record for the failure to land on it:
        # a run that fails with no phase started has no phase to stamp.
        await detail.on_phase_started(
            PhaseStartedEvent(
                workflow_id=WORKFLOW_ID,
                execution_id=execution_id,
                phase_id=PHASE_ID,
                phase_name=PHASE_ID,
                phase_order=0,
                started_at=_STARTED_AT,
            ).model_dump()
        )
        await detail.on_workflow_failed(_failed_event(execution_id, error).model_dump())
    return _StubProjectionManager(store=store, workflow_execution_detail=detail)


async def _detail(
    monkeypatch: pytest.MonkeyPatch, manager: _StubProjectionManager, execution_id: str
) -> ExecutionDetailResponse:
    """Serve `GET /executions/{id}` off projections built from real events."""
    from syn_api import _wiring
    from syn_api.routes.executions import queries

    async def _noop_connect() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    return await queries.get_execution_endpoint(execution_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_id", sorted(_FAILURES))
async def test_a_failed_execution_carries_its_error_and_classification(
    monkeypatch: pytest.MonkeyPatch, execution_id: str
) -> None:
    detail = await _detail(monkeypatch, await _projections(), execution_id)

    assert detail.status == "failed"
    assert detail.error_message, f"{execution_id} failed with an empty error_message"
    assert isinstance(detail.failure_classification, FailureClassification), (
        f"{execution_id} failed with no classification"
    )
    # Unclassified is a classification only when the phase itself said it
    # cannot tell; from anything else today's code must have decided.
    if detail.failure_classification is FailureClassification.UNCLASSIFIED:
        assert detail.reported_failure_reason is ReportedFailureReason.UNKNOWN, (
            f"{execution_id} was produced by today's code and still reads unclassified"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_id", sorted(_FAILURES))
async def test_the_failed_phase_carries_the_same_error_and_classification(
    monkeypatch: pytest.MonkeyPatch, execution_id: str
) -> None:
    """The phase a reader opens first says what the execution says.

    Driven to the HTTP model, not stopped at the projection row: the response
    constructor re-lists every phase field by hand and is the hop that has
    dropped one before (#891, #1176, #1319).
    """
    detail = await _detail(monkeypatch, await _projections(), execution_id)

    (phase,) = detail.phases
    assert phase.status == "failed"
    assert phase.error_message, f"{execution_id}'s failed phase has no error_message"
    assert phase.error_message == detail.error_message, (
        f"{execution_id}: execution says {detail.error_message!r}, "
        f"its failed phase says {phase.error_message!r}"
    )
    assert phase.failure_classification is detail.failure_classification, (
        f"{execution_id}: execution says {detail.failure_classification!r}, "
        f"its failed phase says {phase.failure_classification!r}"
    )
    assert phase.reported_failure_reason == detail.reported_failure_reason
