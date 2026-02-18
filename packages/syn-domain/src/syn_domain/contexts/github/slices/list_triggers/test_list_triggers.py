"""Tests for list_triggers query slice."""

from __future__ import annotations

import pytest

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import (
    TriggerStatus,
)
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import (
    TriggerFiredEvent,
)
from syn_domain.contexts.github.domain.events.TriggerPausedEvent import (
    TriggerPausedEvent,
)
from syn_domain.contexts.github.domain.events.TriggerRegisteredEvent import (
    TriggerRegisteredEvent,
)
from syn_domain.contexts.github.slices.list_triggers.projection import (
    TriggerRuleProjection,
)


def _make_registered_event(trigger_id: str, **overrides) -> TriggerRegisteredEvent:
    """Create a TriggerRegisteredEvent with defaults."""
    defaults = {
        "trigger_id": trigger_id,
        "name": f"trigger-{trigger_id}",
        "event": "check_run.completed",
        "repository": "syntropic137/test",
        "installation_id": "inst-1",
        "workflow_id": "ci-fix-workflow",
        "created_by": "test",
    }
    defaults.update(overrides)
    return TriggerRegisteredEvent(**defaults)


@pytest.mark.unit
class TestTriggerRuleProjection:
    """Tests for TriggerRuleProjection."""

    def test_handle_trigger_registered(self) -> None:
        """Test projecting a TriggerRegistered event."""
        projection = TriggerRuleProjection()
        event = _make_registered_event("tr-1")

        rule = projection.handle_trigger_registered(event)

        assert rule.trigger_id == "tr-1"
        assert rule.status == TriggerStatus.ACTIVE
        assert projection.get("tr-1") is not None

    def test_handle_trigger_paused(self) -> None:
        """Test projecting a TriggerPaused event."""
        projection = TriggerRuleProjection()
        projection.handle_trigger_registered(_make_registered_event("tr-1"))

        rule = projection.handle_trigger_paused(
            TriggerPausedEvent(trigger_id="tr-1", paused_by="admin")
        )

        assert rule is not None
        assert rule.status == TriggerStatus.PAUSED

    def test_handle_trigger_fired_updates_count(self) -> None:
        """Test that TriggerFired updates fire_count and last_fired_at."""
        projection = TriggerRuleProjection()
        projection.handle_trigger_registered(_make_registered_event("tr-1"))

        rule = projection.handle_trigger_fired(
            TriggerFiredEvent(
                trigger_id="tr-1",
                execution_id="exec-1",
                github_event_type="check_run.completed",
            )
        )

        assert rule is not None
        assert rule.fire_count == 1
        assert rule.last_fired_at is not None

    def test_list_all_with_filters(self) -> None:
        """Test listing triggers with filters."""
        projection = TriggerRuleProjection()
        projection.handle_trigger_registered(
            _make_registered_event("tr-1", repository="org/repo-a")
        )
        projection.handle_trigger_registered(
            _make_registered_event("tr-2", repository="org/repo-b")
        )
        projection.handle_trigger_registered(
            _make_registered_event("tr-3", repository="org/repo-a")
        )
        projection.handle_trigger_paused(TriggerPausedEvent(trigger_id="tr-3", paused_by="admin"))

        all_rules = projection.list_all()
        assert len(all_rules) == 3

        repo_a = projection.list_all(repository="org/repo-a")
        assert len(repo_a) == 2

        active = projection.list_all(status="active")
        assert len(active) == 2

        repo_a_active = projection.list_all(repository="org/repo-a", status="active")
        assert len(repo_a_active) == 1
