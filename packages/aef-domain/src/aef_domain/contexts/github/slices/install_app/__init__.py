"""Install App feature slice.

Handles GitHub App installation events from webhooks.
"""

from aef_domain.contexts.github.domain.events.AppInstalledEvent import AppInstalledEvent
from aef_domain.contexts.github.domain.events.InstallationRevokedEvent import (
    InstallationRevokedEvent,
)
from aef_domain.contexts.github.domain.events.InstallationSuspendedEvent import (
    InstallationSuspendedEvent,
)

__all__ = [
    "AppInstalledEvent",
    "InstallationRevokedEvent",
    "InstallationSuspendedEvent",
]
