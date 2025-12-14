"""Tool token estimation service.

Estimates the number of tokens used by tool_use and tool_result blocks
in Claude's API responses. Uses heuristics based on content size since
exact token counts require API calls.

Token Estimation Heuristics:
- Average English text: ~4 characters per token
- JSON/code: ~3-4 characters per token
- Tool names and structure: ~10-20 tokens overhead
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from aef_domain.contexts.costs._shared.tool_tokens import ToolTokenBreakdown, ToolTokens

logger = logging.getLogger(__name__)


# Characters per token for different content types
CHARS_PER_TOKEN_TEXT = 4.0
CHARS_PER_TOKEN_JSON = 3.5

# Overhead tokens for tool structure (name, id, type fields)
TOOL_USE_OVERHEAD = 15
TOOL_RESULT_OVERHEAD = 10


@dataclass
class ToolUseBlock:
    """Parsed tool_use block from Claude's response."""

    tool_use_id: str
    tool_name: str
    input_json: dict[str, Any]

    @property
    def input_size(self) -> int:
        """Size of the input JSON in characters."""
        return len(json.dumps(self.input_json))


@dataclass
class ToolResultBlock:
    """Parsed tool_result block from a user message."""

    tool_use_id: str
    content: str | list[dict[str, Any]]
    is_error: bool = False

    @property
    def content_size(self) -> int:
        """Size of the result content in characters."""
        if isinstance(self.content, str):
            return len(self.content)
        return len(json.dumps(self.content))


