"""Lifecycle operations — startup, shutdown, and health checks."""

from syn_api.services.lifecycle._orchestrator import health_check, shutdown, startup

__all__ = ["health_check", "shutdown", "startup"]
