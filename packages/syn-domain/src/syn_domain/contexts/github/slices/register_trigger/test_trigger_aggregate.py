"""Tests for TriggerRuleAggregate state transitions."""

from __future__ import annotations

import pytest

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from syn_domain.contexts.github.domain.commands.DeleteTriggerCommand import (
    DeleteTriggerCommand,
)
from syn_domain.contexts.github.domain.commands.PauseTriggerCommand import (
    PauseTriggerCommand,
)
from syn_domain.contexts.github.domain.commands.RecordTriggerFiredCommand import (
    RecordTriggerFiredCommand,
)
from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from syn_domain.contexts.github.domain.commands.ResumeTriggerCommand import (
    ResumeTriggerCommand,
)
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
    TriggerFiredEvent,
)
from syn_domain.contexts.github.domain.events.TriggerRegisteredEvent import (
    TriggerRegisteredEvent,
)


def _make_register_command(**overrides) -> RegisterTriggerCommand:
    """Create a RegisterTriggerCommand with sensible defaults."""
    defaults = {
        "name": "ci-self-heal",
        "event": "check_run.completed",
        "conditions": ({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        "repository": "syntropic137/my-project",
        "installation_id": "inst-123",
        "workflow_id": "ci-fix-workflow",
        "input_mapping": (("repository", "repository.full_name"),),
        "config": (("max_attempts", 3), ("daily_limit", 20)),
        "created_by": "test-user",
    }
    defaults.update(overrides)
    return RegisterTriggerCommand(**defaults)


def _register_aggregate(**overrides) -> TriggerRuleAggregate:
    """Create and register a TriggerRuleAggregate."""
    cmd = _make_register_command(**overrides)
    aggregate = TriggerRuleAggregate()
    aggregate.register(cmd)
    return aggregate


@pytest.mark.unit
class TestTriggerRuleAggregateRegister:
    """Tests for trigger registration."""

    def test_register_creates_aggregate_with_correct_state(self) -> None:
        """Test that register creates an aggregate with the right fields."""
        aggregate = _register_aggregate()

        assert aggregate.trigger_id.startswith("tr-")
        assert aggregate.name == "ci-self-heal"
        assert aggregate.status == TriggerStatus.ACTIVE
        assert aggregate.event == "check_run.completed"
        assert aggregate.repository == "syntropic137/my-project"
        assert aggregate.workflow_id == "ci-fix-workflow"
        assert aggregate.created_by == "test-user"
        assert aggregate.fire_count == 0
        assert len(aggregate.conditions) == 1
        assert aggregate.conditions[0].field == "check_run.conclusion"
        assert aggregate.conditions[0].operator == "eq"
        assert aggregate.conditions[0].value == "failure"

    def test_register_emits_trigger_registered_event(self) -> None:
        """Test that register emits a TriggerRegisteredEvent."""
        aggregate = _register_aggregate()

        uncommitted = aggregate.get_uncommitted_events()
        assert len(uncommitted) == 1
        event = uncommitted[0].event
        assert isinstance(event, TriggerRegisteredEvent)
        assert event.trigger_id == aggregate.trigger_id
        assert event.name == "ci-self-heal"
        assert event.repository == "syntropic137/my-project"


@pytest.mark.unit
class TestTriggerRuleAggregatePause:
    """Tests for trigger pausing."""

    def test_pause_active_trigger(self) -> None:
        """Test pausing an active trigger changes status."""
        aggregate = _register_aggregate()
        aggregate.mark_events_as_committed()

        cmd = PauseTriggerCommand(
            trigger_id=aggregate.trigger_id, paused_by="admin", reason="maintenance"
        )
        aggregate.pause(cmd)

        assert aggregate.status == TriggerStatus.PAUSED
        uncommitted = aggregate.get_uncommitted_events()
        assert len(uncommitted) == 1

    def test_pause_already_paused_raises(self) -> None:
        """Test pausing an already-paused trigger raises ValueError."""
        aggregate = _register_aggregate()
        aggregate.pause(PauseTriggerCommand(trigger_id=aggregate.trigger_id, paused_by="admin"))

        with pytest.raises(ValueError, match="Cannot pause"):
            aggregate.pause(PauseTriggerCommand(trigger_id=aggregate.trigger_id, paused_by="admin"))

    def test_pause_deleted_raises(self) -> None:
        """Test pausing a deleted trigger raises ValueError."""
        aggregate = _register_aggregate()
        aggregate.delete(DeleteTriggerCommand(trigger_id=aggregate.trigger_id, deleted_by="admin"))

        with pytest.raises(ValueError, match="Cannot pause"):
            aggregate.pause(PauseTriggerCommand(trigger_id=aggregate.trigger_id, paused_by="admin"))


@pytest.mark.unit
class TestTriggerRuleAggregateResume:
    """Tests for trigger resuming."""

    def test_resume_paused_trigger(self) -> None:
        """Test resuming a paused trigger returns to active."""
        aggregate = _register_aggregate()
        aggregate.pause(PauseTriggerCommand(trigger_id=aggregate.trigger_id, paused_by="admin"))
        aggregate.mark_events_as_committed()

        aggregate.resume(ResumeTriggerCommand(trigger_id=aggregate.trigger_id, resumed_by="admin"))

        assert aggregate.status == TriggerStatus.ACTIVE
        uncommitted = aggregate.get_uncommitted_events()
        assert len(uncommitted) == 1

    def test_resume_active_raises(self) -> None:
        """Test resuming an already-active trigger raises ValueError."""
        aggregate = _register_aggregate()

        with pytest.raises(ValueError, match="Cannot resume"):
            aggregate.resume(
                ResumeTriggerCommand(trigger_id=aggregate.trigger_id, resumed_by="admin")
            )


@pytest.mark.unit
class TestTriggerRuleAggregateDelete:
    """Tests for trigger deletion."""

    def test_delete_trigger(self) -> None:
        """Test deleting a trigger sets status to DELETED."""
        aggregate = _register_aggregate()
        aggregate.mark_events_as_committed()

        aggregate.delete(DeleteTriggerCommand(trigger_id=aggregate.trigger_id, deleted_by="admin"))

        assert aggregate.status == TriggerStatus.DELETED
        uncommitted = aggregate.get_uncommitted_events()
        assert len(uncommitted) == 1

    def test_delete_already_deleted_raises(self) -> None:
        """Test deleting an already-deleted trigger raises ValueError."""
        aggregate = _register_aggregate()
        aggregate.delete(DeleteTriggerCommand(trigger_id=aggregate.trigger_id, deleted_by="admin"))

        with pytest.raises(ValueError, match="already deleted"):
            aggregate.delete(
                DeleteTriggerCommand(trigger_id=aggregate.trigger_id, deleted_by="admin")
            )


@pytest.mark.unit
class TestTriggerRuleAggregateFireAndCanFire:
    """Tests for firing and can_fire checks."""

    def test_record_fired_increments_count(self) -> None:
        """Test that record_fired increments fire_count and emits event."""
        aggregate = _register_aggregate()
        aggregate.mark_events_as_committed()

        cmd = RecordTriggerFiredCommand(
            trigger_id=aggregate.trigger_id,
            execution_id="exec-abc",
            webhook_delivery_id="del-123",
            event_type="check_run.completed",
            repository="syntropic137/my-project",
            workflow_id="ci-fix-workflow",
            pr_number=42,
            payload_summary={"check_name": "lint"},
        )
        aggregate.record_fired(cmd)

        assert aggregate.fire_count == 1
        uncommitted = aggregate.get_uncommitted_events()
        assert len(uncommitted) == 1
        event = uncommitted[0].event
        assert isinstance(event, TriggerFiredEvent)
        assert event.execution_id == "exec-abc"
        assert event.pr_number == 42
        assert event.workflow_id == "ci-fix-workflow"

    def test_can_fire_only_when_active(self) -> None:
        """Test that can_fire returns True only when status is active."""
        aggregate = _register_aggregate()
        assert aggregate.can_fire() is True

        aggregate.pause(PauseTriggerCommand(trigger_id=aggregate.trigger_id, paused_by="admin"))
        assert aggregate.can_fire() is False

        aggregate.resume(ResumeTriggerCommand(trigger_id=aggregate.trigger_id, resumed_by="admin"))
        assert aggregate.can_fire() is True

        aggregate.delete(DeleteTriggerCommand(trigger_id=aggregate.trigger_id, deleted_by="admin"))
        assert aggregate.can_fire() is False


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