class ToolTokenEstimator:
    """Estimates token usage for tool calls.

    This service parses assistant message content arrays to extract
    tool_use blocks and estimates their token counts. It can also
    process tool_result blocks to estimate input token costs.

    Usage:
        estimator = ToolTokenEstimator()

        # From assistant message content
        tool_tokens = estimator.estimate_from_content(content_array)

        # From individual blocks
        tokens = estimator.estimate_tool_use(tool_name, input_json)
        tokens = estimator.estimate_tool_result(result_content)
    """

    def __init__(
        self,
        chars_per_token: float = CHARS_PER_TOKEN_JSON,
    ) -> None:
        """Initialize the estimator.

        Args:
            chars_per_token: Average characters per token for estimation.
        """
        self._chars_per_token = chars_per_token

    def estimate_from_content(
        self,
        content: list[dict[str, Any]],
    ) -> ToolTokenBreakdown:
        """Estimate tokens from an assistant message content array.

        Parses the content array for tool_use blocks and estimates
        their token usage.

        Args:
            content: The content array from an assistant message

        Returns:
            ToolTokenBreakdown with per-tool token estimates
        """
        breakdown = ToolTokenBreakdown()

        for block in content:
            block_type = block.get("type")

            if block_type == "tool_use":
                tool_tokens = self._estimate_tool_use_block(block)
                if tool_tokens:
                    breakdown.add(tool_tokens)

        return breakdown

    def estimate_tool_use(
        self,
        tool_name: str,
        input_json: dict[str, Any] | None = None,
    ) -> ToolTokens:
        """Estimate tokens for a tool_use block.

        Args:
            tool_name: Name of the tool (e.g., "Write", "Read")
            input_json: The input parameters for the tool

        Returns:
            ToolTokens with estimated tool_use_tokens
        """
        # Base overhead for tool structure
        tokens = TOOL_USE_OVERHEAD

        # Add tokens for tool name
        tokens += self._estimate_string_tokens(tool_name)

        # Add tokens for input JSON
        if input_json:
            input_str = json.dumps(input_json)
            tokens += self._estimate_tokens(input_str)

        return ToolTokens(
            tool_name=tool_name,
            tool_use_tokens=tokens,
            tool_result_tokens=0,
            estimated=True,
        )

    def estimate_tool_result(
        self,
        tool_name: str,
        content: str | list[dict[str, Any]] | None = None,
        is_error: bool = False,  # noqa: ARG002 - reserved for future error handling
    ) -> ToolTokens:
        """Estimate tokens for a tool_result block.

        These tokens count as input tokens on the next API call.

        Args:
            tool_name: Name of the tool for attribution
            content: The result content (string or structured)
            is_error: Whether this is an error result

        Returns:
            ToolTokens with estimated tool_result_tokens
        """
        # Base overhead for result structure
        tokens = TOOL_RESULT_OVERHEAD

        if content:
            if isinstance(content, str):
                tokens += self._estimate_tokens(content)
            else:
                tokens += self._estimate_tokens(json.dumps(content))

        return ToolTokens(
            tool_name=tool_name,
            tool_use_tokens=0,
            tool_result_tokens=tokens,
            estimated=True,
        )

    def estimate_from_tool_details(
        self,
        tool_details: list[dict[str, Any]],
    ) -> ToolTokenBreakdown:
        """Estimate tokens from tool_details event data.

        The collector provides tool_details with pre-calculated sizes.

        Args:
            tool_details: List of tool detail dicts with:
                - name: Tool name
                - input_size: Size of input in chars (optional)
                - result_size: Size of result in chars (optional)

        Returns:
            ToolTokenBreakdown with per-tool estimates
        """
        breakdown = ToolTokenBreakdown()

        for detail in tool_details:
            name = detail.get("name", "unknown")
            input_size = detail.get("input_size", 0)
            result_size = detail.get("result_size", 0)

            # Estimate tokens from sizes
            tool_use_tokens = TOOL_USE_OVERHEAD
            if input_size:
                tool_use_tokens += int(input_size / self._chars_per_token)

            tool_result_tokens = TOOL_RESULT_OVERHEAD
            if result_size:
                tool_result_tokens += int(result_size / self._chars_per_token)

            breakdown.add(
                ToolTokens(
                    tool_name=name,
                    tool_use_tokens=tool_use_tokens,
                    tool_result_tokens=tool_result_tokens,
                    estimated=True,
                )
            )

        return breakdown

    def _estimate_tool_use_block(
        self,
        block: dict[str, Any],
    ) -> ToolTokens | None:
        """Estimate tokens for a single tool_use block.

        Args:
            block: A tool_use content block

        Returns:
            ToolTokens or None if invalid
        """
        tool_name = block.get("name")
        if not tool_name:
            logger.debug("tool_use block missing name")
            return None

        input_json = block.get("input", {})

        return self.estimate_tool_use(tool_name, input_json)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses the configured characters-per-token ratio.

        Args:
            text: The text to estimate

        Returns:
            Estimated token count
        """
        if not text:
            return 0
        return max(1, int(len(text) / self._chars_per_token))

    def _estimate_string_tokens(self, text: str) -> int:
        """Estimate tokens for a short string (tool name, etc).

        Uses a more conservative estimate for short strings.

        Args:
            text: Short string to estimate

        Returns:
            Estimated token count
        """
        if not text:
            return 0
        # Short strings tend to be less efficiently tokenized
        return max(1, int(len(text) / 3.0))


def estimate_write_tool_tokens(
    file_path: str,
    content: str,
) -> ToolTokens:
    """Convenience function to estimate Write tool tokens.

    Write tool is special because the content can be very large.

    Args:
        file_path: Path being written to
        content: File content being written

    Returns:
        ToolTokens estimate
    """
    estimator = ToolTokenEstimator()

    # Build input JSON structure like Claude does
    input_json = {
        "file_path": file_path,
        "content": content,
    }

    return estimator.estimate_tool_use("Write", input_json)


def estimate_read_tool_tokens(
    file_path: str,
    file_content: str,
) -> ToolTokens:
    """Convenience function to estimate Read tool tokens.

    Read tool has small input but potentially large result.

    Args:
        file_path: Path being read
        file_content: Content returned by the tool

    Returns:
        ToolTokens estimate
    """
    estimator = ToolTokenEstimator()

    # Small tool_use for the read request
    use_tokens = estimator.estimate_tool_use("Read", {"file_path": file_path})

    # Larger tool_result for the file content
    result_tokens = estimator.estimate_tool_result("Read", file_content)

    return ToolTokens(
        tool_name="Read",
        tool_use_tokens=use_tokens.tool_use_tokens,
        tool_result_tokens=result_tokens.tool_result_tokens,
        estimated=True,
    )
