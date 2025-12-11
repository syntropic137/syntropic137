"""Container logging for isolated workspace observability.

This module provides structured logging for operations inside containers,
with secret redaction and external streaming capabilities.

See ADR-021: Isolated Workspace Architecture - Container Observability.

Usage (inside container):
    from aef_adapters.workspaces.logging import StructuredLogger

    logger = StructuredLogger()
    logger.command(["git", "clone", "..."], exit_code=0, duration_ms=1500)
    logger.tool_call("read_file", {"path": "/workspace/main.py"})
    logger.error("Failed to compile", exception=e)

Usage (from orchestrator):
    from aef_adapters.workspaces.logging import ContainerLogStreamer

    streamer = ContainerLogStreamer()
    async for log in streamer.stream_logs(container_id):
        print(log["message"])
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aef_adapters.workspaces.types import IsolatedWorkspace


class LogLevel(str, Enum):
    """Log levels for container logging."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class LogEntry:
    """A structured log entry.

    Attributes:
        timestamp: ISO-8601 timestamp
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        message: Log message (may be redacted)
        event_type: Type of event (command, tool_call, api_call, error, info)
        extra: Additional structured data
    """

    timestamp: str
    level: LogLevel
    message: str
    event_type: str = "info"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "message": self.message,
            "event_type": self.event_type,
            **self.extra,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> LogEntry:
        """Parse from JSON string."""
        data = json.loads(json_str)
        return cls(
            timestamp=data.get("timestamp", ""),
            level=LogLevel(data.get("level", "INFO")),
            message=data.get("message", ""),
            event_type=data.get("event_type", "info"),
            extra={
                k: v
                for k, v in data.items()
                if k not in ("timestamp", "level", "message", "event_type")
            },
        )


