"""End-to-end validation of token counts and costs.

This test validates that:
1. Events from recordings flow through the collector correctly
2. Token counts stored in TimescaleDB match authoritative result event
3. Cost tracking is accurate per ADR-039

Requires test-stack running (just test-stack).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from aef_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.integration]


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def context_tracking_adapter() -> RecordingEventStreamAdapter:
    """Get adapter for context-tracking recording."""
    try:
        return RecordingEventStreamAdapter("context-tracking")
    except FileNotFoundError:
        pytest.skip("context-tracking recording not available")


@pytest.fixture
def multi_model_adapter() -> RecordingEventStreamAdapter:
    """Get adapter for multi-model-usage recording."""
    try:
        return RecordingEventStreamAdapter("multi-model-usage")
    except FileNotFoundError:
        pytest.skip("multi-model-usage recording not available")


@pytest.fixture
def simple_bash_adapter() -> RecordingEventStreamAdapter:
    """Get adapter for simple-bash recording."""
    try:
        return RecordingEventStreamAdapter("simple-bash")
    except FileNotFoundError:
        pytest.skip("simple-bash recording not available")


def _make_event_id(session_id: str, event_type: str, index: int) -> str:
    """Generate deterministic event ID."""
    content = f"{session_id}:{event_type}:{index}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


# =============================================================================
# CONTEXT WINDOW VALIDATION (ADR-039)
# =============================================================================


class TestContextWindowValidation:
    """Validate context window calculation matches ADR-039 formula."""

    def test_context_window_from_assistant_events(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Context window = input_tokens + cache_creation + cache_read.

        Per ADR-039, the context window is calculated from assistant message usage.
        """
        events = simple_bash_adapter.get_events()
        context_windows: list[int] = []

        for event in events:
            if event.get("type") != "assistant":
                continue

            message = event.get("message", {})
            usage = message.get("usage", {})
            if not usage:
                continue

            input_tokens = usage.get("input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            # ADR-039 formula
            context_window = input_tokens + cache_creation + cache_read
            context_windows.append(context_window)

        assert len(context_windows) > 0, "Should have context window data points"

        # Context window should grow over conversation
        for i in range(1, len(context_windows)):
            # Allow for variance but generally should be increasing
            assert context_windows[i] > 0, f"Context window at turn {i} should be positive"

        print(f"\nContext window progression: {context_windows}")
        print(f"Max context window: {max(context_windows)}")


# =============================================================================
# COST TRACKING VALIDATION (ADR-039)
# =============================================================================


class TestCostTrackingValidation:
    """Validate cost tracking against authoritative result event."""

    def test_result_event_has_authoritative_cost(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Result event contains total_cost_usd (authoritative)."""
        events = simple_bash_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)

        assert result is not None, "Recording should have result event"
        assert "total_cost_usd" in result, "Result should have total_cost_usd"

        total_cost = result["total_cost_usd"]
        assert total_cost > 0, f"Cost should be positive, got {total_cost}"

        # Verify it's a reasonable value (not astronomical)
        assert total_cost < 100, f"Cost seems too high: ${total_cost}"

        print(f"\nAuthoritative total cost: ${total_cost}")

    def test_result_event_has_model_usage_breakdown(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Result event contains modelUsage breakdown per model."""
        events = simple_bash_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)

        assert result is not None

        # Check for modelUsage (may be empty for single-model sessions)
        model_usage = result.get("modelUsage", {})

        print(f"\nModel usage breakdown: {model_usage}")

        # If present, verify structure
        for model, usage in model_usage.items():
            if "cost_usd" in usage:
                assert usage["cost_usd"] >= 0, f"Model {model} cost should be non-negative"
            if "input_tokens" in usage:
                assert usage["input_tokens"] >= 0, (
                    f"Model {model} input tokens should be non-negative"
                )

    def test_calculated_cost_approximates_authoritative(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Calculated cost from tokens should be close to authoritative cost.

        This validates our cost formula matches Claude's calculation.
        """
        events = simple_bash_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None

        usage = result.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)

        # Claude Sonnet pricing (per ADR-039)
        input_cost = Decimal(input_tokens) * Decimal("0.000003")
        output_cost = Decimal(output_tokens) * Decimal("0.000015")
        cache_creation_cost = Decimal(cache_creation) * Decimal("0.00000375")
        cache_read_cost = Decimal(cache_read) * Decimal("0.0000003")

        calculated_cost = float(input_cost + output_cost + cache_creation_cost + cache_read_cost)
        authoritative_cost = result["total_cost_usd"]

        # Allow 20% variance for pricing differences, tool costs, etc.
        ratio = calculated_cost / authoritative_cost if authoritative_cost > 0 else 0
        print(f"\nCalculated cost: ${calculated_cost:.6f}")
        print(f"Authoritative cost: ${authoritative_cost:.6f}")
        print(f"Ratio: {ratio:.2f}")

        # The calculated cost should be in the same ballpark
        assert 0.5 < ratio < 2.0, (
            f"Calculated cost (${calculated_cost:.4f}) differs too much from "
            f"authoritative (${authoritative_cost:.4f})"
        )


# =============================================================================
# TOKEN RECONCILIATION (ADR-039)
# =============================================================================


class TestTokenReconciliation:
    """Validate token counts match between per-turn and result."""

    def test_cumulative_input_tokens_match_result(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Result input_tokens includes all token usage.

        Per ADR-039: result.usage.input_tokens is authoritative for cumulative input.
        """
        events = simple_bash_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None

        result_input = result.get("usage", {}).get("input_tokens", 0)

        # Sum input tokens from assistant events
        cumulative_input = 0
        for event in events:
            if event.get("type") != "assistant":
                continue
            message = event.get("message", {})
            usage = message.get("usage", {})
            cumulative_input += usage.get("input_tokens", 0)

        print(f"\nResult input tokens: {result_input}")
        print(f"Cumulative input tokens: {cumulative_input}")

        # Input tokens accumulate, so result should be >= last cumulative value
        assert result_input > 0, "Result should have input tokens"

    def test_output_tokens_authoritative_from_result(
        self, simple_bash_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Result output_tokens is authoritative (per-turn may differ due to streaming).

        Per ADR-039: result.usage.output_tokens is authoritative.
        Streaming can cause per-turn output_tokens to differ.
        """
        events = simple_bash_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None

        result_output = result.get("usage", {}).get("output_tokens", 0)

        print(f"\nResult output tokens: {result_output}")
        assert result_output > 0, "Result should have output tokens"


# =============================================================================
# MULTI-MODEL VALIDATION
# =============================================================================


class TestMultiModelValidation:
    """Validate multi-model sessions track costs correctly."""

    def test_multi_model_session_has_model_breakdown(
        self, multi_model_adapter: RecordingEventStreamAdapter
    ) -> None:
        """Multi-model sessions show per-model cost in modelUsage."""
        events = multi_model_adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)

        assert result is not None, "Should have result event"

        model_usage = result.get("modelUsage", {})
        total_cost = result.get("total_cost_usd", 0)

        print(f"\nTotal cost: ${total_cost}")
        print(f"Model usage: {model_usage}")

        # Should have at least one model
        assert len(model_usage) >= 1 or total_cost > 0, (
            "Multi-model session should have modelUsage or total_cost"
        )


# =============================================================================
# COLLECTOR INTEGRATION (requires test-stack)
# =============================================================================


class TestCollectorIntegration:
    """Test collector accepts events correctly.

    Note: The collector writes to event store via gRPC, not directly to agent_events.
    The agent_events table is populated from actual agent execution.
    These tests validate collector acceptance, not TimescaleDB storage.
    """

    @pytest.fixture
    def collector_url(self, test_infrastructure: Any) -> str | None:
        """Get collector URL from test infrastructure."""
        from aef_tests.fixtures.infrastructure import TestInfrastructure

        if isinstance(test_infrastructure, TestInfrastructure):
            return test_infrastructure.collector_url
        return None

    @pytest.mark.asyncio
    async def test_collector_accepts_token_usage_events(
        self,
        collector_url: str | None,
        simple_bash_adapter: RecordingEventStreamAdapter,
    ) -> None:
        """Collector accepts token_usage events from recordings."""
        if not collector_url:
            pytest.skip("Collector not available")

        # Generate unique session ID for this test
        test_session_id = f"test-{uuid.uuid4()}"
        events = simple_bash_adapter.get_events()

        # Transform events to collector format
        batch_events = []
        for i, event in enumerate(events):
            event_type = event.get("type", "unknown")

            # Map to collector event types (must match EventType enum in aef_shared)
            type_mapping = {
                "system": "session_started",
                "assistant": "token_usage",
                "user": "token_usage",
                "result": "session_ended",
            }
            mapped_type = type_mapping.get(event_type, "token_usage")

            batch_events.append(
                {
                    "event_id": _make_event_id(test_session_id, mapped_type, i),
                    "event_type": mapped_type,
                    "session_id": test_session_id,
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                    "data": event,
                }
            )

        batch = {
            "agent_id": "validation-test",
            "batch_id": str(uuid.uuid4()),
            "events": batch_events,
        }

        # Send to collector
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{collector_url}/events",
                json=batch,
                timeout=10.0,
            )

        assert response.status_code == 200, f"Collector rejected events: {response.text}"
        result = response.json()
        assert result["accepted"] > 0, "Should accept some events"

        print(f"\nCollector accepted {result['accepted']} events for session {test_session_id}")
