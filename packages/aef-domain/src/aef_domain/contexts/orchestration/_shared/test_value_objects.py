"""Tests for costs domain value objects."""

from decimal import Decimal

import pytest

from aef_domain.contexts.orchestration._shared.value_objects import CostAmount, TokenCount


@pytest.mark.unit
class TestCostAmount:
    """Tests for CostAmount value object."""

    def test_create_cost_amount(self) -> None:
        """Test creating a CostAmount."""
        cost = CostAmount(Decimal("1.50"))
        assert cost.value == Decimal("1.50")

    def test_negative_raises_error(self) -> None:
        """Test that negative values raise ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            CostAmount(Decimal("-1.00"))

    def test_zero_factory(self) -> None:
        """Test zero() factory method."""
        cost = CostAmount.zero()
        assert cost.value == Decimal("0")

    def test_from_float(self) -> None:
        """Test from_float factory method."""
        cost = CostAmount.from_float(1.5)
        assert cost.value == Decimal("1.5")

    def test_addition(self) -> None:
        """Test adding two CostAmounts."""
        cost1 = CostAmount(Decimal("1.00"))
        cost2 = CostAmount(Decimal("2.50"))
        result = cost1 + cost2
        assert result.value == Decimal("3.50")


class TestCostAmountFormatting:
    """Tests for CostAmount formatting with adaptive precision."""

    def test_format_usd_large_amount(self) -> None:
        """Test formatting for amounts >= $1.00 (2 decimals)."""
        cost = CostAmount(Decimal("1.52345"))
        assert cost.format_usd() == "$1.52"

    def test_format_usd_exactly_one_dollar(self) -> None:
        """Test formatting for exactly $1.00."""
        cost = CostAmount(Decimal("1.00"))
        assert cost.format_usd() == "$1.00"

    def test_format_usd_large_value(self) -> None:
        """Test formatting for large amounts."""
        cost = CostAmount(Decimal("123.456789"))
        assert cost.format_usd() == "$123.46"

    def test_format_usd_medium_amount(self) -> None:
        """Test formatting for amounts >= $0.01 (4 decimals)."""
        cost = CostAmount(Decimal("0.052345"))
        assert cost.format_usd() == "$0.0523"

    def test_format_usd_exactly_one_cent(self) -> None:
        """Test formatting for exactly $0.01."""
        cost = CostAmount(Decimal("0.01"))
        assert cost.format_usd() == "$0.0100"

    def test_format_usd_small_amount(self) -> None:
        """Test formatting for amounts < $0.01 (6 decimals)."""
        cost = CostAmount(Decimal("0.000234"))
        assert cost.format_usd() == "$0.000234"

    def test_format_usd_very_small(self) -> None:
        """Test formatting for very small amounts."""
        cost = CostAmount(Decimal("0.000001"))
        assert cost.format_usd() == "$0.000001"

    def test_format_usd_zero(self) -> None:
        """Test formatting for zero."""
        cost = CostAmount(Decimal("0"))
        assert cost.format_usd() == "$0.000000"

    def test_str_uses_format_usd(self) -> None:
        """Test that __str__ uses format_usd."""
        cost = CostAmount(Decimal("5.25"))
        assert str(cost) == "$5.25"


class TestTokenCount:
    """Tests for TokenCount value object."""

    def test_create_token_count(self) -> None:
        """Test creating a TokenCount."""
        tc = TokenCount(input_tokens=100, output_tokens=50)
        assert tc.input_tokens == 100
        assert tc.output_tokens == 50
        assert tc.cache_creation_tokens == 0
        assert tc.cache_read_tokens == 0

    def test_total_tokens(self) -> None:
        """Test total property."""
        tc = TokenCount(input_tokens=100, output_tokens=50)
        assert tc.total == 150

    def test_negative_input_raises(self) -> None:
        """Test that negative input tokens raise ValueError."""
        with pytest.raises(ValueError, match="Input tokens cannot be negative"):
            TokenCount(input_tokens=-1, output_tokens=0)

    def test_negative_output_raises(self) -> None:
        """Test that negative output tokens raise ValueError."""
        with pytest.raises(ValueError, match="Output tokens cannot be negative"):
            TokenCount(input_tokens=0, output_tokens=-1)

    def test_addition(self) -> None:
        """Test adding two TokenCounts."""
        tc1 = TokenCount(input_tokens=100, output_tokens=50, cache_creation_tokens=10)
        tc2 = TokenCount(input_tokens=200, output_tokens=100, cache_read_tokens=20)
        result = tc1 + tc2
        assert result.input_tokens == 300
        assert result.output_tokens == 150
        assert result.cache_creation_tokens == 10
        assert result.cache_read_tokens == 20
