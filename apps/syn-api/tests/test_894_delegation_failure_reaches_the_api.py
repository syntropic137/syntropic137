"""#894: which required delegate failed, and why, must reach the API as fields.

Verification of the first #894 fix found the gate correct and its account
prose: the reason and every delegate the journal held were rendered into
`error_message` and nothing else, so a client could tell `failed` from
`not_attempted` from `unverifiable` only by parsing a sentence.

The chain is driven with the production code at every hop, as
`test_failure_classification_reaches_the_api` does for #1357, because the
defect it guards against is a value dropped by one constructor that does not
pass it:

    DelegationEvidencePort (double)  ->  delegation_failure  ->  DelegationFailedError
      ->  failed_phase_outcome  ->  FailExecutionCommand  ->  WorkflowExecutionAggregate
      ->  WorkflowFailedEvent   ->  detail projection     ->  WorkflowExecutionDetail
      ->  GET /executions/{id}  (ExecutionDetailResponse, serialised as JSON)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration import (
    DelegationAttempt,
    DelegationFailureReason,
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.ports import DelegationOutcome
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_delegation import (
    delegation_failure,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    failed_phase_outcome,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
    from syn_api.routes.executions.models import ExecutionDetailResponse

pytestmark = pytest.mark.unit

WORKFLOW_ID = "wf-894"
PHASE_ID = "implement"
_STARTED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
_FAILED_AT = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)

#: What the journal held for the run #894 records: a Codex delegate that could
#: not start, and a second that started and exited non-zero.
_JOURNAL = (
    DelegationAttempt(
        delegate_id="child-launch",
        target_harness="codex",
        outcome=DelegationOutcome.FAILED,
        exit_code=127,
        reason="binary_missing",
    ),
    DelegationAttempt(
        delegate_id="child-exit",
        target_harness="codex",
        outcome=DelegationOutcome.FAILED,
        exit_code=1,
    ),
)


@dataclass
class _Journal:
    held: tuple[DelegationAttempt, ...]

    async def attempts(self, workspace: ManagedWorkspace) -> tuple[DelegationAttempt, ...]:
        return self.held


@dataclass
class _Manager:
    store: InMemoryProjectionStore
    workflow_execution_detail: WorkflowExecutionDetailProjection


async def _served_detail(
    monkeypatch: pytest.MonkeyPatch, execution_id: str, held: tuple[DelegationAttempt, ...]
) -> ExecutionDetailResponse:
    error = await delegation_failure(
        _Journal(held), MagicMock(), phase_id=PHASE_ID, allow_delegation=True
    )
    assert error is not None
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
            workflow_name="delegating",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.fail_execution(outcome.as_command(execution_id, completed_phases=0, total_phases=1))
    failed = aggregate.get_uncommitted_events()[-1].event
    assert failed.event_type == "WorkflowFailed"

    store = InMemoryProjectionStore()
    detail = WorkflowExecutionDetailProjection(store)
    started = WorkflowExecutionStartedEvent(
        workflow_id=WORKFLOW_ID,
        execution_id=execution_id,
        workflow_name="delegating",
        started_at=_STARTED_AT,
        total_phases=1,
        inputs={},
    )
    await detail.on_workflow_execution_started(started.model_dump(mode="json"))
    # As the event store hands it back: JSON, not the in-process model.
    await detail.on_workflow_failed(failed.model_dump(mode="json"))

    from syn_api import _wiring
    from syn_api.routes.executions import queries

    async def _noop_connect() -> None:
        return None

    manager = _Manager(store=store, workflow_execution_detail=detail)
    monkeypatch.setattr(queries, "ensure_connected", _noop_connect)
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: manager)
    monkeypatch.setattr(_wiring, "get_projection_mgr", lambda: manager)
    response = await queries.get_execution_endpoint(execution_id)
    return response


@pytest.mark.asyncio
async def test_failed_delegates_reach_the_api_with_reason_and_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await _served_detail(monkeypatch, "exec-894-failed", _JOURNAL)
    # Serialised as the HTTP response is, so the assertion is on the wire shape.
    body = response.model_dump(mode="json")

    assert body["failure_classification"] == FailureClassification.PLATFORM.value
    assert body["delegation_failure"] == {
        "reason": DelegationFailureReason.FAILED.value,
        "attempts": [attempt.model_dump(mode="json") for attempt in _JOURNAL],
        "detail": None,
    }


@pytest.mark.asyncio
async def test_no_delegate_at_all_reaches_the_api_as_not_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (await _served_detail(monkeypatch, "exec-894-none", ())).model_dump(mode="json")

    assert body["delegation_failure"] == {
        "reason": DelegationFailureReason.NOT_ATTEMPTED.value,
        "attempts": [],
        "detail": None,
    }
