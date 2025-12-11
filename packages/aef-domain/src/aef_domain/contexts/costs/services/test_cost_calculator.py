"""Tests for CostCalculator service."""

from decimal import Decimal
from typing import Any

import pytest

from aef_domain.contexts.costs.services.cost_calculator import CostCalculator


class MockEmitter:
    """Mock event emitter for testing."""

    def __init__(self) -> None:
        self.emitted: list[Any] = []

    async def emit(self, event: Any) -> None:
        """Record emitted event."""
        self.emitted.append(event)


@pytest.fixture
def emitter() -> MockEmitter:
    """Create mock emitter."""
    return MockEmitter()


@pytest.fixture
def calculator(emitter: MockEmitter) -> CostCalculator:
    """Create calculator with mock emitter."""
    return CostCalculator(emitter)


class TestCostCalculator:
    """Tests for CostCalculator."""

    @pytest.mark.asyncio
    async def test_on_token_usage_emits_cost_event(
        self, calculator: CostCalculator, emitter: MockEmitter
    ) -> None:
        """Test that token_usage event generates CostRecordedEvent."""
        event_data = {
            "session_id": "session-1",
            "execution_id": "exec-1",
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 1000,
            "output_tokens": 500,
            "timestamp": "2024-01-01T12:00:00Z",
        }

        result = await calculator.on_token_usage(event_data)

        assert result is not None
        assert result.session_id == "session-1"
        assert result.cost_type == "llm_tokens"
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        assert result.amount_usd > 0

        # Verify event was emitted
        assert len(emitter.emitted) == 1
        assert emitter.emitted[0] == result

    @pytest.mark.asyncio
    async def test_on_token_usage_calculates_correct_cost(self, calculator: CostCalculator) -> None:
        """Test correct cost calculation for Sonnet model."""
        event_data = {
            "session_id": "session-1",
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 1000000,  # 1M tokens
            "output_tokens": 500000,  # 500K tokens
        }

        result = await calculator.on_token_usage(event_data)

        assert result is not None
        # 1M input @ $3/M = $3.00
        # 500K output @ $15/M = $7.50
        # Total = $10.50
        assert result.amount_usd == Decimal("10.50")

    @pytest.mark.asyncio
    async def test_on_token_usage_skips_missing_session(self, calculator: CostCalculator) -> None:
        """Test that events without session_id are skipped."""
        event_data = {
            "model": "claude-sonnet-4-20250514",
            "input_tokens": 1000,
            "output_tokens": 500,
        }

        result = await calculator.on_token_usage(event_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_on_tool_execution_emits_cost_event(
        self, calculator: CostCalculator, emitter: MockEmitter
    ) -> None:
        """Test that tool_execution event generates CostRecordedEvent."""
        event_data = {
            "session_id": "session-1",
            "tool_name": "read_file",
            "duration_ms": 100,
            "timestamp": "2024-01-01T12:00:00Z",
        }

        result = await calculator.on_tool_execution(event_data)

        assert result is not None
        assert result.session_id == "session-1"
        assert result.cost_type == "tool_execution"
        assert result.tool_name == "read_file"
        assert result.tool_duration_ms == 100

        # Verify event was emitted
        assert len(emitter.emitted) == 1

    @pytest.mark.asyncio
    async def test_on_session_ended_emits_finalized_event(
        self, calculator: CostCalculator, emitter: MockEmitter
    ) -> None:
        """Test that session_ended generates SessionCostFinalizedEvent."""
        session_data = {
            "session_id": "session-1",
            "execution_id": "exec-1",
            "total_cost_usd": "1.50",
            "token_cost_usd": "1.00",
            "compute_cost_usd": "0.50",
            "input_tokens": 10000,
            "output_tokens": 5000,
            "tool_calls": 10,
            "turns": 5,
        }

        result = await calculator.on_session_ended(session_data)

        assert result is not None
        assert result.session_id == "session-1"
        assert result.total_cost_usd == Decimal("1.50")
        assert result.tool_calls == 10

        # Verify event was emitted
        assert len(emitter.emitted) == 1

    def test_calculate_token_cost_direct(self) -> None:
        """Test direct cost calculation without event emission."""
        calculator = CostCalculator()

        cost = calculator.calculate_token_cost(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
        )

        # 1000 input @ $3/M = $0.003
        # 500 output @ $15/M = $0.0075
        # Total = $0.0105
        assert cost == Decimal("0.0105")

    def test_calculate_token_cost_with_cache(self) -> None:
        """Test cost calculation with cache tokens."""
        calculator = CostCalculator()

        cost = calculator.calculate_token_cost(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=200,
            cache_read_tokens=300,
        )

        # 1000 input @ $3/M = $0.003
        # 500 output @ $15/M = $0.0075
        # 200 cache_creation @ $3.75/M = $0.00075
        # 300 cache_read @ $0.30/M = $0.00009
        # Total = $0.01134
        assert cost == Decimal("0.01134")
