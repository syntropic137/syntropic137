"""Tests for ToolTokens value objects."""

from decimal import Decimal

import pytest

from aef_domain.contexts.costs._shared.tool_tokens import (
    ToolTokenBreakdown,
    ToolTokens,
)


class TestToolTokens:
    """Tests for ToolTokens value object."""

    def test_create_tool_tokens(self) -> None:
        """Test creating tool tokens."""
        tt = ToolTokens(
            tool_name="Write",
            tool_use_tokens=500,
            tool_result_tokens=50,
        )
        assert tt.tool_name == "Write"
        assert tt.tool_use_tokens == 500
        assert tt.tool_result_tokens == 50
        assert tt.total_tokens == 550
        assert tt.estimated is True

    def test_negative_tokens_raises(self) -> None:
        """Test that negative tokens raise ValueError."""
        with pytest.raises(ValueError, match="cannot be negative"):
            ToolTokens(tool_name="Write", tool_use_tokens=-1)

        with pytest.raises(ValueError, match="cannot be negative"):
            ToolTokens(tool_name="Write", tool_result_tokens=-1)

    def test_add_same_tool(self) -> None:
        """Test adding tokens for the same tool."""
        tt1 = ToolTokens(tool_name="Write", tool_use_tokens=100, tool_result_tokens=10)
        tt2 = ToolTokens(tool_name="Write", tool_use_tokens=200, tool_result_tokens=20)

        result = tt1 + tt2

        assert result.tool_name == "Write"
        assert result.tool_use_tokens == 300
        assert result.tool_result_tokens == 30
        assert result.total_tokens == 330

    def test_add_different_tools_raises(self) -> None:
        """Test that adding different tools raises ValueError."""
        tt1 = ToolTokens(tool_name="Write", tool_use_tokens=100)
        tt2 = ToolTokens(tool_name="Read", tool_use_tokens=100)

        with pytest.raises(ValueError, match="Cannot add ToolTokens for different tools"):
            _ = tt1 + tt2

    def test_estimated_flag_propagates(self) -> None:
        """Test that estimated flag is True if either is estimated."""
        tt1 = ToolTokens(tool_name="Write", tool_use_tokens=100, estimated=False)
        tt2 = ToolTokens(tool_name="Write", tool_use_tokens=100, estimated=True)

        result = tt1 + tt2
        assert result.estimated is True


class TestToolTokenBreakdown:
    """Tests for ToolTokenBreakdown."""

    def test_add_single_tool(self) -> None:
        """Test adding a single tool."""
        breakdown = ToolTokenBreakdown()
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=500))

        assert "Write" in breakdown.by_tool
        assert breakdown.by_tool["Write"].tool_use_tokens == 500

    def test_add_multiple_tools(self) -> None:
        """Test adding multiple different tools."""
        breakdown = ToolTokenBreakdown()
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=500))
        breakdown.add(ToolTokens(tool_name="Read", tool_result_tokens=1000))

        assert len(breakdown.by_tool) == 2
        assert breakdown.by_tool["Write"].tool_use_tokens == 500
        assert breakdown.by_tool["Read"].tool_result_tokens == 1000

    def test_aggregate_same_tool(self) -> None:
        """Test that multiple adds for same tool aggregate."""
        breakdown = ToolTokenBreakdown()
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=100))
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=200))
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=300))

        assert len(breakdown.by_tool) == 1
        assert breakdown.by_tool["Write"].tool_use_tokens == 600

    def test_total_tokens(self) -> None:
        """Test total token calculations."""
        breakdown = ToolTokenBreakdown()
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=500, tool_result_tokens=50))
        breakdown.add(ToolTokens(tool_name="Read", tool_use_tokens=100, tool_result_tokens=1000))

        assert breakdown.total_tool_use_tokens == 600
        assert breakdown.total_tool_result_tokens == 1050
        assert breakdown.total_tokens == 1650

    def test_to_dict(self) -> None:
        """Test conversion to simple dict."""
        breakdown = ToolTokenBreakdown()
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=500, tool_result_tokens=50))
        breakdown.add(ToolTokens(tool_name="Read", tool_use_tokens=100, tool_result_tokens=1000))

        result = breakdown.to_dict()

        assert result == {"Write": 550, "Read": 1100}

    def test_calculate_costs(self) -> None:
        """Test cost calculation per tool."""
        breakdown = ToolTokenBreakdown()
        # Write: 1000 output tokens (tool_use)
        breakdown.add(ToolTokens(tool_name="Write", tool_use_tokens=1000, tool_result_tokens=0))
        # Read: 2000 input tokens (tool_result)
        breakdown.add(ToolTokens(tool_name="Read", tool_use_tokens=0, tool_result_tokens=2000))

        # Use Sonnet pricing: $3/M input, $15/M output
        costs = breakdown.calculate_costs(
            input_price_per_million=Decimal("3.00"),
            output_price_per_million=Decimal("15.00"),
        )

        # Write: 1000 * $15/M = $0.015
        assert costs["Write"] == Decimal("0.015")
        # Read: 2000 * $3/M = $0.006
        assert costs["Read"] == Decimal("0.006")
