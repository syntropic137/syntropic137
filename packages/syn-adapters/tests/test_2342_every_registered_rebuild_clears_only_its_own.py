"""#2342: every registered projection's version rebuild clears its own namespaces, and only those.

Runs over the real registry: ``create_coordinator_service()`` with both
optional inventory managers, plus the realtime adapter, all on one shared
``InMemoryProjectionStore``. Every namespace any of them stores holds rows
(``dashboard_metrics`` is one singleton row, every other namespace two). Then one registration at a time is rebuilt through
``SubscriptionCoordinator._resume_position`` (a VERSION mismatch). Its declared
namespaces must be empty afterwards, and every other namespace must be exactly
what it was, row for row.

Every row is produced by a registered handler: one ordered event history goes
through ``handle_event`` of every registration that subscribes to each event,
the way the coordinator delivers it. Events are the real domain event classes
(``_EVENT_CLASSES``), with every required field filled from its annotation (``_build``) and the few fields a handler keys on set
explicitly. The observation events have no class and travel as
``GenericDomainEvent``, as in ``test_2342_observation_adapters_clear_on_rebuild.py``.
Only ``_UNOWNED`` is written directly, because no handler owns it.
"""

from __future__ import annotations

import os

# Must be set before any syn_* imports
os.environ.setdefault("APP_ENVIRONMENT", "test")

import datetime as dt
import enum
import json
import types
import typing
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock, Mock

