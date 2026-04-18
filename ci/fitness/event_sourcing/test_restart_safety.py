"""Fitness function: restart safety (replay produces zero side effects).

Restarting the coordinator with historical events in the event store
must never trigger process_pending() during catch-up replay. This is
the fundamental invariant that prevents replay storms - the class of
bug where restarting the service with N open PRs creates N spurious
workflow executions.

Principle: 5. Startup Contract + 3. Replay Safety
(docs/architecture/architectural-fitness.md)

Uses ESP's ProcessManagerScenario to verify the invariant structurally.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    ProcessManager,
    ProjectionCheckpointStore,
    ProjectionResult,
)
from event_sourcing.testing import ProcessManagerScenario


class _StubEvent(DomainEvent):
    """Minimal event for testing replay safety."""

    trigger_id: str = "test-trigger"
    execution_id: str = "test-execution"


class _TrackingProcessManager(ProcessManager):
    """Minimal ProcessManager that tracks calls for testing.

    handle_event() always succeeds (writes nothing).
    process_pending() increments a counter (should never be called during replay).
    """

    SIDE_EFFECTS_ALLOWED: ClassVar[bool] = True
    _pending_count: int = 0

    def get_name(self) -> str:
        return "test_tracking_pm"

    def get_version(self) -> int:
        return 1

    def get_subscribed_event_types(self) -> set[str] | None:
        return {"test.StubEvent"}

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,
    ) -> ProjectionResult:
        return ProjectionResult.SUCCESS

    async def process_pending(self) -> int:
        self._pending_count += 1
        return 1

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        return str(todo_item.get("execution_id", ""))


def _make_envelope(nonce: int) -> EventEnvelope[DomainEvent]:
    """Create a test event envelope with the given global_nonce."""
    return EventEnvelope(
        event=_StubEvent(trigger_id=f"trigger-{nonce}", execution_id=f"exec-{nonce}"),
        metadata=EventMetadata(
            stream_name=f"trigger-{nonce}",
            aggregate_id=f"trigger-{nonce}",
            aggregate_type="TriggerRule",
            aggregate_nonce=1,
            global_nonce=nonce,
            event_type="test.StubEvent",
        ),
    )


@pytest.mark.architecture
class TestRestartSafety:
    """Replay must never trigger side effects via process_pending()."""

    @pytest.mark.asyncio
    async def test_replay_does_not_trigger_process_pending(self) -> None:
        """Catch-up replay of N events must produce zero process_pending() calls.

        This is the core invariant: when the coordinator replays historical
        events after a restart, ProcessManager.process_pending() must never
        be called. Only the projection side (handle_event) runs during replay.
        """
        pm = _TrackingProcessManager()
        scenario = ProcessManagerScenario(pm)

        # Simulate replaying 50 historical events (a typical restart scenario)
        events = [_make_envelope(i) for i in range(50)]
        await scenario.given_events(events)

        assert scenario.process_pending_call_count == 0, (
            f"process_pending() was called {scenario.process_pending_call_count} times "
            "during catch-up replay. This would cause a replay storm in production - "
            "every historical TriggerFired event would re-dispatch a workflow execution. "
            "The coordinator must gate process_pending() on is_catching_up == False."
        )

    @pytest.mark.asyncio
    async def test_checkpoint_loss_full_replay_is_safe(self) -> None:
        """Full replay from position 0 (simulating checkpoint loss) is safe.

        Even when all checkpoints are lost and the coordinator must replay
        the entire event store from the beginning, process_pending() must
        not be called.
        """
        pm = _TrackingProcessManager()
        scenario = ProcessManagerScenario(pm)

        # Simulate full replay from position 0 (100 events, heavier load)
        events = [_make_envelope(i) for i in range(100)]
        await scenario.given_events(events)

        assert scenario.process_pending_call_count == 0, (
            "process_pending() was called during full replay from position 0. "
            "Even with complete checkpoint loss, replay must be safe. "
            "Check that DispatchContext.is_catching_up is True during catch-up."
        )

    @pytest.mark.asyncio
    async def test_live_event_does_trigger_process_pending(self) -> None:
        """After catch-up completes, live events MUST trigger process_pending().

        This is the complementary invariant: process_pending() must be called
        for live events. Without this, the ProcessManager never dispatches work.
        """
        pm = _TrackingProcessManager()
        scenario = ProcessManagerScenario(pm)

        # Replay history
        events = [_make_envelope(i) for i in range(10)]
        await scenario.given_events(events)

        # Then process a live event
        live_envelope = _make_envelope(100)
        result = await scenario.when_live_event(live_envelope)

        assert result == ProjectionResult.SUCCESS
        # process_pending is called inside when_live_event after handle_event succeeds
        assert pm._pending_count > 0, (  # testing internal state
            "process_pending() was NOT called for a live event. "
            "Live events must trigger the processor side of the ProcessManager."
        )
