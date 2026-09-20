"""Cross-context shared kernel: value objects and integration events."""

from syn_domain.contexts._shared.integration_events import AdmissionOpenEvent
from syn_domain.contexts._shared.maintenance import (
    AdmissionAnnouncementFailedError,
    AdmissionAnnouncer,
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
    "AdmissionAnnouncementFailedError",
    "AdmissionAnnouncer",
    "AdmissionGate",
    "AdmissionOpenEvent",
    "AdmissionTicket",
    "MaintenanceMode",
    "MaintenancePausedError",
    "MaintenancePort",
    "RepositoryRef",
    "carrying",
    "refuse_if_paused",
]
