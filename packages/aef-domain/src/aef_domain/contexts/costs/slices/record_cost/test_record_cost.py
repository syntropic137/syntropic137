"""Tests for cost recording events and value objects."""

from decimal import Decimal

import pytest

from aef_domain.contexts.costs._shared.value_objects import (
    CostAmount,
    ModelPricing,
    TokenCount,
    get_model_pricing,
)
from aef_domain.contexts.costs.domain.events.CostRecordedEvent import CostRecordedEvent
from aef_domain.contexts.costs.domain.events.SessionCostFinalizedEvent import (
    SessionCostFinalizedEvent,
)


@pytest.mark.unit
class TestCostAmount:
    """Tests for CostAmount value object."""

    def test_create_cost_amount(self) -> None:
        """Test creating a cost amount."""
        cost = CostAmount(Decimal("1.23"))
        assert cost.value == Decimal("1.23")

    def test_negative_cost_raises(self) -> None:
        """Test that negative costs raise ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            CostAmount(Decimal("-1.00"))

    def test_zero_cost(self) -> None:
        """Test creating zero cost."""
        cost = CostAmount.zero()
        assert cost.value == Decimal("0")

    def test_from_float(self) -> None:
        """Test creating from float."""
        cost = CostAmount.from_float(1.23)
        assert cost.value == Decimal("1.23")

    def test_add_costs(self) -> None:
        """Test adding two costs."""
        cost1 = CostAmount(Decimal("1.00"))
        cost2 = CostAmount(Decimal("2.50"))
        result = cost1 + cost2
        assert result.value == Decimal("3.50")

    def test_str_format(self) -> None:
        """Test string formatting with adaptive precision."""
        # Large amounts: 2 decimals
        cost = CostAmount(Decimal("1.234567"))
        assert str(cost) == "$1.23"

        # Medium amounts: 4 decimals
        cost = CostAmount(Decimal("0.05"))
        assert str(cost) == "$0.0500"

        # Small amounts: 6 decimals
        cost = CostAmount(Decimal("0.001234"))
        assert str(cost) == "$0.001234"


class TestTokenCount:
    """Tests for TokenCount value object."""

    def test_create_token_count(self) -> None:
        """Test creating a token count."""
        tokens = TokenCount(input_tokens=100, output_tokens=50)
        assert tokens.input_tokens == 100
        assert tokens.output_tokens == 50
        assert tokens.total == 150

    def test_negative_tokens_raises(self) -> None:
        """Test that negative tokens raise ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            TokenCount(input_tokens=-1, output_tokens=0)

    def test_zero_tokens(self) -> None:
        """Test creating zero tokens."""
        tokens = TokenCount.zero()
        assert tokens.input_tokens == 0
        assert tokens.output_tokens == 0
        assert tokens.total == 0

    def test_add_tokens(self) -> None:
        """Test adding token counts."""
        tokens1 = TokenCount(input_tokens=100, output_tokens=50)
        tokens2 = TokenCount(input_tokens=200, output_tokens=100)
        result = tokens1 + tokens2
        assert result.input_tokens == 300
        assert result.output_tokens == 150
        assert result.total == 450


class TestModelPricing:
    """Tests for ModelPricing value object."""

    def test_calculate_cost(self) -> None:
        """Test calculating cost from token counts."""
        pricing = ModelPricing(
            model_id="test-model",
            input_price_per_million=Decimal("3.00"),
            output_price_per_million=Decimal("15.00"),
        )
        tokens = TokenCount(input_tokens=1000, output_tokens=500)
        cost = pricing.calculate_cost(tokens)

        # 1000 input * $3/M = $0.003
        # 500 output * $15/M = $0.0075
        # Total = $0.0105
        expected = Decimal("0.0105")
        assert cost.value == expected

    def test_calculate_cost_with_cache(self) -> None:
        """Test calculating cost with cache tokens."""
        pricing = ModelPricing(
            model_id="test-model",
            input_price_per_million=Decimal("3.00"),
            output_price_per_million=Decimal("15.00"),
            cache_creation_price_per_million=Decimal("3.75"),
            cache_read_price_per_million=Decimal("0.30"),
        )
        tokens = TokenCount(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=200,
            cache_read_tokens=300,
        )
        cost = pricing.calculate_cost(tokens)

        # 1000 input * $3/M = $0.003
        # 500 output * $15/M = $0.0075
        # 200 cache_creation * $3.75/M = $0.00075
        # 300 cache_read * $0.30/M = $0.00009
        # Total = $0.01134
        expected = Decimal("0.01134")
        assert cost.value == expected


class TestGetModelPricing:
    """Tests for get_model_pricing function."""

    def test_known_model(self) -> None:
        """Test getting pricing for a known model."""
        pricing = get_model_pricing("claude-sonnet-4-20250514")
        assert pricing.model_id == "claude-sonnet-4-20250514"
        assert pricing.input_price_per_million == Decimal("3.00")

    def test_unknown_model_fallback(self) -> None:
        """Test fallback to Sonnet pricing for unknown models."""
        pricing = get_model_pricing("unknown-model")
        assert pricing.model_id == "claude-sonnet-4-20250514"


class TestCostRecordedEvent:
    """Tests for CostRecordedEvent."""

    def test_create_token_cost_event(self) -> None:
        """Test creating a token cost event."""
        event = CostRecordedEvent(
            session_id="session-1",
            execution_id="exec-1",
            cost_type="llm_tokens",
            amount_usd=Decimal("0.01"),
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=500,
        )
        assert event.session_id == "session-1"
        assert event.cost_type == "llm_tokens"
        assert event.amount_usd == Decimal("0.01")

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        event = CostRecordedEvent(
            session_id="session-1",
            cost_type="llm_tokens",
            amount_usd=Decimal("0.01"),
        )
        data = event.to_dict()
        assert data["event_type"] == "CostRecorded"
        assert data["session_id"] == "session-1"
        assert data["amount_usd"] == "0.01"


class TestSessionCostFinalizedEvent:
    """Tests for SessionCostFinalizedEvent."""

    def test_create_event(self) -> None:
        """Test creating a session cost finalized event."""
        event = SessionCostFinalizedEvent(
            session_id="session-1",
            execution_id="exec-1",
            total_cost_usd=Decimal("1.50"),
            token_cost_usd=Decimal("1.00"),
            compute_cost_usd=Decimal("0.50"),
            input_tokens=10000,
            output_tokens=5000,
            tool_calls=10,
        )
        assert event.session_id == "session-1"
        assert event.total_cost_usd == Decimal("1.50")
        assert event.tool_calls == 10

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        event = SessionCostFinalizedEvent(
            session_id="session-1",
            total_cost_usd=Decimal("1.50"),
        )
        data = event.to_dict()
        assert data["event_type"] == "SessionCostFinalized"
        assert data["session_id"] == "session-1"
        assert data["total_cost_usd"] == "1.50"
