"""Fitness function: every registered read model clears its data on a version rebuild.

On a VERSION mismatch the ESP coordinator calls ``clear_all_data()`` and then
replays from position 0. ESP's default ``clear_all_data`` does nothing, so a
read model that inherits it replays onto its old rows, and the bump that was
meant to rebuild it silently does not (#2342; the cost adapters in #2333).

The check runs over what ``create_coordinator_service()`` actually registers,
with both optional inventory managers and the realtime adapter included. An
adapter that delegates to a wrapped ``_projection`` is checked through to the
clear that will run.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from event_sourcing import CheckpointedProjection

#: Registered classes whose no-op clear is correct, by ``get_name()``. Each must
#: say why a rebuild has nothing to discard. Never add a read model that stores rows.
_NOTHING_TO_CLEAR: dict[str, str] = {
    "realtime_sse": "RealTimeProjectionAdapter broadcasts over SSE and stores nothing",
    "session_inventory_replication": (
        "InventoryReplicationProcessManager only advances its checkpoint; it writes no rows"
    ),
    "session_inventory_jobs": (
        "InventoryReconciliationProcessManager is a process manager: its to-do and lease "
        "writes are keyed by source event or run and converge on replay by design (#1398). "
        "Clearing live to-do state on a bump is a separate decision from clearing a read model"
    ),
}


def _registered() -> list[CheckpointedProjection]:
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
        projection_store=dummy,
        checkpoint_store=dummy,
        inventory_process_manager=InventoryReconciliationProcessManager(
            dummy, dummy, lease_seconds=60, retry_seconds=10, max_jobs_per_tick=1
        ),
        inventory_replication_manager=InventoryReplicationProcessManager(dummy),
    )
    realtime = as_checkpointed(RealTimeProjection())
    assert realtime is not None
    return [*service._projections, realtime]


def _runs_a_real_clear(projection: CheckpointedProjection) -> bool:
    owner = next(c for c in type(projection).__mro__ if "clear_all_data" in vars(c))
    if owner is CheckpointedProjection:
        return False
    wrapped = getattr(projection, "_projection", None)
    if wrapped is None:
        return True
    return callable(getattr(wrapped, "clear_all_data", None))


@pytest.mark.architecture
def test_every_registered_read_model_clears_on_a_version_rebuild() -> None:
    registered = _registered()
    names = {p.get_name() for p in registered}
    assert set(_NOTHING_TO_CLEAR) <= names, (
        f"Allowlisted but no longer registered: {sorted(set(_NOTHING_TO_CLEAR) - names)}. "
        "Remove them from _NOTHING_TO_CLEAR."
    )

    no_op = sorted(
        f"{type(p).__name__} ({p.get_name()})"
        for p in registered
        if p.get_name() not in _NOTHING_TO_CLEAR and not _runs_a_real_clear(p)
    )

    assert not no_op, (
        f"These registered read models keep ESP's no-op clear_all_data: {no_op}. "
        "A VERSION bump would replay onto their old rows. Implement clear_all_data "
        "to delete their own namespace(s) only."
    )
