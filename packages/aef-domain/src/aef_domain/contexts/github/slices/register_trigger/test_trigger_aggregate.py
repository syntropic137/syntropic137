"""Tests for TriggerRuleAggregate state transitions."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from aef_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)
from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from aef_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from aef_domain.contexts.github.domain.events.TriggerDeletedEvent import (
    TriggerDeletedEvent,
)
from aef_domain.contexts.github.domain.events.TriggerFiredEvent import (
    TriggerFiredEvent,
)
from aef_domain.contexts.github.domain.events.TriggerPausedEvent import (
    TriggerPausedEvent,
)
from aef_domain.contexts.github.domain.events.TriggerRegisteredEvent import (
    TriggerRegisteredEvent,
)
from aef_domain.contexts.github.domain.events.TriggerResumedEvent import (
    TriggerResumedEvent,
)


def _make_register_command(**overrides) -> RegisterTriggerCommand:
    """Create a RegisterTriggerCommand with sensible defaults."""
    defaults = {
        "name": "ci-self-heal",
        "event": "check_run.completed",
        "conditions": ({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        "repository": "AgentParadise/my-project",
        "installation_id": "inst-123",
        "workflow_id": "ci-fix-workflow",
        "input_mapping": (("repository", "repository.full_name"),),
        "config": (("max_attempts", 3), ("daily_limit", 20)),
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return RegisterTriggerCommand(**defaults)


@pytest.mark.unit
class TestTriggerRuleAggregateRegister:
    """Tests for trigger registration."""

    def test_register_creates_aggregate_with_correct_state(self) -> None:
        """Test that register creates an aggregate with the right fields."""
        cmd = _make_register_command()
        aggregate = TriggerRuleAggregate.register(cmd)

        assert aggregate.trigger_id.startswith("tr-")
        assert aggregate.name == "ci-self-heal"
        assert aggregate.status == TriggerStatus.ACTIVE
        assert aggregate.event == "check_run.completed"
        assert aggregate.repository == "AgentParadise/my-project"
        assert aggregate.workflow_id == "ci-fix-workflow"
        assert aggregate.created_by == "test-user"
        assert aggregate.fire_count == 0
        assert len(aggregate.conditions) == 1
        assert aggregate.conditions[0].field == "check_run.conclusion"
        assert aggregate.conditions[0].operator == "eq"
        assert aggregate.conditions[0].value == "failure"

    def test_register_emits_trigger_registered_event(self) -> None:
        """Test that register emits a TriggerRegisteredEvent."""
        cmd = _make_register_command()
        aggregate = TriggerRuleAggregate.register(cmd)

        assert len(aggregate.pending_events) == 1
        event = aggregate.pending_events[0]
        assert isinstance(event, TriggerRegisteredEvent)
        assert event.trigger_id == aggregate.trigger_id
        assert event.name == "ci-self-heal"
        assert event.repository == "AgentParadise/my-project"


@pytest.mark.unit
class TestTriggerRuleAggregatePause:
    """Tests for trigger pausing."""

    def test_pause_active_trigger_returns_event(self) -> None:
        """Test pausing an active trigger returns a TriggerPausedEvent."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.pending_events.clear()

        event = aggregate.pause(paused_by="admin", reason="maintenance")

        assert event is not None
        assert isinstance(event, TriggerPausedEvent)
        assert event.trigger_id == aggregate.trigger_id
        assert event.paused_by == "admin"
        assert event.reason == "maintenance"
        assert aggregate.status == TriggerStatus.PAUSED

    def test_pause_already_paused_returns_none(self) -> None:
        """Test pausing an already-paused trigger returns None."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.pause(paused_by="admin")

        result = aggregate.pause(paused_by="admin")
        assert result is None

    def test_pause_deleted_returns_none(self) -> None:
        """Test pausing a deleted trigger returns None."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.delete(deleted_by="admin")

        result = aggregate.pause(paused_by="admin")
        assert result is None


@pytest.mark.unit
class TestTriggerRuleAggregateResume:
    """Tests for trigger resuming."""

    def test_resume_paused_trigger_returns_event(self) -> None:
        """Test resuming a paused trigger returns a TriggerResumedEvent."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.pause(paused_by="admin")
        aggregate.pending_events.clear()

        event = aggregate.resume(resumed_by="admin")

        assert event is not None
        assert isinstance(event, TriggerResumedEvent)
        assert event.trigger_id == aggregate.trigger_id
        assert aggregate.status == TriggerStatus.ACTIVE

    def test_resume_active_returns_none(self) -> None:
        """Test resuming an already-active trigger returns None."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())

        result = aggregate.resume(resumed_by="admin")
        assert result is None


