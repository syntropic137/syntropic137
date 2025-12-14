"""Install App feature slice.

Handles GitHub App installation events from webhooks.
"""

from aef_domain.contexts.github.install_app.AppInstalledEvent import AppInstalledEvent
from aef_domain.contexts.github.install_app.InstallationRevokedEvent import (
    InstallationRevokedEvent,
)
from aef_domain.contexts.github.install_app.InstallationSuspendedEvent import (
    InstallationSuspendedEvent,
)

__all__ = [
    "AppInstalledEvent",
    "InstallationRevokedEvent",
    "InstallationSuspendedEvent",
]