import pytest
from event_sourcing import (
    CheckpointedProjection,
    DomainEvent,
    EventEnvelope,
    EventMetadata,
    GenericDomainEvent,
    MemoryCheckpointStore,
    ProjectionCheckpoint,
    ProjectionResult,
    SubscriptionCoordinator,
)
from pydantic import BaseModel

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.agent_sessions.domain.events.SessionStartedEvent import SessionStartedEvent
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import ArtifactCreatedEvent
from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import TriggerBlockedEvent
from syn_domain.contexts.github.domain.events.TriggerFiredEvent import TriggerFiredEvent
from syn_domain.contexts.github.domain.events.TriggerRegisteredEvent import TriggerRegisteredEvent
from syn_domain.contexts.orchestration.domain.aggregate_eval.value_objects import Verdict
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    QuarantinedRef,
)
from syn_domain.contexts.orchestration.domain.events.ClaudePluginRegisteredEvent import (
    ClaudePluginRegisteredEvent,
)
from syn_domain.contexts.orchestration.domain.events.EvalCreatedEvent import EvalCreatedEvent
from syn_domain.contexts.orchestration.domain.events.EvalRunScoredEvent import EvalRunScoredEvent
from syn_domain.contexts.orchestration.domain.events.ExecutionRequestedEvent import (
    ExecutionRequestedEvent,
)
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.domain.events.GlobalClaudePluginAddedEvent import (
    GlobalClaudePluginAddedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import PhaseCompletedEvent
from syn_domain.contexts.orchestration.domain.events.PhaseStartedEvent import PhaseStartedEvent
from syn_domain.contexts.orchestration.domain.events.SkillRegisteredEvent import (
    SkillRegisteredEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import WorkflowFailedEvent
from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateCreatedEvent import (
    WorkflowTemplateCreatedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.organization.domain.events.OrganizationCreatedEvent import (
    OrganizationCreatedEvent,
)
from syn_domain.contexts.organization.domain.events.RepoAssignedToSystemEvent import (
    RepoAssignedToSystemEvent,
)
from syn_domain.contexts.organization.domain.events.RepoRegisteredEvent import RepoRegisteredEvent
from syn_domain.contexts.organization.domain.events.SystemCreatedEvent import SystemCreatedEvent
from syn_shared.events import TOKEN_USAGE, TOOL_EXECUTION_STARTED

pytestmark = pytest.mark.unit

#: Every registration by ``get_name()``, with each namespace it stores. A
#: rebuild must empty exactly these. A new registration fails
#: ``test_every_registration_is_declared`` until it is added here.
_OWNED: dict[str, frozenset[str]] = {
    "workflow_summaries": frozenset({"workflow_summaries"}),
    "workflow_details": frozenset({"workflow_details", "workflow_definition_changes"}),
    "workflow_executions": frozenset({"workflow_executions"}),
    "workflow_execution_details": frozenset({"workflow_execution_details"}),
    "evals": frozenset({"evals", "eval_run_scores"}),
    "dashboard_metrics": frozenset({"dashboard_metrics"}),
    "workflow_phase_metrics": frozenset({"workflow_phase_metrics"}),
    "failure_streak": frozenset({"failure_streak"}),
    "execution_todo": frozenset({"execution_todo"}),
    "workflow_dispatch": frozenset({"workflow_dispatch"}),
    "resume_start": frozenset({"resume_start"}),
    "execution_request_start": frozenset({"execution_request_start"}),
    "quarantine_notice": frozenset({"quarantine_notice"}),
    "trigger_query": frozenset({"trigger_deliveries", "trigger_fire_records", "trigger_index"}),
    "session_summaries": frozenset({"session_summaries"}),
    "artifact_summaries": frozenset({"artifact_summaries"}),
    "organization_list": frozenset({"organizations"}),
    "system_list": frozenset({"systems"}),
    "repo_list": frozenset({"repos"}),
    "repo_health": frozenset({"repo_health"}),
    "repo_cost": frozenset({"repo_cost"}),
    "repo_correlation": frozenset({"repo_correlation"}),
    "trigger_history": frozenset({"trigger_history"}),
    "tool_timeline": frozenset({"tool_timelines"}),
    "execution_cost": frozenset({"execution_cost"}),
    "session_cost": frozenset({"session_cost"}),
    "claude_plugin_lock": frozenset({"claude_plugin_lock"}),
    "global_claude_plugins": frozenset({"global_claude_plugins"}),
    "skill_lock": frozenset({"skill_lock"}),
    "workspace_ownership": frozenset({"workspace_ownership"}),
    # Nothing to clear: the reasons are in ci/fitness/event_sourcing/
    # test_rebuild_clears_read_models.py (_NOTHING_TO_CLEAR). A rebuild of these
    # must leave every namespace exactly as it was.
    "realtime_sse": frozenset(),
    "session_inventory_replication": frozenset(),
    "session_inventory_jobs": frozenset(),
}

#: Registered, but its rebuild recounts from ``agent_events`` in SQL through a
#: database pool, not through the projection store; it refuses to run without
#: one. Its clear is covered against a real database in
#: ``packages/syn-domain/tests/integration/test_tool_call_counts_rebuild.py``.
_SQL_BACKED = frozenset({"tool_call_counts"})

#: Owned by no registration, so every rebuild must leave it untouched.
_UNOWNED = "unowned_by_any_projection"

_NAMESPACES = sorted({ns for owned in _OWNED.values() for ns in owned} | {_UNOWNED})


def _registered(store: InMemoryProjectionStore) -> dict[str, CheckpointedProjection]:
    from syn_adapters.projections.realtime import RealTimeProjection
    from syn_adapters.subscriptions.coordinator_service import create_coordinator_service
    from syn_adapters.subscriptions.read_model_dispatch import as_checkpointed
    from syn_domain.contexts.agent_sessions import InventoryReconciliationProcessManager
    from syn_domain.contexts.agent_sessions.slices.replicate_session_inventory.projection import (
        InventoryReplicationProcessManager,
    )

    dummy = cast("Any", MagicMock())
    service = create_coordinator_service(
        event_store=dummy,
        projection_store=store,
        checkpoint_store=dummy,
        inventory_process_manager=InventoryReconciliationProcessManager(
            dummy, dummy, lease_seconds=60, retry_seconds=10, max_jobs_per_tick=1
        ),
        inventory_replication_manager=InventoryReplicationProcessManager(dummy),
    )
    realtime = as_checkpointed(RealTimeProjection())
    assert realtime is not None
    return {p.get_name(): p for p in [*service._projections, realtime]}


def _value(field: str, annotation: object, n: int) -> object:
    """A valid value for a required field, the same for every event with the same ``n``.

    Ids are ``f"{field}-{n}"``, so ``execution_id`` correlates across events
    the way it does in a real stream.
    """
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return _value(field, next(a for a in args if a is not type(None)), n)
    if origin is typing.Literal:
        return args[0]
    if origin is list:
        return []
    if origin is dict:
        return {}
    if isinstance(annotation, type):
        if issubclass(annotation, bool):
            return False
        if issubclass(annotation, enum.Enum):
            return next(iter(annotation))
        if issubclass(annotation, int | float):
            return annotation(n)
        if issubclass(annotation, dt.datetime):
            return dt.datetime(2026, 11, 21, 0, n, tzinfo=UTC)
        if issubclass(annotation, BaseModel):
            return _build(annotation, n)
    return f"{field}-{n}"


def _build[M: BaseModel](model: type[M], n: int, **overrides: object) -> M:
    required = {
        name: _value(name, info.annotation, n)
        for name, info in model.model_fields.items()
        if info.is_required()
    }
    return model.model_validate(required | overrides)


def _repository(n: int) -> str:
    return f"owner/repo-{n}"


def _domain_event(event_type: str, n: int) -> DomainEvent:
    """One event of the history, as its registered class, for entity ``n``."""
    if event_type in (TOOL_EXECUTION_STARTED, TOKEN_USAGE):
        return GenericDomainEvent(
            session_id=f"session_id-{n}",
            execution_id=f"execution_id-{n}",
            tool_use_id=f"tool_use_id-{n}",
            tool_name="Bash",
            timestamp="2026-11-21T00:00:00+00:00",
            observation_type=event_type,
            event_type=event_type,
            data={"input_tokens": 100 * n, "output_tokens": 10, "model": "claude-opus-5-5"},
        )
    event_class = _EVENT_CLASSES[event_type]
    # The fields a handler keys on that an annotation cannot supply.
    match event_type:
        case "EvalRunScored":
            return _build(event_class, n, verdict=Verdict.PASS.value)
        case "github.TriggerFired":
            return _build(
                event_class, n, repository=_repository(n), webhook_delivery_id=f"delivery-{n}"
            )
        case "WorkflowExecutionStarted":
            return _build(
                event_class, n, inputs={"repository": f"https://github.com/{_repository(n)}"}
            )
        case "WorkflowFailed":
            return _build(
                event_class,
                n,
                failed_phase_id=f"phase_id-{n}",
                quarantined_refs=[_build(QuarantinedRef, n, repository=_repository(n))],
            )
        case _:
            return _build(event_class, n)


#: The class each event of ``_HISTORY`` is built as.
_EVENT_CLASSES: dict[str, type[DomainEvent]] = {
    "WorkflowTemplateCreated": WorkflowTemplateCreatedEvent,
    "ArtifactCreated": ArtifactCreatedEvent,
    "EvalCreated": EvalCreatedEvent,
    "EvalRunScored": EvalRunScoredEvent,
    "ClaudePluginRegistered": ClaudePluginRegisteredEvent,
    "GlobalClaudePluginAdded": GlobalClaudePluginAddedEvent,
    "SkillRegistered": SkillRegisteredEvent,
    "ExecutionRequested": ExecutionRequestedEvent,
    "ExecutionResumed": ExecutionResumedEvent,
    "organization.OrganizationCreated": OrganizationCreatedEvent,
    "organization.SystemCreated": SystemCreatedEvent,
    "organization.RepoRegistered": RepoRegisteredEvent,
    "organization.RepoAssignedToSystem": RepoAssignedToSystemEvent,
    "github.TriggerRegistered": TriggerRegisteredEvent,
    "github.TriggerFired": TriggerFiredEvent,
    "github.TriggerBlocked": TriggerBlockedEvent,
    "SessionStarted": SessionStartedEvent,
    "WorkflowExecutionStarted": WorkflowExecutionStartedEvent,
    "PhaseStarted": PhaseStartedEvent,
    "PhaseCompleted": PhaseCompletedEvent,
    "WorkflowFailed": WorkflowFailedEvent,
    "WorkspaceProvisionedForPhase": WorkspaceProvisionedForPhaseEvent,
}

#: Creation before change, nothing deleted: after this history every namespace
#: any registration owns holds at least one handler-produced row.
_HISTORY = (*_EVENT_CLASSES, TOOL_EXECUTION_STARTED, TOKEN_USAGE)


async def _fed_store() -> tuple[InMemoryProjectionStore, dict[str, CheckpointedProjection]]:
    """The registry after ``_HISTORY`` for two entities went through every handler."""
    store = InMemoryProjectionStore()
    registered = _registered(store)
    checkpoints = MemoryCheckpointStore()
    nonce = 0
    for event_type in _HISTORY:
        for n in (1, 2):
            nonce += 1
            envelope = EventEnvelope(
                event=_domain_event(event_type, n),
                metadata=EventMetadata(
                    event_type=event_type,
                    aggregate_id=f"aggregate-{n}",
                    aggregate_type="Fixture",
                    aggregate_nonce=nonce,
                    global_nonce=nonce,
                ),
            )
            for name, adapter in registered.items():
                if name in _SQL_BACKED or not adapter.should_handle_event_type(event_type):
                    continue
                result = await adapter.handle_event(envelope, checkpoints)
                assert result is not ProjectionResult.FAILURE, f"{name} failed {event_type}"
    for n in (1, 2):
        await store.save(_UNOWNED, f"sentinel-{n}", {"n": n})
    return store, registered


async def _snapshot(store: InMemoryProjectionStore) -> dict[str, str]:
    """Each namespace's rows as canonical JSON, so equality means row-for-row identical."""
    return {
        ns: json.dumps(await store.get_all(ns), sort_keys=True, default=str) for ns in _NAMESPACES
    }


def test_every_registration_is_declared() -> None:
    registered = set(_registered(InMemoryProjectionStore()))
    declared = set(_OWNED) | _SQL_BACKED
    assert registered == declared, (
        f"Registered but undeclared: {sorted(registered - declared)}; "
        f"declared but not registered: {sorted(declared - registered)}. "
        "Declare each registration's namespaces in _OWNED."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rebuilt", sorted(_OWNED))
async def test_rebuild_clears_its_own_namespaces_and_leaves_every_other_row_exactly(
    rebuilt: str,
) -> None:
    store, registered = await _fed_store()
    adapter = registered[rebuilt]
    before = await _snapshot(store)
    empty = sorted(ns for ns in _NAMESPACES if before[ns] == "[]")
    assert not empty, f"no handler wrote to {empty}; extend _HISTORY"

    checkpoints = MemoryCheckpointStore()
    await checkpoints.save_checkpoint(
        ProjectionCheckpoint(
            projection_name=rebuilt,
            global_position=10,
            updated_at=datetime.now(UTC),
            version=adapter.get_version() - 1,
        )
    )
    coordinator = SubscriptionCoordinator(
        event_store=Mock(), checkpoint_store=checkpoints, projections=[adapter]
    )
    assert await coordinator._resume_position(rebuilt, adapter) == 0

    after = await _snapshot(store)
    owned = _OWNED[rebuilt]
    left_behind = sorted(ns for ns in owned if after[ns] != "[]")
    assert not left_behind, f"rebuilding {rebuilt} left rows in {left_behind}"
    changed = sorted(ns for ns in _NAMESPACES if ns not in owned and after[ns] != before[ns])
    assert not changed, f"rebuilding {rebuilt} changed rows it does not own in {changed}"
