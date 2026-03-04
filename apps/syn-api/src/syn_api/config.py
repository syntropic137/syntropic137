"""API server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for the API server."""

    host: str
    port: int
    debug: bool
    cors_origins: list[str]

    @classmethod
    def from_env(cls) -> ApiConfig:
        """Create config from environment variables."""
        return cls(
            host=os.getenv("SYN_API_HOST", os.getenv("SYN_DASHBOARD_HOST", "0.0.0.0")),
            port=int(os.getenv("SYN_API_PORT", os.getenv("SYN_DASHBOARD_PORT", "8000"))),
            debug=os.getenv("SYN_DEBUG", "false").lower() == "true",
            cors_origins=[
                "http://localhost:5173",
                "http://localhost:3000",
            ],
        )


def get_api_config() -> ApiConfig:
    """Get API configuration."""
    return ApiConfig.from_env()
