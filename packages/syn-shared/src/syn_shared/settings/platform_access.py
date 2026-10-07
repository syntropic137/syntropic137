"""Workspace access to the Syntropic137 API (PC-127, ADR-072).

Default OFF. While off, the API refuses every request that arrived through the
workspace ingress and no workspace is issued a platform token, so turning it
on is the only way a workspace can read the platform.

Override via SYN_PLATFORM_ACCESS_* environment variables.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformAccessSettings(BaseSettings):
    """Whether, and for how long, workspaces may call the Syntropic137 API."""

    model_config = SettingsConfigDict(
        env_prefix="SYN_PLATFORM_ACCESS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description=(
            "Let workspaces call the Syntropic137 API with a scoped, short-lived, "
            "read-only platform token (ADR-072). Default: False - no token is "
            "issued and the API refuses all workspace-ingress traffic."
        ),
    )
    token_ttl_seconds: int = Field(
        default=4 * 60 * 60,
        ge=60,
        description=(
            "Upper bound on a platform token's lifetime. A token also dies when "
            "its phase ends (it is revoked then), whichever comes first."
        ),
    )
    workspace_api_url: str = Field(
        default="http://envoy-proxy:8081/syn-platform",
        description=(
            "SYN_API_URL as seen from inside a workspace: the Envoy sidecar's "
            "/syn-platform prefix, which it forwards to the API marked as "
            "workspace ingress. The syn CLI appends /api/v1."
        ),
    )
