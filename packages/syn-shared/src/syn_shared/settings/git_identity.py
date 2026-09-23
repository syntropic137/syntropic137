"""Git identity and credentials for workspace commits.

See ADR-021: Isolated Workspace Architecture - Git Identity section.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, SecretStr, field_validator
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


class OperatorSettings(BaseSettings):
    """The human who sponsored a workspace, credited as a commit co-author.

    Override via ``SYN_OPERATOR_*`` environment variables.

    These two values are forwarded into every workspace container, where the
    ``prepare-commit-msg`` hook shipped by agentic-primitives appends a
    ``Co-authored-by`` trailer to the agent's commits. Without them the hook
    exits at its first guard and every agent commit is authored solely by the
    bot, so the sponsoring human earns no GitHub contribution for the work.

    Two deliberate choices:

    - **Both or neither.** The hook itself no-ops unless both variables are
      present, so forwarding one is a configuration that looks set and does
      nothing. ``attribution_env`` therefore returns an empty mapping unless
      both are populated, rather than emitting half a pair.
    - **Newlines are rejected, not stripped.** A newline in either value is how
      a second ``Co-authored-by`` trailer would be injected into every commit
      this deployment makes. The hook defends itself by stripping CR/LF, but a
      value that could only have arrived by mistake or by attack should fail
      loudly here rather than be silently rewritten two layers away.

    ``email`` must be an address attached to the GitHub account that should
    receive the credit - typically the ``users.noreply.github.com`` address.
    GitHub only counts a co-authored commit toward the contribution graph when
    the address resolves to an account, and it reports nothing when it does
    not, so a typo here fails silently and is worth checking against a real
    commit rather than assumed.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_OPERATOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    name: str | None = Field(
        default=None,
        description=(
            "Display name of the operator credited as co-author on agent commits. "
            "Requires SYN_OPERATOR_EMAIL to have any effect."
        ),
    )
    email: str | None = Field(
        default=None,
        description=(
            "Email of the operator credited as co-author on agent commits. Must be "
            "an address attached to the GitHub account that should receive the "
            "contribution. Requires SYN_OPERATOR_NAME to have any effect."
        ),
    )

    @field_validator("name", "email")
    @classmethod
    def _reject_newlines(cls, v: str | None) -> str | None:
        """Refuse a value carrying a line break.

        The value is interpolated into a commit message trailer. A line break
        would end that trailer and start another, letting one setting write an
        arbitrary second co-author onto every commit the deployment produces.
        """
        if v is not None and ("\n" in v or "\r" in v):
            raise ValueError(
                "must not contain a line break: this value becomes a commit "
                "message trailer, and a break would inject a second one"
            )
        return v

    @property
    def is_configured(self) -> bool:
        """Whether attribution will actually be applied."""
        return bool(self.name and self.email)

    @property
    def attribution_env(self) -> dict[str, str]:
        """Environment for the workspace, or empty when not fully configured.

        The keys are the names the agentic-primitives hook reads. They are
        deliberately NOT prefixed the way this class's own settings are: the
        hook is a separate artifact with its own published contract, and
        renaming these would silently disable attribution rather than fail.
        """
        if not (self.name and self.email):
            return {}
        return {"SYN_OPERATOR_NAME": self.name, "SYN_OPERATOR_EMAIL": self.email}