@pytest.mark.unit
class TestTriggerRuleAggregateDelete:
    """Tests for trigger deletion."""

    def test_delete_trigger_returns_event(self) -> None:
        """Test deleting a trigger returns a TriggerDeletedEvent."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.pending_events.clear()

        event = aggregate.delete(deleted_by="admin")

        assert event is not None
        assert isinstance(event, TriggerDeletedEvent)
        assert event.trigger_id == aggregate.trigger_id
        assert aggregate.status == TriggerStatus.DELETED

    def test_delete_already_deleted_returns_none(self) -> None:
        """Test deleting an already-deleted trigger returns None."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.delete(deleted_by="admin")

        result = aggregate.delete(deleted_by="admin")
        assert result is None


@pytest.mark.unit
class TestTriggerRuleAggregateFireAndCanFire:
    """Tests for firing and can_fire checks."""

    def test_record_fired_increments_count(self) -> None:
        """Test that record_fired increments fire_count and emits event."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        aggregate.pending_events.clear()

        event = aggregate.record_fired(
            execution_id="exec-abc",
            webhook_delivery_id="del-123",
            event_type="check_run.completed",
            repository="AgentParadise/my-project",
            pr_number=42,
            payload_summary={"check_name": "lint"},
        )

        assert aggregate.fire_count == 1
        assert isinstance(event, TriggerFiredEvent)
        assert event.execution_id == "exec-abc"
        assert event.pr_number == 42

    def test_can_fire_only_when_active(self) -> None:
        """Test that can_fire returns True only when status is active."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())
        assert aggregate.can_fire() is True

        aggregate.pause(paused_by="admin")
        assert aggregate.can_fire() is False

        aggregate.resume(resumed_by="admin")
        assert aggregate.can_fire() is True

        aggregate.delete(deleted_by="admin")
        assert aggregate.can_fire() is False


@pytest.mark.unit
class TestTriggerRuleAggregateEventSourcing:
    """Tests for event sourcing reconstitution."""

    def test_from_events_reconstitutes_state(self) -> None:
        """Test that from_events rebuilds aggregate state correctly."""
        registered = TriggerRegisteredEvent(
            trigger_id="tr-abc123",
            name="test-trigger",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="AgentParadise/test",
            installation_id="inst-1",
            workflow_id="ci-fix-workflow",
            input_mapping={"repo": "repository.full_name"},
            config={"max_attempts": 3},
            created_by="test",
        )
        paused = TriggerPausedEvent(trigger_id="tr-abc123", paused_by="admin")
        resumed = TriggerResumedEvent(trigger_id="tr-abc123", resumed_by="admin")
        fired = TriggerFiredEvent(
            trigger_id="tr-abc123",
            execution_id="exec-1",
            webhook_delivery_id="del-1",
            event_type="check_run.completed",
            repository="AgentParadise/test",
        )

        aggregate = TriggerRuleAggregate.from_events([registered, paused, resumed, fired])

        assert aggregate is not None
        assert aggregate.trigger_id == "tr-abc123"
        assert aggregate.name == "test-trigger"
        assert aggregate.status == TriggerStatus.ACTIVE
        assert aggregate.fire_count == 1
        assert len(aggregate.conditions) == 1

    def test_from_events_empty_returns_none(self) -> None:
        """Test that from_events with empty list returns None."""
        assert TriggerRuleAggregate.from_events([]) is None

    def test_clear_pending_events(self) -> None:
        """Test that clear_pending_events returns and clears events."""
        aggregate = TriggerRuleAggregate.register(_make_register_command())

        assert len(aggregate.pending_events) == 1
        cleared = aggregate.clear_pending_events()
        assert len(cleared) == 1
        assert len(aggregate.pending_events) == 0


@pytest.mark.unit
class TestTriggerValueObjects:
    """Tests for value objects."""

    def test_trigger_condition_validation(self) -> None:
        """Test TriggerCondition validation."""
        with pytest.raises(ValueError, match="field is required"):
            TriggerCondition(field="", operator="eq", value="x")

        with pytest.raises(ValueError, match="operator must be one of"):
            TriggerCondition(field="x", operator="invalid", value="x")

    def test_trigger_config_defaults(self) -> None:
        """Test TriggerConfig default values."""
        config = TriggerConfig()
        assert config.max_attempts == 3
        assert config.budget_per_trigger_usd == 5.00
        assert config.daily_limit == 20
        assert config.cooldown_seconds == 300
        assert config.skip_if_sender_is_bot is True

    def test_trigger_config_validation(self) -> None:
        """Test TriggerConfig validation."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            TriggerConfig(max_attempts=0)

        with pytest.raises(ValueError, match="budget_per_trigger_usd must be > 0"):
            TriggerConfig(budget_per_trigger_usd=0)

        with pytest.raises(ValueError, match="daily_limit must be >= 1"):
            TriggerConfig(daily_limit=0)
