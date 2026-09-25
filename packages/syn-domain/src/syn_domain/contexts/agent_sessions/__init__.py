"""Sessions bounded context - tracks agent execution sessions.

Public API for cross-context consumers (ADR-062). This context provides
aggregates, commands, and events for tracking agent sessions including
token usage and operations. Cost is Lane 2 telemetry — use
``SessionCostQueryService`` for per-session cost (#695).

Usage:
    from syn_domain.contexts.agent_sessions import (
        AgentSessionAggregate,
        StartSessionCommand,
        CompleteSessionCommand,
        # Convenience functions for recording operations
        record_tool_started,
        record_tool_completed,
        record_message_response,
    )

    # Create session
    session = AgentSessionAggregate()
    session.start_session(StartSessionCommand(
        workflow_id="wf-123",
        phase_id="research",
        agent_provider="claude",
    ))

    # Record tool operations (type-safe convenience functions)
    cmd = record_tool_started(str(session.id), "Read", "tool-123", {"path": "/foo"})
    session.record_operation(cmd)

    cmd = record_tool_completed(str(session.id), "Read", "tool-123", "file contents...")
    session.record_operation(cmd)

    # Complete session
    session.complete_session(CompleteSessionCommand(
        aggregate_id=str(session.id),
        success=True,
    ))
"""

