"""Dashboard configuration."""

from __future__ import annotations

from dataclasses import dataclass

from aef_shared.settings import get_settings


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the dashboard server."""

    host: str
    port: int
    debug: bool
    cors_origins: list[str]

    @classmethod
    def from_settings(cls) -> DashboardConfig:
        """Create config from application settings."""
        settings = get_settings()
        return cls(
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            debug=settings.debug,
            cors_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite defaults
        )


def get_dashboard_config() -> DashboardConfig:
    """Get dashboard configuration."""
    return DashboardConfig.from_settings()
