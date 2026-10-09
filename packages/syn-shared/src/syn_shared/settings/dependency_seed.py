"""Where platform-warmed dependency seeds live, and how much of the disk they may use (#1714).

A seed is a uv or pnpm cache built by the platform for one lockfile, copied
into a workspace's own cache when it is provisioned so the workspace does not
install from cold. Nothing here is ever writable by a workspace: see
`syn_adapters.workspace_backends.dependency_seed`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DependencySeedSettings(BaseSettings):
    """The seed store's directory and its retention budget."""

    model_config = SettingsConfigDict(
        env_prefix="SYN_DEPENDENCY_SEED_",
        env_file=".env",
        extra="ignore",
    )

    dir: str = Field(
        default="",
        description=(
            "Directory holding platform-warmed dependency seeds, as this process "
            "sees it. Empty disables seeding: every workspace installs from cold. "
            "Put it on the workspace volume so SYN_DISK_* thresholds count it."
        ),
    )

    max_bytes: int = Field(
        default=20 * 1024**3,
        gt=0,
        description=(
            "Retention budget for all seeds together. Least recently used seeds "
            "are deleted past it. One seed of this repository is about 1-2 GiB."
        ),
    )
