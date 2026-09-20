"""Cross-context shared kernel: value objects and integration events."""

from syn_domain.contexts._shared.maintenance import (
    MaintenanceMode,
    MaintenancePausedError,
    MaintenancePort,
    refuse_if_paused,
)
from syn_domain.contexts._shared.repository_ref import RepositoryRef

__all__ = [
    "MaintenanceMode",
    "MaintenancePausedError",
    "MaintenancePort",
    "RepositoryRef",
    "refuse_if_paused",
]
