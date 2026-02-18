"""Tests for subagent event type constants.

Moved from syn_tests/integration/test_subagent_observability.py (issue #115).
"""

from __future__ import annotations

import pytest

from syn_shared.events import SUBAGENT_STARTED, SUBAGENT_STOPPED


@pytest.mark.unit
class TestSubagentEventTypes:
    """Test subagent event type constants."""

    def test_subagent_started_constant(self) -> None:
        """SUBAGENT_STARTED constant is correctly defined."""
        assert SUBAGENT_STARTED == "subagent_started"

    def test_subagent_stopped_constant(self) -> None:
        """SUBAGENT_STOPPED constant is correctly defined."""
        assert SUBAGENT_STOPPED == "subagent_stopped"
