"""Tests for ToolTokenEstimator service."""

import pytest

from aef_domain.contexts.costs.services.tool_token_estimator import (
    ToolTokenEstimator,
    estimate_read_tool_tokens,
    estimate_write_tool_tokens,
)


class TestToolTokenEstimator:
    """Tests for ToolTokenEstimator."""

    @pytest.fixture
    def estimator(self) -> ToolTokenEstimator:
        """Create a ToolTokenEstimator."""
        return ToolTokenEstimator()

    def test_estimate_tool_use_simple(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating tokens for a simple tool_use."""
        result = estimator.estimate_tool_use("Read", {"file_path": "/path/to/file.py"})

        assert result.tool_name == "Read"
        assert result.tool_use_tokens > 0
        assert result.tool_result_tokens == 0
        assert result.estimated is True

    def test_estimate_tool_use_with_large_input(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating tokens for tool_use with large input (e.g., Write)."""
        # 1000 characters of content
        content = "x" * 1000

        result = estimator.estimate_tool_use(
            "Write",
            {"file_path": "/path/to/file.py", "content": content},
        )

        assert result.tool_name == "Write"
        # At ~3.5 chars/token, 1000 chars ≈ 285 tokens + overhead
        assert result.tool_use_tokens >= 280

    def test_estimate_tool_result_string(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating tokens for a string tool_result."""
        # Simulate file content returned by Read
        file_content = "def hello():\n    print('Hello, World!')\n" * 100  # ~4000 chars

        result = estimator.estimate_tool_result("Read", file_content)

        assert result.tool_name == "Read"
        assert result.tool_use_tokens == 0
        assert result.tool_result_tokens > 1000  # ~4000 chars / 3.5 = ~1142 tokens

    def test_estimate_tool_result_structured(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating tokens for a structured tool_result."""
        result_content = [
            {"type": "text", "text": "File written successfully"},
        ]

        result = estimator.estimate_tool_result("Write", result_content)

        assert result.tool_name == "Write"
        assert result.tool_result_tokens > 10

    def test_estimate_from_content_array(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating tokens from an assistant message content array."""
        content = [
            {"type": "text", "text": "I'll read that file for you."},
            {
                "type": "tool_use",
                "id": "toolu_01ABC",
                "name": "Read",
                "input": {"file_path": "/path/to/file.py"},
            },
            {"type": "text", "text": "The file contains the following:"},
        ]

        breakdown = estimator.estimate_from_content(content)

        assert "Read" in breakdown.by_tool
        assert breakdown.by_tool["Read"].tool_use_tokens > 0

    def test_estimate_from_content_multiple_tools(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating tokens from content with multiple tool calls."""
        content = [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "Read",
                "input": {"file_path": "/path/a.py"},
            },
            {
                "type": "tool_use",
                "id": "toolu_02",
                "name": "Read",
                "input": {"file_path": "/path/b.py"},
            },
            {
                "type": "tool_use",
                "id": "toolu_03",
                "name": "Write",
                "input": {"file_path": "/path/c.py", "content": "# New file\n"},
            },
        ]

        breakdown = estimator.estimate_from_content(content)

        assert "Read" in breakdown.by_tool
        assert "Write" in breakdown.by_tool
        # Read should have aggregated tokens from both calls
        assert (
            breakdown.by_tool["Read"].tool_use_tokens
            > breakdown.by_tool["Write"].tool_use_tokens * 0.5
        )

    def test_estimate_from_tool_details(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating from collector tool_details format."""
        tool_details = [
            {"name": "Read", "input_size": 50, "result_size": 4000},
            {"name": "Write", "input_size": 2000, "result_size": 30},
        ]

        breakdown = estimator.estimate_from_tool_details(tool_details)

        assert "Read" in breakdown.by_tool
        assert "Write" in breakdown.by_tool
        # Read has large result
        assert breakdown.by_tool["Read"].tool_result_tokens > 500
        # Write has large input
        assert breakdown.by_tool["Write"].tool_use_tokens > 500

    def test_estimate_empty_content(self, estimator: ToolTokenEstimator) -> None:
        """Test estimating with empty content array."""
        breakdown = estimator.estimate_from_content([])

        assert len(breakdown.by_tool) == 0
        assert breakdown.total_tokens == 0

    def test_estimate_text_only_content(self, estimator: ToolTokenEstimator) -> None:
        """Test that text-only content produces no tool tokens."""
        content = [
            {"type": "text", "text": "I can help with that. Let me explain..."},
        ]

        breakdown = estimator.estimate_from_content(content)

        assert len(breakdown.by_tool) == 0

    def test_estimate_handles_missing_name(self, estimator: ToolTokenEstimator) -> None:
        """Test that tool_use blocks without name are skipped."""
        content = [
            {
                "type": "tool_use",
                "id": "toolu_01",
                # name is missing
                "input": {"file_path": "/path/to/file.py"},
            },
        ]

        breakdown = estimator.estimate_from_content(content)

        assert len(breakdown.by_tool) == 0


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_estimate_write_tool_tokens(self) -> None:
        """Test Write tool estimation convenience function."""
        content = "def hello():\n    pass\n" * 50  # ~1100 chars

        result = estimate_write_tool_tokens("/path/to/file.py", content)

        assert result.tool_name == "Write"
        assert result.tool_use_tokens > 300  # Content + path + overhead
        assert result.tool_result_tokens == 0  # No result for tool_use

    def test_estimate_read_tool_tokens(self) -> None:
        """Test Read tool estimation convenience function."""
        file_content = "# Large file\n" * 500  # ~6500 chars

        result = estimate_read_tool_tokens("/path/to/file.py", file_content)

        assert result.tool_name == "Read"
        assert result.tool_use_tokens > 15  # Small input
        assert result.tool_result_tokens > 1500  # Large result


class TestTokenAccuracy:
    """Tests for token estimation accuracy."""

    def test_known_token_count_approximation(self) -> None:
        """Test that estimation is within reasonable range of known counts.

        Note: These are approximations. Actual tokenization depends on
        the specific tokenizer used by the model.
        """
        estimator = ToolTokenEstimator()

        # "Hello, World!" is typically 4-5 tokens
        result = estimator._estimate_tokens("Hello, World!")
        assert 3 <= result <= 6

        # 100 characters of text is typically 20-30 tokens
        result = estimator._estimate_tokens("a" * 100)
        assert 20 <= result <= 35

    def test_json_estimation(self) -> None:
        """Test JSON content estimation."""
        estimator = ToolTokenEstimator()

        # JSON typically tokenizes slightly differently than plain text
        json_str = '{"key": "value", "number": 123}'
        result = estimator._estimate_tokens(json_str)

        # ~31 chars / 3.5 ≈ 9 tokens
        assert 7 <= result <= 12
