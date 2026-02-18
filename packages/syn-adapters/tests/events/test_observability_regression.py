"""Regression tests for observability bugs.

These tests verify that known observability issues are caught before
they reach production. Each test is linked to a specific bug scenario
that was encountered during manual testing.

REGRESSION-001: Session tokens not counted
REGRESSION-002: Tool use not appearing in UI
REGRESSION-003: Cost not calculated
REGRESSION-004: Missing session lifecycle events
REGRESSION-005: Event type mismatch (producer vs consumer)

See ADR-033: Recording-Based Integration Testing
"""

from __future__ import annotations

from typing import Any

import pytest

from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.regression]  # Runs in CI


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def recording_events() -> dict[str, list[dict[str, Any]]]:
    """Load all available recordings for regression testing."""
    recording_names = [
        "simple-bash",
        "file-create",
        "file-read",
        "git-status",
        "multi-tool",
        "simple-question",
        "list-files",
    ]
    events_by_recording: dict[str, list[dict[str, Any]]] = {}

    for name in recording_names:
        try:
            adapter = RecordingEventStreamAdapter(name)
            events_by_recording[name] = adapter.get_events()
        except FileNotFoundError:
            pass

    if not events_by_recording:
        pytest.skip("No recordings available")

    return events_by_recording


# =============================================================================
# REGRESSION-001: Session tokens not counted
# =============================================================================


