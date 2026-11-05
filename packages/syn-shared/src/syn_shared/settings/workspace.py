"""Workspace isolation settings for secure agent execution.

See ADR-021: Isolated Workspace Architecture

Environment Variables:
    SYN_WORKSPACE_* - Workspace backend configuration
    SYN_GIT_* - Git identity and credentials
    SYN_LOGGING_* - Container logging configuration
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator
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

DEFAULT_WORKSPACE_PIDS_LIMIT = 256
"""Processes and threads one workspace container may hold (``--pids-limit``).

The value agentic-workspace's ``SecurityConfig`` defaults to; syn137 owns it
now and passes it explicitly, so a workspace's limit does not move when the
submodule's default does."""

MIN_WORKSPACE_PIDS_LIMIT = 64
"""Below this an agent CLI and its shell tools cannot start."""


#: What `WorkspaceSettings.runtime` reads (env_prefix + field name). Named so
#: the doctor reports the same variable the settings parse.
ENV_SYN_WORKSPACE_RUNTIME = "SYN_WORKSPACE_RUNTIME"


class WorkspaceRuntime(StrEnum):
    """The OCI runtime an operator asks workspace containers to run under.

    Mirrors agentic-workspace's ``WorkspaceRuntime`` value for value; the
    adapter maps one to the other. Whether a runtime is actually registered,
    and which one auto mode picks, is decided by agentic-workspace's resolver,
    never here.
    """

    RUNC = "runc"
    GVISOR = "gvisor"
    KATA = "kata"
    SYSBOX = "sysbox"


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
        description=(
            "Memory limit applied to each workspace container, in MB, unless its "
            "phase requests otherwise with resources.memory_mb."
        ),
    )

    memory_max_mb: int | None = Field(
        default=None,
        ge=256,
        description=(
            "The most memory, in MB, one phase may request for its workspace with "
            "resources.memory_mb (okrs-51p.30). Unset means no phase may ask for "
            "more than SYN_WORKSPACE_MEMORY_LIMIT_MB. A request above it is refused "
            "at install and at start, never clamped. A larger workspace counts as "
            "more than one run against the host: each process admits workspaces up "
            "to SYN_EXECUTION_MAX_CONCURRENT x SYN_WORKSPACE_MEMORY_LIMIT_MB in total, "
            "so a 16384 MB phase waits for four default-sized ones. Must be at least "
            "SYN_WORKSPACE_MEMORY_LIMIT_MB."
        ),
    )

    @model_validator(mode="after")
    def _ceiling_covers_the_default(self) -> WorkspaceSettings:
        """A ceiling below the default would refuse a phase that asked for nothing."""
        if self.memory_max_mb is not None and self.memory_max_mb < self.memory_limit_mb:
            msg = (
                f"SYN_WORKSPACE_MEMORY_MAX_MB ({self.memory_max_mb}) is below "
                f"SYN_WORKSPACE_MEMORY_LIMIT_MB ({self.memory_limit_mb}). The ceiling "
                "bounds what a phase may request, so it must cover the default."
            )
            raise ValueError(msg)
        return self

    @property
    def memory_ceiling_mb(self) -> int:
        """The most memory a phase may request: the ceiling, or the default when unset."""
        return self.memory_limit_mb if self.memory_max_mb is None else self.memory_max_mb

    pids_limit: int = Field(
        default=DEFAULT_WORKSPACE_PIDS_LIMIT,
        ge=MIN_WORKSPACE_PIDS_LIMIT,
        description=(
            "Processes and threads each workspace container may hold (--pids-limit), "
            "unless its phase requests otherwise with resources.pids_limit. Threads "
            "count: a parallel test suite can exceed the default."
        ),
    )

    pids_max: int | None = Field(
        default=None,
        ge=MIN_WORKSPACE_PIDS_LIMIT,
        description=(
            "The highest pids limit one phase may request for its workspace with "
            "resources.pids_limit (okrs-51p.30). Unset means no phase may ask for "
            "more than SYN_WORKSPACE_PIDS_LIMIT. A request above it is refused at "
            "install and at start, never clamped. Must be at least "
            "SYN_WORKSPACE_PIDS_LIMIT."
        ),
    )

    @model_validator(mode="after")
    def _pids_ceiling_covers_the_default(self) -> WorkspaceSettings:
        """A pids ceiling below the default would refuse a phase that asked for nothing."""
        if self.pids_max is not None and self.pids_max < self.pids_limit:
            msg = (
                f"SYN_WORKSPACE_PIDS_MAX ({self.pids_max}) is below "
                f"SYN_WORKSPACE_PIDS_LIMIT ({self.pids_limit}). The ceiling bounds "
                "what a phase may request, so it must cover the default."
            )
            raise ValueError(msg)
        return self

    @property
    def pids_ceiling(self) -> int:
        """The highest pids limit a phase may request: the ceiling, or the default when unset."""
        return self.pids_limit if self.pids_max is None else self.pids_max

    cpu_limit: float = Field(
        default=DEFAULT_WORKSPACE_CPU_LIMIT,
        gt=0,
        description="CPU limit applied to each workspace container, in cores.",
    )

    runtime: WorkspaceRuntime | None = Field(
        default=None,
        description=(
            "OCI runtime for workspace containers: runc, gvisor, kata or sysbox. "
            "Unset means auto (gVisor when Docker has it registered, else runc). "
            "An explicit runtime Docker does not have fails the workspace; it "
            "never falls back to runc."
        ),
    )

    @field_validator("runtime", mode="before")
    @classmethod
    def _empty_runtime_is_auto(cls, v: object) -> object:
        """An empty SYN_WORKSPACE_RUNTIME means auto; any other unknown value is refused."""
        if v == "":
            return None
        return v
