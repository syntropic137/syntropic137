"""Tests for D3: trigger dispatch lifecycle events."""

from __future__ import annotations

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.domain.commands import (
    RecordTriggerDispatchCompletedCommand,
    RecordTriggerDispatchFailedCommand,
    RecordTriggerFiredCommand,
    RegisterTriggerCommand,
)


def _make_active_trigger(trigger_id: str = "trig-1") -> TriggerRuleAggregate:
    """Create an active trigger aggregate for testing."""
    agg = TriggerRuleAggregate()
    cmd = RegisterTriggerCommand(
        aggregate_id=trigger_id,
        name="test-trigger",
        event="check_run.completed",
        repository="owner/repo",
        installation_id="inst-1",
        workflow_id="wf-1",
        created_by="test",
    )
    agg.register(cmd)
    return agg


class TestTriggerDispatchCompleted:
    def test_record_dispatch_completed(self) -> None:
        agg = _make_active_trigger()
        fire_cmd = RecordTriggerFiredCommand(
            trigger_id="trig-1", execution_id="exec-1", workflow_id="wf-1"
        )
        agg.record_fired(fire_cmd)
        cmd = RecordTriggerDispatchCompletedCommand(
            trigger_id="trig-1", execution_id="exec-1", workflow_id="wf-1"
        )
        agg.record_dispatch_completed(cmd)
        envelopes = agg.get_uncommitted_events()
        assert any(e.event.__class__.__name__ == "TriggerDispatchCompletedEvent" for e in envelopes)

    def test_completed_event_fields(self) -> None:
        agg = _make_active_trigger()
        fire_cmd = RecordTriggerFiredCommand(
            trigger_id="trig-1", execution_id="exec-1", workflow_id="wf-1"
        )
        agg.record_fired(fire_cmd)
        cmd = RecordTriggerDispatchCompletedCommand(
            trigger_id="trig-1", execution_id="exec-1", workflow_id="wf-1"
        )
        agg.record_dispatch_completed(cmd)
        envelope = next(
            e
            for e in agg.get_uncommitted_events()
            if e.event.__class__.__name__ == "TriggerDispatchCompletedEvent"
        )
        evt = envelope.event
        assert evt.trigger_id == "trig-1"
        assert evt.execution_id == "exec-1"
        assert evt.workflow_id == "wf-1"


class TestTriggerDispatchFailed:
    def test_record_dispatch_failed(self) -> None:
        agg = _make_active_trigger()
        fire_cmd = RecordTriggerFiredCommand(
            trigger_id="trig-1", execution_id="exec-1", workflow_id="wf-1"
        )
        agg.record_fired(fire_cmd)
        cmd = RecordTriggerDispatchFailedCommand(
            trigger_id="trig-1",
            execution_id="exec-1",
            workflow_id="wf-1",
            failure_reason="budget_exceeded",
        )
        agg.record_dispatch_failed(cmd)
        envelopes = agg.get_uncommitted_events()
        assert any(e.event.__class__.__name__ == "TriggerDispatchFailedEvent" for e in envelopes)

    def test_failed_event_contains_reason(self) -> None:
        agg = _make_active_trigger()
        fire_cmd = RecordTriggerFiredCommand(
            trigger_id="trig-1", execution_id="exec-1", workflow_id="wf-1"
        )
        agg.record_fired(fire_cmd)
        cmd = RecordTriggerDispatchFailedCommand(
            trigger_id="trig-1",
            execution_id="exec-1",
            workflow_id="wf-1",
            failure_reason="budget_exceeded",
        )
        agg.record_dispatch_failed(cmd)
        envelope = next(
            e
            for e in agg.get_uncommitted_events()
            if e.event.__class__.__name__ == "TriggerDispatchFailedEvent"
        )
        evt = envelope.event
        assert evt.failure_reason == "budget_exceeded"
        assert evt.trigger_id == "trig-1"
        assert evt.execution_id == "exec-1"