from syn_domain.contexts.agent_sessions._shared import (
    AgentLaunch,
    AgentSessionAggregate,
    OperationRecord,
    OperationType,
    SessionStatus,
    TokenMetrics,
)
from syn_domain.contexts.agent_sessions.canonical_usage import (
    CANONICAL_SESSION_USAGE_CTE,
    CANONICAL_USAGE_EVENT_FILTER,
    price_canonical_row,
)
from syn_domain.contexts.agent_sessions.delegate_import import import_phase_delegates
from syn_domain.contexts.agent_sessions.delegate_usage import (
    SessionStorePort,
    StoredSession,
)
from syn_domain.contexts.agent_sessions.domain.aggregate_inventory_reconciliation.InventoryReconciliationAggregate import (
    InventoryReconciliationAggregate,
)
from syn_domain.contexts.agent_sessions.domain.events.agent_observation import (
    ObservationType,
)
from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)
from syn_domain.contexts.agent_sessions.domain.events.observation_payloads import (
    SessionSummaryData,
    TokenUsageData,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CaptureReceipt,
    EvidenceRetraction,
    IdentityBinding,
    InventoryCoverage,
    InventoryGap,
    InventoryNode,
    LineageEdge,
    Membership,
    ResolvedInventory,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.import_ledger import (
    BilledUsage,
    ImportLedger,
    ImportLedgerPort,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
    EvidenceBatch,
    EvidencePage,
    PendingEvidence,
    SessionEvidenceReadPort,
    SessionEvidenceWritePort,
    StoredEvidenceBatch,
)
from syn_domain.contexts.agent_sessions.ports.SessionInventoryJobPort import (
    InventoryJob,
    InventoryJobLease,
    InventoryLeaseLost,
    SessionInventoryJobPort,
)
from syn_domain.contexts.agent_sessions.ports.SessionInventoryReadPort import (
    InventoryCounts,
    InventoryItem,
    InventoryPage,
    InventorySnapshot,
    ItemKind,
    SessionInventoryReadPort,
)
from syn_domain.contexts.agent_sessions.ports.SessionInventoryWritePort import (
    InventoryNotFound,
    InventoryPublicationConflict,
    SessionInventoryWritePort,
)
from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
    ArchivedTranscript,
    SessionTranscriptArchivePort,
    TranscriptDeletedError,
    TranscriptIntegrityError,
)
from syn_domain.contexts.agent_sessions.recorded_model_rows import (
    HAS_REQUESTED_MODEL_COLUMN,
    REQUESTED_MODEL_COLUMN,
    pick_primary_model,
    recorded_model_from_row,
    recorded_model_group_by,
    recorded_model_select,
)
from syn_domain.contexts.agent_sessions.slices.canonical_totals import (
    CanonicalTotals,
    CanonicalUsageQueryService,
)
from syn_domain.contexts.agent_sessions.slices.complete_session import (
    CompleteSessionCommand,
    SessionCompletedEvent,
)
from syn_domain.contexts.agent_sessions.slices.complete_session.CompleteSessionHandler import (
    CompleteSessionHandler,
)
from syn_domain.contexts.agent_sessions.slices.mark_agent_launched import (
    AgentLaunchedEvent,
    MarkAgentLaunchedCommand,
)
from syn_domain.contexts.agent_sessions.slices.mark_agent_launched.MarkAgentLaunchedHandler import (
    MarkAgentLaunchedHandler,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.BuildInventorySnapshotHandler import (
    BuildInventorySnapshotHandler,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.InventoryStepHandler import (
    InventoryStepHandler,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.projection import (
    InventoryReconciliationProcessManager,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.RefreshSessionInventoryHandler import (
    RefreshSessionInventoryHandler,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.SchedulePendingInventoryHandler import (
    SchedulePendingInventoryHandler,
)
from syn_domain.contexts.agent_sessions.slices.record_operation import (
    OperationRecordedEvent,
    RecordOperationCommand,
    # Convenience factory functions
    record_error,
    record_message_request,
    record_message_response,
    record_thinking,
    record_tool_blocked,
    record_tool_completed,
    record_tool_started,
)
from syn_domain.contexts.agent_sessions.slices.record_operation.RecordOperationHandler import (
    RecordOperationHandler,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import (
    CostCalculator,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.query_service import (
    SessionCostQueryService,
)
from syn_domain.contexts.agent_sessions.slices.start_session import (
    SessionStartedEvent,
    StartSessionCommand,
)
from syn_domain.contexts.agent_sessions.slices.start_session.StartSessionHandler import (
    StartSessionHandler,
)
from syn_domain.contexts.agent_sessions.transcript_usage import (
    PricedUsage,
    RolloutDocument,
    RolloutRecord,
    StoredTranscript,
    model_from_rollout,
)

from .domain.read_models.transcript_body_state import TranscriptBodyState

__all__ = [
    "CANONICAL_SESSION_USAGE_CTE",
    "CANONICAL_USAGE_EVENT_FILTER",
    "HAS_REQUESTED_MODEL_COLUMN",
    "REQUESTED_MODEL_COLUMN",
    "AcquisitionStatusEvidence",
    "AgentLaunch",
    "AgentLaunchedEvent",
    "AgentSessionAggregate",
    "ArchivedTranscript",
    "BilledUsage",
    "BodyAvailability",
    "BuildInventorySnapshotHandler",
    "CanonicalTotals",
    "CanonicalUsageQueryService",
    "CaptureEvidence",
    "CaptureLocalTranscriptHandler",
    "CaptureReceipt",
    "CaptureSpool",
    "CaptureSpoolLease",
    "CaptureSpoolLeaseLost",
    "CataloguedCapture",
    "CompleteSessionCommand",
    "CompleteSessionHandler",
    "CostCalculator",
    "EvidenceBatch",
    "EvidenceClass",
    "EvidencePage",
    "EvidenceReference",
    "EvidenceRetraction",
    "HostSessionEvidenceProjector",
    "IdentityBinding",
    "IdentityBindingEvidence",
    "ImportLedger",
    "ImportLedgerPort",
    "InventoryClockAggregate",
    "InventoryCounts",
    "InventoryCoverage",
    "InventoryGap",
    "InventoryItem",
    "InventoryJob",
    "InventoryJobLease",
    "InventoryLeaseLost",
    "InventoryNode",
    "InventoryNodeRef",
    "InventoryNotFound",
    "InventoryPage",
    "InventoryPublicationConflict",
    "InventoryReconciliationAggregate",
    "InventoryReconciliationProcessManager",
    "InventoryReconciliationSweepEvent",
    "InventoryReplicationProcessManager",
    "InventorySnapshot",
    "InventoryStepHandler",
    "InvocationContextEvidence",
    "InvocationLifecycleEvidence",
    "InvocationStatus",
    "ItemKind",
    "LineageEdge",
    "LineageEvidence",
    "LocalCaptureResult",
    "LocalTranscriptCapture",
    "LocalTranscriptRead",
    "MarkAgentLaunchedCommand",
    "MarkAgentLaunchedHandler",
    "Membership",
    "NativeRelationshipFact",
    "NativeSessionEvidencePort",
    "NativeTranscriptFacts",
    "NodeEvidence",
    "ObservationType",
    "ObserveInventoryClockCommand",
    "OperationRecord",
    "OperationRecordedEvent",
    "OperationType",
    "PendingEvidence",
    "PricedUsage",
    "QualifiedSessionIdentity",
    "ReadLocalTranscriptHandler",
    "RecordOperationCommand",
    "RecordOperationHandler",
    "RecordSessionInvocationCommand",
    "RefreshSessionInventoryHandler",
    "ResolvedInventory",
    "RolloutDocument",
    "RolloutRecord",
    "RunIdentity",
    "SchedulePendingInventoryHandler",
    "SessionCaptureCatalogPort",
    "SessionCaptureSpoolPort",
    "SessionCompletedEvent",
    "SessionCostQueryService",
    "SessionEvidence",
    "SessionEvidenceReadPort",
    "SessionEvidenceWritePort",
    "SessionInventoryJobPort",
    "SessionInventoryReadPort",
    "SessionInventoryWritePort",
    "SessionInvocationState",
    "SessionStartedEvent",
    "SessionStatus",
    "SessionStorePort",
    "SessionSummaryData",
    "SessionTranscriptArchivePort",
    "StartSessionCommand",
    "StartSessionHandler",
    "StoredEvidenceBatch",
    "StoredSession",
    "StoredTranscript",
    "TokenMetrics",
    "TokenUsageData",
    "TranscriptBodyState",
    "TranscriptDeletedError",
    "TranscriptIntegrityError",
    "import_phase_delegates",
    "model_from_rollout",
    "pick_primary_model",
    "price_canonical_row",
    "record_error",
    "record_message_request",
    "record_message_response",
    "record_thinking",
    "record_tool_blocked",
    "record_tool_completed",
    "record_tool_started",
    "recorded_model_from_row",
    "recorded_model_group_by",
    "recorded_model_select",
]

from ._shared.session_invocation import InvocationStatus, SessionInvocationState
from .domain.aggregate_inventory_clock.InventoryClockAggregate import InventoryClockAggregate
from .domain.commands.ObserveInventoryClockCommand import ObserveInventoryClockCommand
from .domain.commands.RecordSessionInvocationCommand import RecordSessionInvocationCommand
from .domain.read_models.session_evidence import (
    AcquisitionStatusEvidence,
    CaptureEvidence,
    IdentityBindingEvidence,
    InvocationContextEvidence,
    InvocationLifecycleEvidence,
    LineageEvidence,
    NodeEvidence,
    SessionEvidence,
)
from .domain.read_models.session_inventory import (
    BodyAvailability,
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
)
from .ports.NativeSessionEvidencePort import (
    NativeRelationshipFact,
    NativeSessionEvidencePort,
    NativeTranscriptFacts,
)
from .ports.QualifiedSessionStorePort import QualifiedSessionIdentity
from .ports.SessionCaptureCatalogPort import CataloguedCapture, SessionCaptureCatalogPort
from .ports.SessionCaptureSpoolPort import (
    CaptureSpool,
    CaptureSpoolLease,
    CaptureSpoolLeaseLost,
    SessionCaptureSpoolPort,
)
from .slices.capture_local_transcript.CaptureLocalTranscriptHandler import (
    CaptureLocalTranscriptHandler,
    LocalCaptureResult,
    LocalTranscriptCapture,
)
from .slices.read_local_transcript.ReadLocalTranscriptHandler import (
    LocalTranscriptRead,
    ReadLocalTranscriptHandler,
)
from .slices.reconcile_session_inventory.HostSessionEvidenceProjector import (
    HostSessionEvidenceProjector,
)
from .slices.replicate_session_inventory.projection import InventoryReplicationProcessManager
