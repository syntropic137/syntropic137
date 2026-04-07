"""Git identity and credentials for workspace commits.

See ADR-021: Isolated Workspace Architecture - Git Identity section.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitCredentialType(StrEnum):
    """Git credential types for authentication."""

    HTTPS = "https"
    GITHUB_APP = "github_app"
    NONE = "none"


class GitIdentitySettings(BaseSettings):
    """Git identity and credentials for workspace commits.

    Override via SYN_GIT_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_GIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    _skip_env_file: bool = False

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize settings, tracking env file configuration."""
        super().__init__(**kwargs)
        if kwargs.get("_env_file") is None:
            object.__setattr__(self, "_skip_env_file", True)

    user_name: str | None = Field(default=None, description="Git committer name (user.name).")
    user_email: str | None = Field(default=None, description="Git committer email (user.email).")
    token: SecretStr | None = Field(
        default=None, description="GitHub PAT for HTTPS authentication."
    )

    @property
    def credential_type(self) -> GitCredentialType:
        """Determine which credential type is configured."""
        from syn_shared.settings.github import GitHubAppSettings

        github = (
            GitHubAppSettings(_env_file=None)  # type: ignore[call-arg]
            if self._skip_env_file
            else GitHubAppSettings()
        )
        if github.is_configured:
            return GitCredentialType.GITHUB_APP
        if self.token:
            return GitCredentialType.HTTPS
        return GitCredentialType.NONE

    @property
    def is_configured(self) -> bool:
        """Check if identity is fully configured for commits."""
        return bool(self.user_name and self.user_email)

    @property
    def has_credentials(self) -> bool:
        """Check if credentials are configured for push."""
        return self.credential_type != GitCredentialType.NONE
