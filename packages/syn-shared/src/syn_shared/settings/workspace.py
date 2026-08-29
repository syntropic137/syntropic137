"""Workspace isolation settings for secure agent execution.

See ADR-021: Isolated Workspace Architecture

Environment Variables:
    SYN_WORKSPACE_* - Workspace backend configuration
    SYN_SECURITY_* - Security policies for all workspaces
    SYN_GIT_* - Git identity and credentials
    SYN_LOGGING_* - Container logging configuration
"""

from __future__ import annotations

import shutil
import sys
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    WorkspaceSecuritySettings,
)


class IsolationBackend(StrEnum):
    """Available isolation backends for agent workspaces."""

    FIRECRACKER = "firecracker"
    KATA = "kata"
    GVISOR = "gvisor"
    DOCKER_HARDENED = "docker_hardened"
    CLOUD = "cloud"


class CloudProvider(StrEnum):
    """Cloud sandbox providers for overflow capacity."""

    E2B = "e2b"
    MODAL = "modal"


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

    isolation_backend: IsolationBackend = Field(
        default_factory=lambda: get_default_isolation_backend(),
        description="Isolation backend to use.",
    )

    @field_validator("isolation_backend", mode="before")
    @classmethod
    def _empty_str_to_default(cls, v: object) -> object:
        """Treat empty-string env vars as 'use the default'."""
        if v == "":
            return get_default_isolation_backend()
        return v

    pool_size: int = Field(
        default=100,
        ge=0,
        le=10000,
        description="Number of pre-warmed workspace instances.",
    )

    max_concurrent: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum concurrent workspaces.",
    )

    enable_cloud_overflow: bool = Field(
        default=True,
        description="Enable cloud overflow when local capacity exceeded.",
    )

    cloud_provider: CloudProvider = Field(
        default=CloudProvider.E2B,
        description="Cloud provider for overflow: e2b or modal.",
    )

    cloud_api_key: SecretStr | None = Field(
        default=None,
        description="API key for cloud sandbox provider.",
    )

    cloud_template: str = Field(
        default="syn-workspace",
        description="Cloud sandbox template/environment name.",
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

    docker_runtime: Literal["runsc", "runc"] = Field(
        default="runsc",
        description="Docker runtime to use (runsc = gVisor, runc = native).",
    )

    docker_network: str = Field(
        default="none",
        description="Docker network for containers.",
    )

    # --- Self-hosting Syntropic (#949) -------------------------------------
    #
    # An agent working ON Syntropic cannot verify its own change: the
    # integration suite needs Postgres and an event store, and the workspace
    # has no Docker socket. Granting one would give the agent the host's
    # container runtime - a far larger capability than the tests need.
    #
    # `syn_tests/fixtures/infrastructure.py` resolves in this order:
    #     explicit env vars  >  test-stack on :15432  >  testcontainers
    #
    # so pointing the FIRST tier at an already-running stack lets the suite run
    # with no container capability at all. That is strictly less privilege than
    # socket mediation, not merely different.
    #
    # OFF BY DEFAULT, and it must stay that way: this hands every workspace
    # network reach and credentials to a database. It is a deliberate grant for
    # repos that test against real infrastructure, not a convenience.

    test_infra_enabled: bool = Field(
        default=False,
        description=(
            "Inject TEST_* infrastructure env into workspaces so an agent can run "
            "integration tests without a Docker socket (#949). Grants the workspace "
            "network access to the configured database - keep off unless the workflow "
            "is working on a repo that needs it."
        ),
    )

    test_infra_database_url: str = Field(
        default="",
        description=(
            "Value for TEST_DATABASE_URL inside the workspace. Must be reachable FROM "
            "the container, so a host-local 'localhost' URL will not work; use the "
            "compose service name or a routable address."
        ),
    )

    test_infra_eventstore_host: str = Field(
        default="",
        description="Value for TEST_EVENTSTORE_HOST inside the workspace.",
    )

    test_infra_eventstore_port: int = Field(
        default=0,
        description="Value for TEST_EVENTSTORE_PORT inside the workspace. 0 means unset.",
    )


def get_default_isolation_backend() -> IsolationBackend:
    """Select the best available isolation backend for the current platform."""
    if sys.platform == "linux" and Path("/dev/kvm").exists():
        if shutil.which("firecracker"):
            return IsolationBackend.FIRECRACKER
        if shutil.which("kata-runtime"):
            return IsolationBackend.KATA

    if _is_gvisor_available():
        return IsolationBackend.GVISOR

    if shutil.which("docker"):
        return IsolationBackend.DOCKER_HARDENED

    return IsolationBackend.GVISOR


def _is_gvisor_available() -> bool:
    """Check if gVisor (runsc) runtime is available in Docker."""
    return shutil.which("docker") is not None
