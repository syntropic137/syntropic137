"""A trigger may not dispatch a workflow whose failure streak hit the threshold (#1569).

Driven through the real ``WorkflowDispatchProjection`` and the real
``FailureStreakProjection``, fed real events and wired the way
``create_coordinator_service`` wires them, with only the execution service
faked. The rule is tested alone in the slice; this tests the hop that consumes
it: that a refusal reaches the trigger's dispatch record and stops the start.
"""

from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from event_sourcing.core.event import EventEnvelope, EventMetadata
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from event_sourcing.stores.memory_projection import MemoryProjectionStore

if TYPE_CHECKING:
    from event_sourcing import DomainEvent

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.slices.dispatch_triggered_workflow.projection import (
    WorkflowDispatchProjection,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    FailureClassification,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowCompletedEvent import (
    WorkflowCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.failure_streak import (
    FailureStreakProjection,
    TriggerDispatchStreakCheck,
)

pytestmark = pytest.mark.unit

_WORKFLOW = "wf-ci-self-healing"
_T0 = datetime(2026, 11, 16, tzinfo=UTC)
_nonce = count(1)


class _RecordingExecutionService:
    """Stands in for the dispatcher. Records every workflow it was asked to start."""

    def __init__(self) -> None:
        self.started: list[str] = []

    async def run_workflow(self, workflow_id: str, execution_id: str, **_: object) -> None:
        self.started.append(execution_id)

    def holds_execution(self, _execution_id: str) -> bool:
        return False


class _Fixture:
    def __init__(self, threshold: int) -> None:
        self.store = MemoryProjectionStore()
        self.streaks = FailureStreakProjection(self.store)
        self.service = _RecordingExecutionService()
        self.dispatch = WorkflowDispatchProjection(
            execution_service=self.service,  # type: ignore[arg-type]  # the double takes **kwargs
            store=self.store,
            max_dispatches_per_hour=0,
            dispatch_refusals=TriggerDispatchStreakCheck(self.streaks, threshold),
        )

    async def _deliver(self, projection: object, event: DomainEvent, aggregate: str) -> None:
        nonce = next(_nonce)
        envelope = EventEnvelope(
            event=event,
            metadata=EventMetadata(
                event_type=event.event_type,
                aggregate_id=aggregate,
                aggregate_type=aggregate,
                aggregate_nonce=nonce,
                global_nonce=nonce,
            ),
        )
        await projection.handle_event(envelope, MemoryCheckpointStore())  # type: ignore[attr-defined]

    async def failures(self, *execution_ids: str) -> None:
        for execution_id in execution_ids:
            await self._deliver(
                self.streaks,
                WorkflowFailedEvent(
                    workflow_id=_WORKFLOW,
                    execution_id=execution_id,
                    failed_at=_T0,
                    error_message="boom",
                    failure_classification=FailureClassification.PLATFORM,
                    completed_phases=0,
                    total_phases=1,
                ),
                "WorkflowExecution",
            )

    async def a_completion(self, execution_id: str) -> None:
        await self._deliver(
            self.streaks,
            WorkflowCompletedEvent(
                workflow_id=_WORKFLOW,
                execution_id=execution_id,
                completed_at=_T0,
                total_phases=1,
                completed_phases=1,
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                total_duration_seconds=1.0,
                artifact_ids=[],
            ),
            "WorkflowExecution",
        )

    async def a_trigger_fires(self, execution_id: str) -> None:
        await self._deliver(
            self.dispatch,
            TriggerFiredEvent(
                trigger_id="trg-1",
                execution_id=execution_id,
                workflow_id=_WORKFLOW,
                workflow_inputs={},
                github_event_type="check_run.completed",
            ),
            "TriggerRule",
        )
        await self.dispatch.process_pending()

    async def record(self, execution_id: str) -> tuple[str, str]:
        found = await self.store.get(WorkflowDispatchProjection.PROJECTION_NAME, execution_id)
        assert found is not None
        return str(found.get("status")), str(found.get("status_reason", ""))


async def test_below_the_threshold_a_trigger_dispatches() -> None:
    fx = _Fixture(threshold=3)
    await fx.failures("e1", "e2")

    await fx.a_trigger_fires("t1")

    assert fx.service.started == ["t1"]


async def test_at_the_threshold_a_trigger_is_refused_with_the_reason() -> None:
    fx = _Fixture(threshold=3)
    await fx.failures("e1", "e2", "e3")

    await fx.a_trigger_fires("t1")

    assert fx.service.started == []
    status, reason = await fx.record("t1")
    assert status == "failed"
    assert reason.startswith("failure_streak: ")
    assert "failed 3 times" in reason
    assert "threshold of 3" in reason
    assert "e1, e2, e3" in reason


async def test_a_refused_trigger_is_not_offered_again() -> None:
    fx = _Fixture(threshold=1)
    await fx.failures("e1")
    await fx.a_trigger_fires("t1")
    await fx.a_completion("manual-1")

    await fx.dispatch.process_pending()

    assert fx.service.started == []


async def test_threshold_zero_never_refuses() -> None:
    fx = _Fixture(threshold=0)
    await fx.failures("e1", "e2", "e3", "e4", "e5", "e6")

    await fx.a_trigger_fires("t1")

    assert fx.service.started == ["t1"]


async def test_a_completion_lets_triggers_dispatch_again() -> None:
    fx = _Fixture(threshold=2)
    await fx.failures("e1", "e2")
    await fx.a_trigger_fires("t1")
    assert fx.service.started == []

    # The way out: a manual run that completes resets the streak.
    await fx.a_completion("manual-1")
    await fx.a_trigger_fires("t2")

    assert fx.service.started == ["t2"]


def test_manual_start_paths_never_consult_the_streak_check() -> None:
    """A manual run at the threshold proceeds because nothing on its path refuses it.

    Refusing it too would leave the template refused forever: a completion is
    the only thing that resets a streak. So the check is wired into the trigger
    dispatcher and nowhere else, and this pins that.
    """
    repo = Path(__file__).resolve().parents[3]
    users: list[str] = []
    for root in ("apps/syn-api/src", "packages/syn-adapters/src", "packages/syn-domain/src"):
        for path in (repo / root).rglob("*.py"):
            if path.name.startswith("test_") or "failure_streak" in path.parts:
                continue
            tree = ast.parse(path.read_text())
            if any(
                isinstance(node, ast.Name) and node.id == "TriggerDispatchStreakCheck"
                for node in ast.walk(tree)
            ):
                users.append(path.relative_to(repo).as_posix())

    assert users == ["packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py"]


async def test_the_registered_dispatcher_reads_the_registered_streak_at_its_threshold() -> None:
    """The coordinator hands the dispatcher the threshold and the streaks it feeds.

    A dispatcher built without the threshold would pass every test above and
    refuse nothing in production.
    """
    from syn_adapters.subscriptions import create_coordinator_service

    store = MemoryProjectionStore()
    service = create_coordinator_service(
        event_store=object(),  # type: ignore[arg-type]  # never touched before start()
        projection_store=store,  # type: ignore[arg-type]  # the in-memory store
        execution_service=_RecordingExecutionService(),  # type: ignore[arg-type]
        failure_streak_threshold=2,
    )
    projections = service._projections
    (streaks,) = [p for p in projections if isinstance(p, FailureStreakProjection)]
    (dispatch,) = [p for p in projections if isinstance(p, WorkflowDispatchProjection)]
    fx = _Fixture(threshold=0)
    fx.store, fx.streaks, fx.dispatch = store, streaks, dispatch
    fx.service = dispatch._execution_service  # type: ignore[assignment]  # the double above

    await fx.failures("e1", "e2")
    await fx.a_trigger_fires("t1")

    assert fx.service.started == []
    assert (await fx.record("t1"))[1].startswith("failure_streak: ")


def test_the_api_passes_the_configured_threshold_to_the_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SYN_POLLING_FAILURE_STREAK_THRESHOLD`` reaches ``create_coordinator_service``."""
    import syn_adapters.subscriptions as subscriptions
    from syn_api import _wiring
    from syn_shared.settings import reset_settings

    passed: list[object] = []

    def capture(*, failure_streak_threshold: int = -1, **_: object) -> None:
        passed.append(failure_streak_threshold)

    monkeypatch.setenv("SYN_POLLING_FAILURE_STREAK_THRESHOLD", "7")
    monkeypatch.setattr(subscriptions, "create_coordinator_service", capture)
    monkeypatch.setattr(_wiring, "get_event_store_client", lambda: None)
    monkeypatch.setattr(_wiring, "_get_budget_checker", lambda: None)
    reset_settings()
    try:
        _wiring.get_subscription_coordinator()
    finally:
        monkeypatch.delenv("SYN_POLLING_FAILURE_STREAK_THRESHOLD")
        reset_settings()

    assert passed == [7]
