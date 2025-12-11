"""Tests for container logging.

See ADR-021: Isolated Workspace Architecture - Container Observability.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from aef_adapters.workspaces.logging import (
    LogEntry,
    LogLevel,
    StructuredLogger,
    ViewContainerLogsTool,
)


class TestLogEntry:
    """Test LogEntry dataclass."""

    def test_to_dict(self) -> None:
        """Should convert to dictionary correctly."""
        entry = LogEntry(
            timestamp="2025-01-01T00:00:00Z",
            level=LogLevel.INFO,
            message="Test message",
            event_type="test",
            extra={"key": "value"},
        )

        d = entry.to_dict()

        assert d["timestamp"] == "2025-01-01T00:00:00Z"
        assert d["level"] == "INFO"
        assert d["message"] == "Test message"
        assert d["event_type"] == "test"
        assert d["key"] == "value"

    def test_to_json(self) -> None:
        """Should serialize to JSON string."""
        entry = LogEntry(
            timestamp="2025-01-01T00:00:00Z",
            level=LogLevel.ERROR,
            message="Error occurred",
        )

        json_str = entry.to_json()
        parsed = json.loads(json_str)

        assert parsed["level"] == "ERROR"
        assert parsed["message"] == "Error occurred"

    def test_from_json(self) -> None:
        """Should parse from JSON string."""
        json_str = '{"timestamp": "2025-01-01T00:00:00Z", "level": "WARNING", "message": "Warning"}'

        entry = LogEntry.from_json(json_str)

        assert entry.level == LogLevel.WARNING
        assert entry.message == "Warning"


class TestStructuredLogger:
    """Test StructuredLogger class."""

    @pytest.fixture
    def temp_log_file(self) -> Path:
        """Create a temporary log file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            return Path(f.name)

    def test_writes_log_entries(self, temp_log_file: Path) -> None:
        """Should write log entries to file."""
        logger = StructuredLogger(log_file=temp_log_file, level=LogLevel.DEBUG)

        logger.info("Test message", key="value")

        content = temp_log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["message"] == "Test message"
        assert entry["level"] == "INFO"
        assert entry["key"] == "value"

    def test_respects_log_level(self, temp_log_file: Path) -> None:
        """Should filter by log level."""
        logger = StructuredLogger(log_file=temp_log_file, level=LogLevel.WARNING)

        logger.debug("Debug message")  # Should be filtered
        logger.info("Info message")  # Should be filtered
        logger.warning("Warning message")  # Should be logged
        logger.error("Error message")  # Should be logged

        content = temp_log_file.read_text()
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 2

    def test_redacts_secrets(self, temp_log_file: Path) -> None:
        """Should redact sensitive patterns."""
        logger = StructuredLogger(log_file=temp_log_file, redact_secrets=True)

        logger.info("API key: sk-ant-api03-1234567890")
        logger.info("Token: ghp_abcdefgh12345678")

        content = temp_log_file.read_text()
        assert "sk-ant-api03" not in content
        assert "ghp_abcdefgh" not in content
        assert "[REDACTED]" in content

    def test_redaction_can_be_disabled(self, temp_log_file: Path) -> None:
        """Should allow disabling redaction."""
        logger = StructuredLogger(log_file=temp_log_file, redact_secrets=False)

        logger.info("API key: sk-ant-api03-1234567890")

        content = temp_log_file.read_text()
        assert "sk-ant-api03-1234567890" in content

    def test_command_logging(self, temp_log_file: Path) -> None:
        """Should log commands with metadata."""
        logger = StructuredLogger(log_file=temp_log_file)

        logger.command(
            command=["git", "clone", "https://github.com/test/repo"],
            exit_code=0,
            duration_ms=1500,
            stdout_lines=10,
        )

        content = temp_log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["event_type"] == "command"
        assert entry["exit_code"] == 0
        assert entry["duration_ms"] == 1500
        assert "git clone" in entry["message"]

    def test_tool_call_logging(self, temp_log_file: Path) -> None:
        """Should log tool calls."""
        logger = StructuredLogger(log_file=temp_log_file)

        logger.tool_call(
            tool_name="read_file",
            args={"path": "/workspace/main.py"},
            result="file content...",
            duration_ms=50,
        )

        content = temp_log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["event_type"] == "tool_call"
        assert entry["tool_name"] == "read_file"
        assert entry["args"]["path"] == "/workspace/main.py"

    def test_error_logging_with_exception(self, temp_log_file: Path) -> None:
        """Should log errors with exception details."""
        logger = StructuredLogger(log_file=temp_log_file)

        try:
            raise ValueError("Test error")
        except ValueError as e:
            logger.error("Operation failed", exception=e)

        content = temp_log_file.read_text()
        entry = json.loads(content.strip())

        assert entry["level"] == "ERROR"
        assert entry["exception_type"] == "ValueError"
        assert entry["exception_message"] == "Test error"


