"""#1547: production's notice manager settles owed cancelled work, with no run to do it.

The quiet-system recovery is only as real as its wiring: a manager built
without a settler posts from events that the owed work never becomes. So this
builds the registry exactly as production does and drives the manager's live
pass against a store holding owed work.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.subscriptions import create_coordinator_service
from syn_domain.contexts.orchestration import QuarantineNoticeProcessManager
from syn_domain.contexts.orchestration.slices.execute_workflow import cancelled_work_record
from syn_domain.contexts.orchestration.slices.execute_workflow.cancelled_work_record import (
    OWED_CANCELLED_WORK,
)

pytestmark = pytest.mark.unit


async def test_the_registered_notice_manager_settles_owed_work_on_its_live_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryProjectionStore()
    service = create_coordinator_service(
        event_store=cast("Any", object()), projection_store=cast("Any", store)
    )
    (manager,) = [p for p in service._projections if isinstance(p, QuarantineNoticeProcessManager)]

    settled: list[int] = []
    real_settle = cancelled_work_record.CancelledWorkLedger.settle

    async def counting(self: cancelled_work_record.CancelledWorkLedger) -> int:
        settled.append(len(await store.get_all(OWED_CANCELLED_WORK)))
        return await real_settle(self)

    monkeypatch.setattr(cancelled_work_record.CancelledWorkLedger, "settle", counting)
    await store.save(
        OWED_CANCELLED_WORK,
        "exec-q1:implement",
        {"execution_id": "exec-q1", "phase_id": "implement", "quarantined": []},
    )

    await manager.process_pending()

    # Settled from the store production gave the coordinator, the row in view.
    assert settled == [1]
