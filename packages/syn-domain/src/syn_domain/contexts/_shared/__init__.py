"""Cross-context shared kernel: value objects and integration events."""

from syn_domain.contexts._shared.admission_refusal import AdmissionRefusedError
from syn_domain.contexts._shared.disk_space import (
    DiskCheck,
    DiskSpaceGuard,
    DiskSpacePort,
    DiskState,
    DiskUsage,
    InsufficientDiskSpaceError,
)
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
    guarantee_settled,
    refuse_if_paused,
)
from syn_domain.contexts._shared.repository_ref import RepositoryRef

__all__ = [
    "AdmissionAnnouncementFailedError",
    "AdmissionAnnouncer",
    "AdmissionGate",
    "AdmissionOpenEvent",
    "AdmissionRefusedError",
    "AdmissionTicket",
    "DiskCheck",
    "DiskSpaceGuard",
    "DiskSpacePort",
    "DiskState",
    "DiskUsage",
    "InsufficientDiskSpaceError",
    "MaintenanceMode",
    "MaintenancePausedError",
    "MaintenancePort",
    "RepositoryRef",
    "carrying",
    "guarantee_settled",
    "refuse_if_paused",
]
