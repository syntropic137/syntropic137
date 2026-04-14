"""GitHub bounded context - App integration, triggers, and event pipeline.

Public API for cross-context consumers. Import from here, not from internal
subpackages (slices/, domain/aggregate_*/, etc.).

Usage:
    from syn_domain.contexts.github import (
        InstallationAggregate,
        RegisterTriggerCommand,
    )
"""

from syn_domain.contexts.github.domain import InstallationAggregate
from syn_domain.contexts.github.domain.aggregate_trigger import TriggerCondition
from syn_domain.contexts.github.domain.commands import (
    DeleteTriggerCommand,
    PauseTriggerCommand,
    RecordTriggerBlockedCommand,
    RecordTriggerFiredCommand,
    RefreshTokenCommand,
    RegisterTriggerCommand,
    ResumeTriggerCommand,
)

__all__ = [
    "DeleteTriggerCommand",
    "InstallationAggregate",
    "PauseTriggerCommand",
    "RecordTriggerBlockedCommand",
    "RecordTriggerFiredCommand",
    "RefreshTokenCommand",
    "RegisterTriggerCommand",
    "ResumeTriggerCommand",
    "TriggerCondition",
]
