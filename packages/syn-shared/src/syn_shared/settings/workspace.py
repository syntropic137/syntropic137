"""Workspace isolation settings for secure agent execution.

See ADR-021: Isolated Workspace Architecture

Environment Variables:
    SYN_WORKSPACE_* - Workspace backend configuration
    SYN_GIT_* - Git identity and credentials
    SYN_LOGGING_* - Container logging configuration
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Re-export from sub-modules for backwards compatibility
from syn_shared.settings.git_identity import (  # noqa: F401
    GitCredentialType,
    GitIdentitySettings,
)
from syn_shared.settings.git_identity_resolver import (
    GitIdentityResolver as GitIdentityResolver,
)
from syn_shared.settings.workspace_images import (
    DEFAULT_WORKSPACE_IMAGE,
)
from syn_shared.settings.workspace_security import (  # noqa: F401
    ContainerLoggingSettings,
)

DEFAULT_WORKSPACE_MEMORY_LIMIT_MB = 4096
"""Memory ceiling for one workspace container, in MB."""

DEFAULT_WORKSPACE_CPU_LIMIT = 2.0
"""CPU ceiling for one workspace container, in cores."""


class WorkspaceSettings(BaseSettings):
    """Workspace isolation backend configuration.

    Override via SYN_WORKSPACE_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYN_WORKSPACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    docker_image: str = Field(
        default=DEFAULT_WORKSPACE_IMAGE,
        description="Docker image for Claude agent execution.",
    )

    @field_validator("docker_image", mode="before")
    @classmethod
    def _reject_blank_image(cls, value: object) -> object:
        """An explicitly blank image is an error, not a silent fallback (#954).

        The first version of this fix quietly substituted the default for any
        blank value. A codex review pointed out that recreates the very
        false-pass #954 exists to eliminate:

            SYN_WORKSPACE_DOCKER_IMAGE="$CANDIDATE_IMAGE" docker compose up

        If ``CANDIDATE_IMAGE`` is accidentally empty, the operator runs the
        pinned default while believing they tested the candidate -- and nothing
        says so. That is exactly the class of bug this issue is about.

        Compose distinguishes the two states, so the settings layer must too.
        A bare ``SYN_WORKSPACE_DOCKER_IMAGE:`` key resolves to null and is
        removed from the container environment when the variable is unset, so
        an absent value never reaches here and the field default applies. A
        value that DOES arrive and is blank was set deliberately, and is wrong.
        """
        if isinstance(value, str) and not value.strip():
            msg = (
                "SYN_WORKSPACE_DOCKER_IMAGE is set but empty. Unset it to use the "
                "pinned default, or give it a full image reference. Refusing to "
                "silently fall back, because that would run a different image "
                "than the one you meant to test."
            )
            raise ValueError(msg)
        return value

    memory_limit_mb: int = Field(
        default=DEFAULT_WORKSPACE_MEMORY_LIMIT_MB,
        ge=256,
        description="Memory limit applied to each workspace container, in MB.",
    )

    cpu_limit: float = Field(
        default=DEFAULT_WORKSPACE_CPU_LIMIT,
        gt=0,
        description="CPU limit applied to each workspace container, in cores.",
    )
