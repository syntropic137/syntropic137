"""Cross-context shared kernel: value objects and integration events."""

from syn_domain.contexts._shared.maintenance import (
    AdmissionGate,
    AdmissionTicket,
    MaintenanceMode,
    MaintenancePausedError,
    MaintenancePort,
    carrying,
    refuse_if_paused,
)
from syn_domain.contexts._shared.repository_ref import RepositoryRef

__all__ = [
    "AdmissionGate",
    "AdmissionTicket",
    "MaintenanceMode",
    "MaintenancePausedError",
    "MaintenancePort",
    "RepositoryRef",
    "carrying",
    "refuse_if_paused",
]
