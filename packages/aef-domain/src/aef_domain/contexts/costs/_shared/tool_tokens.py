"""Value objects for tool-level token tracking."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ToolTokens:
    """Token usage for a single tool execution.

    Tracks both the tokens used in the tool_use block (output) and
    the tokens used in the tool_result block (input on next call).

    Attributes:
        tool_name: Name of the tool (e.g., "Write", "Read", "Shell")
        tool_use_tokens: Tokens for the tool_use block (output tokens)
        tool_result_tokens: Tokens for the tool_result block (input tokens)
        estimated: Whether the counts are estimated (True) or exact (False)
    """

    tool_name: str
    tool_use_tokens: int = 0
    tool_result_tokens: int = 0
    estimated: bool = True

    def __post_init__(self) -> None:
        """Validate token counts."""
        if self.tool_use_tokens < 0:
            raise ValueError("tool_use_tokens cannot be negative")
        if self.tool_result_tokens < 0:
            raise ValueError("tool_result_tokens cannot be negative")

    @property
    def total_tokens(self) -> int:
        """Total tokens for this tool execution."""
        return self.tool_use_tokens + self.tool_result_tokens

    def __add__(self, other: "ToolTokens") -> "ToolTokens":
        """Add two ToolTokens for the same tool."""
        if self.tool_name != other.tool_name:
            raise ValueError(
                f"Cannot add ToolTokens for different tools: {self.tool_name} vs {other.tool_name}"
            )
        return ToolTokens(
            tool_name=self.tool_name,
            tool_use_tokens=self.tool_use_tokens + other.tool_use_tokens,
            tool_result_tokens=self.tool_result_tokens + other.tool_result_tokens,
            estimated=self.estimated or other.estimated,
        )


@dataclass
class ToolTokenBreakdown:
    """Aggregated token breakdown by tool for a session.

    Provides a complete picture of how tokens were distributed
    across different tools within a session.
    """

    by_tool: dict[str, ToolTokens] = field(default_factory=dict)

    def add(self, tool_tokens: ToolTokens) -> None:
        """Add tool tokens to the breakdown.

        If the tool already exists, tokens are aggregated.
        """
        if tool_tokens.tool_name in self.by_tool:
            self.by_tool[tool_tokens.tool_name] = (
                self.by_tool[tool_tokens.tool_name] + tool_tokens
            )
        else:
            self.by_tool[tool_tokens.tool_name] = tool_tokens

    @property
    def total_tool_use_tokens(self) -> int:
        """Total tokens across all tool_use blocks."""
        return sum(tt.tool_use_tokens for tt in self.by_tool.values())

    @property
    def total_tool_result_tokens(self) -> int:
        """Total tokens across all tool_result blocks."""
        return sum(tt.tool_result_tokens for tt in self.by_tool.values())

    @property
    def total_tokens(self) -> int:
        """Total tokens across all tools."""
        return self.total_tool_use_tokens + self.total_tool_result_tokens

    def to_dict(self) -> dict[str, int]:
        """Convert to simple dict of tool_name -> total_tokens."""
        return {name: tt.total_tokens for name, tt in self.by_tool.items()}

    def calculate_costs(
        self,
        input_price_per_million: Decimal,
        output_price_per_million: Decimal,
    ) -> dict[str, Decimal]:
        """Calculate cost per tool.

        Args:
            input_price_per_million: Price per million input tokens
            output_price_per_million: Price per million output tokens

        Returns:
            Dict of tool_name -> cost in USD
        """
        costs: dict[str, Decimal] = {}
        for name, tt in self.by_tool.items():
            # tool_use is output tokens, tool_result is input tokens
            input_cost = Decimal(tt.tool_result_tokens) * input_price_per_million / Decimal(1_000_000)
            output_cost = Decimal(tt.tool_use_tokens) * output_price_per_million / Decimal(1_000_000)
            costs[name] = input_cost + output_cost
        return costs