class TestViewContainerLogsTool:
    """Test ViewContainerLogsTool class."""

    @pytest.fixture
    def log_file_with_entries(self) -> Path:
        """Create a log file with sample entries."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # Write some sample log entries
            entries = [
                LogEntry(
                    timestamp="2025-01-01T10:00:00Z",
                    level=LogLevel.INFO,
                    message="Starting agent",
                ),
                LogEntry(
                    timestamp="2025-01-01T10:00:01Z",
                    level=LogLevel.DEBUG,
                    message="Debug info",
                ),
                LogEntry(
                    timestamp="2025-01-01T10:00:02Z",
                    level=LogLevel.WARNING,
                    message="Something suspicious",
                ),
                LogEntry(
                    timestamp="2025-01-01T10:00:03Z",
                    level=LogLevel.ERROR,
                    message="Something failed",
                    event_type="error",
                    extra={"exception_type": "ValueError", "exception_message": "bad value"},
                ),
            ]
            for entry in entries:
                f.write(entry.to_json() + "\n")
            return Path(f.name)

    @pytest.mark.asyncio
    async def test_execute_shows_logs(self, log_file_with_entries: Path) -> None:
        """Should show recent logs."""
        tool = ViewContainerLogsTool(log_file=str(log_file_with_entries))

        result = await tool.execute(lines=10)

        assert "Starting agent" in result
        assert "Debug info" in result
        assert "Something failed" in result

    @pytest.mark.asyncio
    async def test_execute_filters_by_level(self, log_file_with_entries: Path) -> None:
        """Should filter by log level."""
        tool = ViewContainerLogsTool(log_file=str(log_file_with_entries))

        result = await tool.execute(lines=10, level="WARNING")

        assert "Starting agent" not in result  # INFO
        assert "Debug info" not in result  # DEBUG
        assert "Something suspicious" in result  # WARNING
        assert "Something failed" in result  # ERROR

    @pytest.mark.asyncio
    async def test_execute_filters_by_search(self, log_file_with_entries: Path) -> None:
        """Should filter by search string."""
        tool = ViewContainerLogsTool(log_file=str(log_file_with_entries))

        result = await tool.execute(lines=10, search="agent")

        assert "Starting agent" in result
        assert "Something failed" not in result

    @pytest.mark.asyncio
    async def test_execute_shows_exception_details(self, log_file_with_entries: Path) -> None:
        """Should show exception details for errors."""
        tool = ViewContainerLogsTool(log_file=str(log_file_with_entries))

        result = await tool.execute(lines=10, level="ERROR")

        assert "ValueError" in result
        assert "bad value" in result

    @pytest.mark.asyncio
    async def test_execute_no_logs(self) -> None:
        """Should handle missing log file."""
        tool = ViewContainerLogsTool(log_file="/nonexistent/path.jsonl")

        result = await tool.execute()

        assert "No logs found" in result
