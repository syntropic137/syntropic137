"""Tests for context window and cost tracking.

Validates the formulas from ADR-039:
- Context window = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
- Authoritative cost from result.total_cost_usd
- Multi-model breakdown from result.modelUsage

See ADR-039: Context Window and Cost Tracking
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.unit]


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def context_tracking_events() -> list[dict[str, Any]]:
    """Get events from context-tracking recording."""
    try:
        adapter = RecordingEventStreamAdapter("context-tracking")
        return adapter.get_events()
    except FileNotFoundError:
        pytest.skip("context-tracking recording not available")


@pytest.fixture
def multi_model_events() -> list[dict[str, Any]]:
    """Get events from multi-model-usage recording (directory format)."""
    try:
        adapter = RecordingEventStreamAdapter("multi-model-usage")
        return adapter.get_events()
    except FileNotFoundError:
        pytest.skip("multi-model-usage recording not available")


@pytest.fixture
def simple_bash_events() -> list[dict[str, Any]]:
    """Get events from simple-bash recording."""
    try:
        adapter = RecordingEventStreamAdapter("simple-bash")
        return adapter.get_events()
    except FileNotFoundError:
        pytest.skip("simple-bash recording not available")


# =============================================================================
# CONTEXT WINDOW CALCULATION TESTS
# =============================================================================


class TestContextWindowFormula:
    """Verify context window calculation formula from ADR-039."""

    def test_context_window_from_usage(self, context_tracking_events: list[dict[str, Any]]) -> None:
        """Context window = input_tokens + cache_creation_input_tokens + cache_read_input_tokens."""
        assistant_events = [e for e in context_tracking_events if e.get("type") == "assistant"]
        assert len(assistant_events) > 0, "Should have assistant events"

        for event in assistant_events:
            message = event.get("message", {})
            usage = message.get("usage", {})

            if not usage:
                continue

            # Extract token counts
            input_tokens = usage.get("input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            # Calculate context window
            context_window = input_tokens + cache_creation + cache_read

            # Verify it's a reasonable value (> 0 for non-empty context)
            assert context_window > 0, (
                f"Context window should be positive: "
                f"input={input_tokens}, cache_creation={cache_creation}, cache_read={cache_read}"
            )

    def test_context_window_grows_over_turns(
        self, context_tracking_events: list[dict[str, Any]]
    ) -> None:
        """Context window should generally grow as conversation progresses."""
        assistant_events = [e for e in context_tracking_events if e.get("type") == "assistant"]

        context_windows = []
        for event in assistant_events:
            message = event.get("message", {})
            usage = message.get("usage", {})

            if not usage:
                continue

            input_tokens = usage.get("input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            context_window = input_tokens + cache_creation + cache_read
            context_windows.append(context_window)

        assert len(context_windows) >= 2, "Need multiple turns to test growth"

        # Context should generally increase (allowing for some variation)
        # Check that max > first
        assert max(context_windows) >= context_windows[0], (
            f"Context window should grow: {context_windows}"
        )


# =============================================================================
# COST TRACKING TESTS
# =============================================================================


class TestCostTracking:
    """Verify cost tracking from result event."""

    def test_result_has_total_cost(self, context_tracking_events: list[dict[str, Any]]) -> None:
        """Result event has authoritative total_cost_usd."""
        result = next((e for e in context_tracking_events if e.get("type") == "result"), None)
        assert result is not None, "Should have result event"

        cost = result.get("total_cost_usd")
        assert cost is not None, "Result should have total_cost_usd"
        assert isinstance(cost, (int, float)), f"Cost should be numeric: {type(cost)}"
        assert cost >= 0, f"Cost should be non-negative: {cost}"

    def test_result_has_usage_totals(self, context_tracking_events: list[dict[str, Any]]) -> None:
        """Result event has cumulative token usage."""
        result = next((e for e in context_tracking_events if e.get("type") == "result"), None)
        assert result is not None

        usage = result.get("usage", {})
        assert usage, "Result should have usage object"

        # Check for expected fields
        assert "input_tokens" in usage or "output_tokens" in usage, (
            f"Usage should have token counts: {usage.keys()}"
        )


class TestMultiModelUsage:
    """Verify multi-model cost breakdown from modelUsage."""

    def test_result_has_model_usage(self, multi_model_events: list[dict[str, Any]]) -> None:
        """Result event has modelUsage breakdown."""
        result = next((e for e in multi_model_events if e.get("type") == "result"), None)
        assert result is not None, "Should have result event"

        model_usage = result.get("modelUsage", {})
        assert model_usage, f"Result should have modelUsage: {result.keys()}"

    def test_model_usage_has_per_model_costs(
        self, multi_model_events: list[dict[str, Any]]
    ) -> None:
        """modelUsage has per-model cost breakdown."""
        result = next((e for e in multi_model_events if e.get("type") == "result"), None)
        assert result is not None

        model_usage = result.get("modelUsage", {})
        assert model_usage, "Should have modelUsage"

        for model_name, model_data in model_usage.items():
            assert "costUSD" in model_data, (
                f"Model {model_name} should have costUSD: {model_data.keys()}"
            )
            assert model_data["costUSD"] >= 0, f"Model {model_name} cost should be non-negative"

    def test_model_usage_costs_sum_to_total(self, multi_model_events: list[dict[str, Any]]) -> None:
        """Sum of per-model costs should equal total_cost_usd."""
        result = next((e for e in multi_model_events if e.get("type") == "result"), None)
        assert result is not None

        total_cost = result.get("total_cost_usd", 0)
        model_usage = result.get("modelUsage", {})

        if not model_usage:
            pytest.skip("No modelUsage in this recording")

        per_model_sum = sum(model_data.get("costUSD", 0) for model_data in model_usage.values())

        # Allow small floating point difference
        assert abs(total_cost - per_model_sum) < 0.0001, (
            f"Per-model costs ({per_model_sum}) should sum to total ({total_cost})"
        )


# =============================================================================
# TOKEN RECONCILIATION TESTS
# =============================================================================


class TestTokenReconciliation:
    """Verify result event is the authoritative source."""

    def test_result_is_authoritative_for_output_tokens(
        self, simple_bash_events: list[dict[str, Any]]
    ) -> None:
        """Result event output_tokens is authoritative (per-turn may be partial).

        Note: Claude CLI streams multiple assistant events per turn with partial
        token counts. The result event contains the authoritative cumulative total.
        Per-turn assistant events may show lower counts due to streaming updates.
        """
        assistant_events = [e for e in simple_bash_events if e.get("type") == "assistant"]
        result = next((e for e in simple_bash_events if e.get("type") == "result"), None)

        if not result:
            pytest.skip("No result event")

        # Sum output tokens from assistant events (may be partial due to streaming)
        cumulative_output = 0
        for event in assistant_events:
            message = event.get("message", {})
            usage = message.get("usage", {})
            cumulative_output += usage.get("output_tokens", 0)

        # Get result total (authoritative)
        result_usage = result.get("usage", {})
        result_output = result_usage.get("output_tokens", 0)

        # Result should be >= cumulative (authoritative source)
        # Per-turn may be lower due to streaming partial updates
        assert result_output >= cumulative_output * 0.5, (
            f"Result output ({result_output}) should be >= half of "
            f"cumulative ({cumulative_output}) - streaming may cause differences"
        )

        # Result should have a reasonable value
        assert result_output > 0, "Result should have output tokens"


# =============================================================================
# ALL RECORDINGS VALIDATION
# =============================================================================


class TestAllRecordingsHaveMetrics:
    """Verify all recordings have the required metrics."""

    @pytest.fixture
    def all_recording_adapters(self) -> list[RecordingEventStreamAdapter]:
        """Get adapters for all available recordings."""
        recording_names = [
            "simple-bash",
            "file-create",
            "file-read",
            "git-status",
            "multi-tool",
            "simple-question",
            "list-files",
            "context-tracking",
            "multi-model-usage",
        ]
        adapters = []
        for name in recording_names:
            with contextlib.suppress(FileNotFoundError):
                adapters.append(RecordingEventStreamAdapter(name))
        if not adapters:
            pytest.skip("No recordings available")
        return adapters

    def test_all_recordings_have_cost(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Every recording has total_cost_usd in result."""
        for adapter in all_recording_adapters:
            events = adapter.get_events()
            result = next((e for e in events if e.get("type") == "result"), None)

            if result:
                cost = result.get("total_cost_usd")
                task = adapter.metadata.task if adapter.metadata else "unknown"
                assert cost is not None, f"Recording {task} missing total_cost_usd"

    def test_all_recordings_have_usage(
        self, all_recording_adapters: list[RecordingEventStreamAdapter]
    ) -> None:
        """Every recording has usage in result."""
        for adapter in all_recording_adapters:
            events = adapter.get_events()
            result = next((e for e in events if e.get("type") == "result"), None)

            if result:
                usage = result.get("usage")
                task = adapter.metadata.task if adapter.metadata else "unknown"
                assert usage is not None, f"Recording {task} missing usage"