class TestRegressionTokenCounting:
    """Regression tests for token counting issues.

    Bug: Sessions would complete but show 0 tokens in the UI because
    token data wasn't being extracted from result events.
    """

    def test_result_has_usage_data(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-001a: Result events must have usage data for token counting."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            assert result is not None, f"{recording_name}: Missing result event"

            # The usage field is required for token counting
            assert "usage" in result, (
                f"REGRESSION-001a: {recording_name} result missing 'usage' field. "
                "UI will show 0 tokens."
            )

    def test_usage_has_token_counts(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-001b: Usage must have input/output token counts."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            if not result:
                continue

            usage = result.get("usage", {})

            # Either input_tokens or output_tokens must be present
            has_input = "input_tokens" in usage
            has_output = "output_tokens" in usage

            assert has_input or has_output, (
                f"REGRESSION-001b: {recording_name} usage missing token counts. "
                f"Got: {list(usage.keys())}"
            )

    def test_token_values_are_numeric(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-001c: Token counts must be numeric, not strings."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            if not result:
                continue

            usage = result.get("usage", {})

            for key in [
                "input_tokens",
                "output_tokens",
                "cache_creation_tokens",
                "cache_read_tokens",
            ]:
                if key in usage:
                    value = usage[key]
                    assert isinstance(value, int), (
                        f"REGRESSION-001c: {recording_name} {key} should be int, "
                        f"got {type(value).__name__}: {value}"
                    )


# =============================================================================
# REGRESSION-002: Tool use not appearing in UI
# =============================================================================


class TestRegressionToolTracking:
    """Regression tests for tool tracking issues.

    Bug: Tools would execute successfully but not appear in the UI
    because tool_use events weren't being extracted from assistant events.
    """

    def test_assistant_events_have_content(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-002a: Assistant events must have content for tool extraction."""
        for recording_name, events in recording_events.items():
            assistant_events = [e for e in events if e.get("type") == "assistant"]

            for i, event in enumerate(assistant_events):
                message = event.get("message", {})
                assert "content" in message, (
                    f"REGRESSION-002a: {recording_name} assistant[{i}] missing content. "
                    "Tool use won't be visible."
                )

    def test_tool_use_has_required_fields(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-002b: tool_use content must have id and name."""
        for recording_name, events in recording_events.items():
            for event in events:
                if event.get("type") != "assistant":
                    continue

                message = event.get("message", {})
                content = message.get("content", [])

                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        assert "id" in item, (
                            f"REGRESSION-002b: {recording_name} tool_use missing 'id'. "
                            "Can't correlate with tool_result."
                        )
                        assert "name" in item, (
                            f"REGRESSION-002b: {recording_name} tool_use missing 'name'. "
                            "Tool won't be identifiable."
                        )

    def test_tool_result_matches_tool_use(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-002c: tool_result must have tool_use_id for correlation."""
        for recording_name, events in recording_events.items():
            tool_use_ids: set[str] = set()
            tool_result_ids: set[str] = set()

            for event in events:
                message = event.get("message", {})
                content = message.get("content", [])

                for item in content:
                    if not isinstance(item, dict):
                        continue

                    if item.get("type") == "tool_use":
                        tool_use_id = item.get("id")
                        if tool_use_id:
                            tool_use_ids.add(tool_use_id)

                    if item.get("type") == "tool_result":
                        tool_use_id = item.get("tool_use_id")
                        if tool_use_id:
                            tool_result_ids.add(tool_use_id)

            # Every tool_result should reference a tool_use
            if tool_result_ids:
                orphan_results = tool_result_ids - tool_use_ids
                assert not orphan_results, (
                    f"REGRESSION-002c: {recording_name} has tool_results without matching "
                    f"tool_use: {orphan_results}"
                )


# =============================================================================
# REGRESSION-003: Cost not calculated
# =============================================================================


class TestRegressionCostCalculation:
    """Regression tests for cost calculation issues.

    Bug: Sessions would show $0.00 cost even though tokens were used
    because total_cost_usd wasn't being extracted from result events.
    """

    def test_result_has_cost(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-003a: Result events must have total_cost_usd."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            assert result is not None, f"{recording_name}: Missing result event"

            assert "total_cost_usd" in result, (
                f"REGRESSION-003a: {recording_name} result missing 'total_cost_usd'. "
                "UI will show $0.00."
            )

    def test_cost_is_numeric(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-003b: Cost must be numeric, not string."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            if not result:
                continue

            cost = result.get("total_cost_usd")
            assert isinstance(cost, (int, float)), (
                f"REGRESSION-003b: {recording_name} total_cost_usd should be numeric, "
                f"got {type(cost).__name__}: {cost}"
            )

    def test_cost_is_non_negative(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-003c: Cost should never be negative."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            if not result:
                continue

            cost = result.get("total_cost_usd", 0)
            assert cost >= 0, f"REGRESSION-003c: {recording_name} has negative cost: {cost}"


# =============================================================================
# REGRESSION-004: Missing session lifecycle events
# =============================================================================


class TestRegressionSessionLifecycle:
    """Regression tests for session lifecycle tracking.

    Bug: Sessions would appear as "running" forever because the
    system.init event wasn't being detected as session start.
    """

    def test_has_session_start_event(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-004a: Must have system.init for session start."""
        for recording_name, events in recording_events.items():
            init_events = [
                e for e in events if e.get("type") == "system" and e.get("subtype") == "init"
            ]

            assert len(init_events) >= 1, (
                f"REGRESSION-004a: {recording_name} missing system.init event. "
                "Session start won't be detected."
            )

    def test_has_session_end_event(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-004b: Must have result event for session completion."""
        for recording_name, events in recording_events.items():
            result_events = [e for e in events if e.get("type") == "result"]

            assert len(result_events) >= 1, (
                f"REGRESSION-004b: {recording_name} missing result event. "
                "Session will show as 'running' forever."
            )

    def test_init_before_result(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-004c: system.init must come before result."""
        for recording_name, events in recording_events.items():
            init_index = None
            result_index = None

            for i, event in enumerate(events):
                is_init = event.get("type") == "system" and event.get("subtype") == "init"
                if is_init and init_index is None:
                    init_index = i
                if event.get("type") == "result":
                    result_index = i

            if init_index is not None and result_index is not None:
                assert init_index < result_index, (
                    f"REGRESSION-004c: {recording_name} has result before init. "
                    "Event order is corrupted."
                )


# =============================================================================
# REGRESSION-005: Event type mismatch
# =============================================================================


class TestRegressionEventTypeConsistency:
    """Regression tests for event type consistency.

    Bug: Events would be recorded but not displayed because the
    event type used by the producer didn't match what the consumer expected.
    """

    def test_session_id_format_consistent(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-005a: session_id format must be consistent across events."""
        for recording_name, events in recording_events.items():
            session_ids = set()

            for event in events:
                session_id = event.get("session_id")
                if session_id:
                    session_ids.add(session_id)

            # All events from same session should have same session_id
            assert len(session_ids) <= 1, (
                f"REGRESSION-005a: {recording_name} has multiple session_ids: {session_ids}. "
                "Events won't correlate correctly."
            )

    def test_model_field_present(self, recording_events: dict[str, list[dict[str, Any]]]) -> None:
        """REGRESSION-005b: Model must be identifiable for cost calculation."""
        for recording_name, events in recording_events.items():
            init_events = [
                e for e in events if e.get("type") == "system" and e.get("subtype") == "init"
            ]

            for init in init_events:
                assert "model" in init, (
                    f"REGRESSION-005b: {recording_name} system.init missing 'model'. "
                    "Can't calculate cost-per-token."
                )

    def test_result_duration_present(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """REGRESSION-005c: Result must have duration for session metrics."""
        for recording_name, events in recording_events.items():
            result = next((e for e in events if e.get("type") == "result"), None)
            if not result:
                continue

            assert "duration_ms" in result or "duration_api_ms" in result, (
                f"REGRESSION-005c: {recording_name} result missing duration. "
                "Can't calculate session timing."
            )


# =============================================================================
# CRITICAL PATH TESTS
# =============================================================================


class TestCriticalObservabilityPath:
    """Tests for the critical observability data flow.

    These tests verify that the minimum required data for the UI
    can be extracted from every recording.
    """

    def test_can_build_session_summary(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Critical: Can build a complete session summary from events."""
        for recording_name, events in recording_events.items():
            # Extract session summary
            session_id = None
            model = None
            total_cost = None
            duration_ms = None
            tool_count = 0
            usage_data: dict[str, Any] = {}

            for event in events:
                if not session_id:
                    session_id = event.get("session_id")

                if event.get("type") == "system" and event.get("subtype") == "init":
                    model = event.get("model")

                if event.get("type") == "result":
                    total_cost = event.get("total_cost_usd")
                    duration_ms = event.get("duration_ms") or event.get("duration_api_ms")
                    usage_data = event.get("usage", {})

                if event.get("type") == "assistant":
                    message = event.get("message", {})
                    content = message.get("content", [])
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            tool_count += 1

            # Verify all critical fields are extractable
            assert session_id is not None, f"{recording_name}: Can't extract session_id"
            assert model is not None, f"{recording_name}: Can't extract model"
            assert total_cost is not None, f"{recording_name}: Can't extract total_cost"
            assert duration_ms is not None, f"{recording_name}: Can't extract duration"
            assert usage_data, f"{recording_name}: Can't extract usage data"

            # Verify numeric types
            assert isinstance(total_cost, (int, float)), f"{recording_name}: total_cost not numeric"
            assert isinstance(duration_ms, (int, float)), f"{recording_name}: duration not numeric"

    def test_can_extract_tool_timeline(
        self, recording_events: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Critical: Can extract tool timeline for UI display."""
        # Only test recordings that have tool use
        tool_recordings = ["simple-bash", "file-create", "git-status", "multi-tool", "list-files"]

        for recording_name in tool_recordings:
            if recording_name not in recording_events:
                continue

            events = recording_events[recording_name]
            tools: list[dict[str, Any]] = []

            for event in events:
                if event.get("type") != "assistant":
                    continue

                message = event.get("message", {})
                content = message.get("content", [])

                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        tools.append(
                            {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "input": item.get("input"),
                            }
                        )

            assert len(tools) > 0, (
                f"Critical: {recording_name} should have tool use but found none. "
                "Tool timeline will be empty."
            )

            # Verify each tool has required fields
            for tool in tools:
                assert tool["id"] is not None, f"{recording_name}: Tool missing id"
                assert tool["name"] is not None, f"{recording_name}: Tool missing name"
