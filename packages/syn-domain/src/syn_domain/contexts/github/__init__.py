"""GitHub bounded context - App integration, triggers, and event pipeline.

Public API for cross-context consumers. Import from here, not from internal
subpackages (slices/, domain/aggregate_*/, etc.).

Usage:
    from syn_domain.contexts.github import (
        InstallationAggregate,
        RegisterTriggerCommand,
    )
"""

# Aggregates
from syn_domain.contexts.github.domain import InstallationAggregate
from syn_domain.contexts.github.domain.aggregate_trigger import TriggerCondition
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import TriggerConfig
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerStatus import TriggerStatus

# Commands
from syn_domain.contexts.github.domain.commands import (
    DeleteTriggerCommand,
    PauseTriggerCommand,
    RecordTriggerBlockedCommand,
    RecordTriggerFiredCommand,
    RefreshTokenCommand,
    RegisterTriggerCommand,
    ResumeTriggerCommand,
)

# Events
from syn_domain.contexts.github.domain.events.AppInstalledEvent import AppInstalledEvent
from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import TriggerBlockedEvent
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent

# Handlers
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)
from syn_domain.contexts.github.slices.manage_trigger.ManageTriggerHandler import (
    ManageTriggerHandler,
)
from syn_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)

# Event pipeline types
from syn_domain.contexts.github.slices.event_pipeline.check_run_synthesizer import (
    synthesize_check_run_event,
)
from syn_domain.contexts.github.slices.event_pipeline.dedup_keys import compute_dedup_key
from syn_domain.contexts.github.slices.event_pipeline.dedup_port import DedupPort
from syn_domain.contexts.github.slices.event_pipeline.event_type_mapper import (
    map_events_api_to_normalized,
)
from syn_domain.contexts.github.slices.event_pipeline.normalized_event import (
    EventSource,
    NormalizedEvent,
)
from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import (
    PendingSHA,
    PendingSHAStore,
)
from syn_domain.contexts.github.slices.event_pipeline.pipeline import EventPipeline
from syn_domain.contexts.github.slices.event_pipeline.poller_state import PollerMode, PollerState

# Projections
from syn_domain.contexts.github.slices.get_installation.projection import (
    get_installation_projection,
)
from syn_domain.contexts.github.slices.list_triggers.projection import get_trigger_rule_projection
from syn_domain.contexts.github.slices.trigger_history.GetTriggerHistoryHandler import (
    get_trigger_history_handler,
)

# Queries
from syn_domain.contexts.github.domain.queries.get_trigger_history import GetTriggerHistoryQuery

# Read models
from syn_domain.contexts.github.domain.read_models.installation import Installation
from syn_domain.contexts.github.domain.read_models.trigger_rule import TriggerRule

# Shared types
from syn_domain.contexts.github._shared.trigger_evaluation_types import (
    TriggerDeferredResult,
    TriggerMatchResult,
)
from syn_domain.contexts.github._shared.trigger_presets import create_preset_command
from syn_domain.contexts.github._shared.trigger_query_store import (
    TriggerQueryStore,
    get_trigger_query_store,
)

__all__ = [
    # Aggregates
    "InstallationAggregate",
    "TriggerCondition",
    "TriggerConfig",
    "TriggerRuleAggregate",
    "TriggerStatus",
    # Commands
    "DeleteTriggerCommand",
    "PauseTriggerCommand",
    "RecordTriggerBlockedCommand",
    "RecordTriggerFiredCommand",
    "RefreshTokenCommand",
    "RegisterTriggerCommand",
    "ResumeTriggerCommand",
    # Events
    "AppInstalledEvent",
    "TriggerBlockedEvent",
    "TriggerFiredEvent",
    # Handlers
    "EvaluateWebhookHandler",
    "ManageTriggerHandler",
    "RegisterTriggerHandler",
    # Event pipeline types
    "DedupPort",
    "EventPipeline",
    "EventSource",
    "NormalizedEvent",
    "PendingSHA",
    "PendingSHAStore",
    "PollerMode",
    "PollerState",
    "compute_dedup_key",
    "map_events_api_to_normalized",
    "synthesize_check_run_event",
    # Projections
    "get_installation_projection",
    "get_trigger_history_handler",
    "get_trigger_query_store",
    "get_trigger_rule_projection",
    # Queries
    "GetTriggerHistoryQuery",
    # Read models
    "Installation",
    "TriggerRule",
    # Shared types
    "TriggerDeferredResult",
    "TriggerMatchResult",
    "TriggerQueryStore",
    "create_preset_command",
]
