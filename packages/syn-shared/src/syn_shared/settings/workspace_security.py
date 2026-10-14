"""Container logging settings for isolated agent workspaces.

See ADR-021: Isolated Workspace Architecture.

This module once also held ``WorkspaceSecuritySettings`` (``SYN_SECURITY_*``).
Nothing read it (#1805): workspace hardening comes from agentic_isolation's
``SecurityConfig.production()``, applied in ``WorkspaceService.create``, and the
live resource limits are ``SYN_WORKSPACE_*`` (#1606).
"""

from __future__ import annotations

import re

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ContainerLoggingSettings(BaseSettings):
    """Logging configuration for container observability.

    See ADR-021: Isolated Workspace Architecture - Container Observability.

    Override via SYN_LOGGING_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_LOGGING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    level: str = Field(
        default="INFO",
        description="Minimum log level for container logs.",
    )

    format: str = Field(
        default="json",
        description="Log format: 'json' for structured, 'text' for human-readable.",
    )

    log_commands: bool = Field(
        default=True, description="Log shell commands executed in container."
    )
    log_tool_calls: bool = Field(default=True, description="Log tool calls made by agents.")
    log_api_calls: bool = Field(
        default=False,
        description="Log API calls (Claude, GitHub, etc). Disabled by default - can be verbose.",
    )

    redact_secrets: bool = Field(
        default=True,
        description="Redact sensitive data in logs (API keys, tokens, passwords).",
    )

    redaction_patterns: list[str] = Field(
        default_factory=lambda: [
            r"sk-ant-[a-zA-Z0-9-]+",
            r"sk-[a-zA-Z0-9-]+",
            r"ghp_[a-zA-Z0-9]+",
            r"github_pat_[a-zA-Z0-9_]+",
            r"gho_[a-zA-Z0-9]+",
            r"ghu_[a-zA-Z0-9]+",
            r"ghs_[a-zA-Z0-9]+",
            r"ghr_[a-zA-Z0-9]+",
            r"password=[^\s&]+",
            r"token=[^\s&]+",
            r"api_key=[^\s&]+",
            r"Bearer [a-zA-Z0-9._-]+",
        ],
        description="Regex patterns for secret redaction.",
    )

    log_file_path: str = Field(
        default="/workspace/.logs/agent.jsonl",
        description="Log file path inside container.",
    )

    max_log_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max log file size in MB before rotation.",
    )

    def redact(self, value: str) -> str:
        """Redact sensitive patterns from a string."""
        if not self.redact_secrets:
            return value
        result = str(value)
        for pattern in self.redaction_patterns:
            result = re.sub(pattern, "[REDACTED]", result, flags=re.IGNORECASE)
        return result
