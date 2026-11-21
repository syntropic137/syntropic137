"""#2342: every registered projection's version rebuild clears its own namespaces, and only those.

Runs over the real registry: ``create_coordinator_service()`` with both
optional inventory managers, plus the realtime adapter, all on one shared
``InMemoryProjectionStore``. Every namespace any of them stores gets two rows.
Then one registration at a time is rebuilt through
``SubscriptionCoordinator._resume_position`` (a VERSION mismatch). Its declared
namespaces must be empty afterwards, and every other namespace must be exactly
what it was, row for row.

Rows are seeded rather than produced by each handler: thirty handlers need
thirty event shapes, and the clear is unconditional on the row contents. The
handler-to-clear path is covered for the observation adapters in
``test_2342_observation_adapters_clear_on_rebuild.py``. Seeded rows carry every
id field a per-key clear reads (``organization_id``, ``execution_id`` ...), so
those clears find what they must delete.
"""

from __future__ import annotations

import os

# Must be set before any syn_* imports
os.environ.setdefault("APP_ENVIRONMENT", "test")

import json
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock, Mock

import pytest
from event_sourcing import (
    CheckpointedProjection,
    MemoryCheckpointStore,
    ProjectionCheckpoint,
    SubscriptionCoordinator,
)

from syn_adapters.projection_stores import InMemoryProjectionStore

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


async def _seeded_store() -> InMemoryProjectionStore:
    """Two rows in every namespace, each carrying every id a per-key clear reads."""
    store = InMemoryProjectionStore()
    for namespace in _NAMESPACES:
        for n in (1, 2):
            key = f"{namespace}-{n}"
            await store.save(
                namespace,
                key,
                {
                    "_projection_key": key,
                    "organization_id": key,
                    "system_id": key,
                    "repo_id": key,
                    "execution_id": key,
                    "payload": {"n": n, "tags": [namespace, n]},
                },
            )
    return store


async def _snapshot(store: InMemoryProjectionStore) -> dict[str, str]:
    """Each namespace's rows as canonical JSON, so equality means row-for-row identical."""
    return {ns: json.dumps(await store.get_all(ns), sort_keys=True) for ns in _NAMESPACES}


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
    store = await _seeded_store()
    adapter = _registered(store)[rebuilt]
    before = await _snapshot(store)
    for namespace in _NAMESPACES:
        assert len(await store.get_all(namespace)) == 2, f"{namespace} was not seeded"

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
