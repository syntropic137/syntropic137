"""Tests for trigger presets."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github._shared.trigger_presets import (
    PRESETS,
    create_preset_command,
)


@pytest.mark.unit
class TestTriggerPresets:
    """Tests for built-in trigger presets."""

    def test_self_healing_preset_creates_command(self) -> None:
        """Test creating a command from the self-healing preset."""
        cmd = create_preset_command(
            preset_name="self-healing",
            repository="AgentParadise/my-project",
            installation_id="inst-123",
            created_by="test-user",
        )

        assert cmd.name == "self-healing"
        assert cmd.event == "check_run.completed"
        assert cmd.repository == "AgentParadise/my-project"
        assert cmd.workflow_id == "self-heal-pr"
        assert len(cmd.conditions) == 2

    def test_review_fix_preset_creates_command(self) -> None:
        """Test creating a command from the review-fix preset."""
        cmd = create_preset_command(
            preset_name="review-fix",
            repository="AgentParadise/my-project",
        )

        assert cmd.name == "review-fix"
        assert cmd.event == "pull_request_review.submitted"
        assert cmd.workflow_id == "self-heal-pr"

    def test_unknown_preset_raises_error(self) -> None:
        """Test that an unknown preset name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown preset"):
            create_preset_command(
                preset_name="nonexistent",
                repository="AgentParadise/test",
            )

    def test_all_presets_are_valid(self) -> None:
        """Test that all preset names produce valid commands."""
        for name in PRESETS:
            cmd = create_preset_command(
                preset_name=name,
                repository="AgentParadise/test",
            )
            assert cmd.name
            assert cmd.event
            assert cmd.workflow_id
            assert cmd.repository == "AgentParadise/test"
