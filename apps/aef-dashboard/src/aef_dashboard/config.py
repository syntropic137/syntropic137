"""Dashboard configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the dashboard server."""

    host: str
    port: int
    debug: bool
    cors_origins: list[str]

    @classmethod
    def from_env(cls) -> DashboardConfig:
        """Create config from environment variables."""
        return cls(
            host=os.getenv("AEF_DASHBOARD_HOST", "0.0.0.0"),
            port=int(os.getenv("AEF_DASHBOARD_PORT", "8000")),
            debug=os.getenv("AEF_DEBUG", "false").lower() == "true",
            cors_origins=[
                "http://localhost:5173",
                "http://localhost:3000",
            ],
        )


def get_dashboard_config() -> DashboardConfig:
    """Get dashboard configuration."""
    return DashboardConfig.from_env()