class StructuredLogger:
    """Structured JSON logger for container operations.

    Features:
    - JSON-formatted logs for machine parsing
    - Secret redaction (API keys, tokens, passwords)
    - Log levels for filtering
    - Ephemeral storage (tmpfs in container)

    Usage:
        logger = StructuredLogger()
        logger.info("Starting agent execution")
        logger.command(["pip", "install", "requests"], exit_code=0)
        logger.error("Failed to connect", exception=e)
    """

    # Default redaction patterns (from ContainerLoggingSettings)
    DEFAULT_REDACTION_PATTERNS: ClassVar[list[str]] = [
        r"sk-ant-[a-zA-Z0-9-]+",  # Anthropic API keys
        r"sk-[a-zA-Z0-9-]+",  # OpenAI API keys
        r"ghp_[a-zA-Z0-9]+",  # GitHub PAT (classic)
        r"github_pat_[a-zA-Z0-9_]+",  # GitHub PAT (fine-grained)
        r"gho_[a-zA-Z0-9]+",  # GitHub OAuth token
        r"password=[^\s&]+",  # Password in URLs/params
        r"token=[^\s&]+",  # Token in URLs/params
        r"Bearer [a-zA-Z0-9._-]+",  # Bearer tokens
    ]

    def __init__(
        self,
        log_file: str | Path = "/workspace/.logs/agent.jsonl",
        level: LogLevel = LogLevel.INFO,
        redact_secrets: bool = True,
        redaction_patterns: list[str] | None = None,
    ) -> None:
        """Initialize the structured logger.

        Args:
            log_file: Path to log file (JSONL format)
            level: Minimum log level
            redact_secrets: Whether to redact sensitive patterns
            redaction_patterns: Custom patterns to redact
        """
        self.log_file = Path(log_file)
        self.level = level
        self.redact_secrets = redact_secrets
        self.redaction_patterns = redaction_patterns or self.DEFAULT_REDACTION_PATTERNS
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensure log directory exists."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _redact(self, value: Any) -> Any:
        """Redact sensitive patterns from a value.

        Args:
            value: Value that may contain secrets

        Returns:
            Value with secrets replaced by [REDACTED]
        """
        if not self.redact_secrets:
            return value

        if isinstance(value, str):
            result = value
            for pattern in self.redaction_patterns:
                result = re.sub(pattern, "[REDACTED]", result, flags=re.IGNORECASE)
            return result
        elif isinstance(value, dict):
            return {k: self._redact(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    def _should_log(self, level: LogLevel) -> bool:
        """Check if this level should be logged."""
        levels = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR]
        return levels.index(level) >= levels.index(self.level)

    def _write_entry(self, entry: LogEntry) -> None:
        """Write a log entry to file."""
        if not self._should_log(entry.level):
            return

        with self.log_file.open("a") as f:
            f.write(entry.to_json() + "\n")

    def log(self, level: LogLevel, message: str, event_type: str = "info", **extra: Any) -> None:
        """Write a log entry.

        Args:
            level: Log level
            message: Log message
            event_type: Type of event
            **extra: Additional structured data
        """
        entry = LogEntry(
            timestamp=datetime.now(UTC).isoformat(),
            level=level,
            message=self._redact(message),
            event_type=event_type,
            extra=self._redact(extra),
        )
        self._write_entry(entry)

    def debug(self, message: str, **extra: Any) -> None:
        """Log a debug message."""
        self.log(LogLevel.DEBUG, message, "debug", **extra)

    def info(self, message: str, **extra: Any) -> None:
        """Log an info message."""
        self.log(LogLevel.INFO, message, "info", **extra)

    def warning(self, message: str, **extra: Any) -> None:
        """Log a warning message."""
        self.log(LogLevel.WARNING, message, "warning", **extra)

    def error(self, message: str, exception: Exception | None = None, **extra: Any) -> None:
        """Log an error message.

        Args:
            message: Error message
            exception: Optional exception that caused the error
            **extra: Additional data
        """
        if exception:
            extra["exception_type"] = type(exception).__name__
            extra["exception_message"] = str(exception)
        self.log(LogLevel.ERROR, message, "error", **extra)

    def command(
        self,
        command: list[str],
        exit_code: int,
        duration_ms: float | None = None,
        stdout_lines: int = 0,
        stderr_lines: int = 0,
        cwd: str | None = None,
    ) -> None:
        """Log a shell command execution.

        Args:
            command: Command and arguments
            exit_code: Exit code (0 = success)
            duration_ms: Execution duration in milliseconds
            stdout_lines: Number of stdout lines
            stderr_lines: Number of stderr lines
            cwd: Working directory
        """
        level = LogLevel.INFO if exit_code == 0 else LogLevel.WARNING
        cmd_str = " ".join(command)
        self.log(
            level,
            f"Command: {cmd_str}",
            "command",
            command=self._redact(command),
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            cwd=cwd,
        )

    def tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log a tool call.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            result: Tool result (truncated if large)
            duration_ms: Execution duration in milliseconds
        """
        # Truncate large results
        result_str = str(result) if result is not None else None
        if result_str and len(result_str) > 1000:
            result_str = result_str[:1000] + "...[truncated]"

        self.log(
            LogLevel.INFO,
            f"Tool: {tool_name}",
            "tool_call",
            tool_name=tool_name,
            args=self._redact(args),
            result=self._redact(result_str),
            duration_ms=duration_ms,
        )

    def api_call(
        self,
        service: str,
        endpoint: str,
        status_code: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log an API call.

        Args:
            service: Service name (e.g., "anthropic", "github")
            endpoint: API endpoint
            status_code: HTTP status code
            duration_ms: Call duration in milliseconds
        """
        level = LogLevel.INFO
        if status_code and status_code >= 400:
            level = LogLevel.WARNING

        self.log(
            level,
            f"API: {service} {endpoint}",
            "api_call",
            service=service,
            endpoint=endpoint,
            status_code=status_code,
            duration_ms=duration_ms,
        )


class ContainerLogStreamer:
    """Stream logs from a container for orchestrator access.

    Provides external access to container logs via Docker exec.

    Usage:
        streamer = ContainerLogStreamer()
        logs = await streamer.get_recent_logs(container_id, n=100)
        async for log in streamer.stream_logs(container_id):
            process(log)
    """

    def __init__(self, log_file: str = "/workspace/.logs/agent.jsonl") -> None:
        """Initialize the log streamer.

        Args:
            log_file: Path to log file inside container
        """
        self.log_file = log_file

    async def get_recent_logs(
        self,
        container_id: str,
        n: int = 100,
        level: LogLevel | None = None,
        event_type: str | None = None,
    ) -> list[LogEntry]:
        """Get the most recent log entries from a container.

        Args:
            container_id: Docker container ID
            n: Number of entries to retrieve
            level: Filter by minimum log level
            event_type: Filter by event type

        Returns:
            List of LogEntry objects
        """
        # Use docker exec to tail the log file
        cmd = ["docker", "exec", container_id, "tail", "-n", str(n * 2), self.log_file]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            entries = []
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = LogEntry.from_json(line)
                    # Apply filters
                    if level and LogLevel[entry.level.value] < level:
                        continue
                    if event_type and entry.event_type != event_type:
                        continue
                    entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

            return entries[-n:]

        except Exception:
            return []

    async def stream_logs(
        self,
        container_id: str,
        follow: bool = True,
    ) -> AsyncIterator[LogEntry]:
        """Stream logs from a container in real-time.

        Args:
            container_id: Docker container ID
            follow: Whether to follow (like tail -f)

        Yields:
            LogEntry objects as they arrive
        """
        cmd = ["docker", "exec", container_id, "tail"]
        if follow:
            cmd.append("-f")
        cmd.append(self.log_file)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break

                try:
                    entry = LogEntry.from_json(line.decode().strip())
                    yield entry
                except (json.JSONDecodeError, KeyError):
                    continue
        finally:
            proc.terminate()

    async def search_logs(
        self,
        container_id: str,
        query: str,
        n: int = 50,
    ) -> list[LogEntry]:
        """Search logs for a pattern.

        Args:
            container_id: Docker container ID
            query: Search string
            n: Max results

        Returns:
            Matching LogEntry objects
        """
        # Use grep inside container
        cmd = ["docker", "exec", container_id, "grep", "-i", query, self.log_file]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            entries = []
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = LogEntry.from_json(line)
                    entries.append(entry)
                    if len(entries) >= n:
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

            return entries

        except Exception:
            return []


class ViewContainerLogsTool:
    """Agent tool for viewing container logs from inside.

    This tool allows the inner agent to inspect its own logs
    for debugging and monitoring.

    Usage:
        tool = ViewContainerLogsTool()
        result = await tool.execute(lines=50, level="ERROR")
    """

    def __init__(self, log_file: str = "/workspace/.logs/agent.jsonl") -> None:
        """Initialize the tool.

        Args:
            log_file: Path to log file
        """
        self.log_file = Path(log_file)

    async def execute(
        self,
        lines: int = 50,
        level: str | None = None,
        event_type: str | None = None,
        search: str | None = None,
    ) -> str:
        """View recent container logs.

        Args:
            lines: Number of lines to show
            level: Filter by level (DEBUG, INFO, WARNING, ERROR)
            event_type: Filter by event type (command, tool_call, api_call, error)
            search: Search string

        Returns:
            Formatted log output
        """
        if not self.log_file.exists():
            return "No logs found yet."

        entries = []
        with self.log_file.open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = LogEntry.from_json(line.strip())

                    # Apply filters
                    if level:
                        levels = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR]
                        min_level = LogLevel(level.upper())
                        if levels.index(entry.level) < levels.index(min_level):
                            continue

                    if event_type and entry.event_type != event_type:
                        continue

                    if search and search.lower() not in entry.message.lower():
                        continue

                    entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

        # Take last N entries
        entries = entries[-lines:]

        if not entries:
            return "No logs matching criteria."

        # Format output
        output_lines = []
        for entry in entries:
            ts = entry.timestamp[:19]  # Truncate microseconds
            level_str = entry.level.value.ljust(7)
            output_lines.append(f"[{ts}] {level_str} {entry.message}")

            # Show extra data for some event types
            if entry.event_type == "command" and "exit_code" in entry.extra:
                output_lines.append(f"         exit_code={entry.extra['exit_code']}")
            if entry.event_type == "error" and "exception_type" in entry.extra:
                output_lines.append(
                    f"         {entry.extra['exception_type']}: {entry.extra.get('exception_message', '')}"
                )

        return "\n".join(output_lines)


def create_container_logger(_workspace: IsolatedWorkspace) -> StructuredLogger:
    """Create a StructuredLogger configured for a workspace.

    Uses ContainerLoggingSettings from environment.

    Args:
        workspace: The isolated workspace

    Returns:
        Configured StructuredLogger
    """
    from aef_shared.settings import get_settings

    settings = get_settings()
    logging_settings = settings.container_logging

    return StructuredLogger(
        log_file=logging_settings.log_file_path,
        level=LogLevel(logging_settings.level),
        redact_secrets=logging_settings.redact_secrets,
        redaction_patterns=logging_settings.redaction_patterns,
    )
