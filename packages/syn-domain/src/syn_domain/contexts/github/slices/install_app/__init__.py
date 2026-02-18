"""Install App feature slice.

Handles GitHub App installation events from webhooks.
"""

from syn_domain.contexts.github.domain.events.AppInstalledEvent import AppInstalledEvent
from syn_domain.contexts.github.domain.events.InstallationRevokedEvent import (
    InstallationRevokedEvent,
)
from syn_domain.contexts.github.domain.events.InstallationSuspendedEvent import (
    InstallationSuspendedEvent,
)

__all__ = [
    "AppInstalledEvent",
    "InstallationRevokedEvent",
    "InstallationSuspendedEvent",
]
