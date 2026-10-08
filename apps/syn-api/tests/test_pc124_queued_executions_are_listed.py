"""A queued execution is a row in the execution list, not a gap in it (PC-124).

Before this, `GET /executions` read only the execution read model, and a start
waiting for a slot has none: `syn execution list --status queued` came back
empty and `status_counts` had no `queued` at all, while three starts waited.

Driven through the real admission path of #1557's world - the route, the
budget, the durable request record and the cancel route - and read through
the list endpoint the dashboard and `syn execution list` call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from test_1557_one_execution_budget import (  # pyright: ignore[reportMissingImports]
    LIMIT,
    _cancel,  # pyright: ignore[reportPrivateUsage]
    _release_everything,  # pyright: ignore[reportPrivateUsage]
    _two_running_one_queued,  # pyright: ignore[reportPrivateUsage]
    _World,  # pyright: ignore[reportPrivateUsage]
)

import syn_api._wiring_admission as admission
from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_api.routes.executions import queries
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

if TYPE_CHECKING:
    from syn_api.routes.executions.models import ExecutionListResponse

pytestmark = pytest.mark.unit


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    built = _World(monkeypatch)
    # The real list read model over the same store: it holds no row for a
    # start with no execution, which is the whole defect.
    built.projections.workflow_execution_list = WorkflowExecutionListProjection(  # type: ignore[attr-defined]
        built.projections.store
    )
    monkeypatch.setattr(queries, "get_projection_mgr", lambda: built.projections)

    async def _connected() -> None:
        return None

    monkeypatch.setattr(queries, "ensure_connected", _connected)
    built.maintenance = InMemoryMaintenanceAdapter()  # type: ignore[attr-defined]
    monkeypatch.setattr(admission, "get_maintenance_port", lambda: built.maintenance)  # type: ignore[attr-defined]
    return built


async def _listed(
    status: str | None = None, q: str | None = None, started_after: datetime | None = None
) -> ExecutionListResponse:
    """`GET /executions`, as `syn execution list` and the dashboard call it."""
    return await queries.list_executions_endpoint(
        status=status,
        statuses=None,
        started_after=started_after,
        started_before=None,
        q=q,
        tag=None,
        eval_id=None,
        in_eval=None,
        page=1,
        page_size=50,
    )


class TestAQueuedStartIsListed:
    async def test_it_is_a_row_with_its_position_and_why_it_waits(self, world: _World) -> None:
        _, queued = await _two_running_one_queued(world)

        listed = await _listed()

        (row,) = [e for e in listed.executions if e.workflow_execution_id == queued]
        assert row.status == "queued"
        assert row.start_queue is not None
        assert row.start_queue.position == 1
        assert row.start_queue.held is True
        assert row.start_queue.reason_display == f"slots full {LIMIT}/{LIMIT}"
        assert listed.status_counts["queued"] == 1
        assert listed.total == 1
        assert listed.budget is not None
        assert listed.budget.display == f"{LIMIT} running / 1 queued / cap {LIMIT}"

        await _release_everything(world)

    async def test_status_queued_selects_it(self, world: _World) -> None:
        _, queued = await _two_running_one_queued(world)

        only = await _listed(status="queued")
        none = await _listed(status="running")

        assert [e.workflow_execution_id for e in only.executions] == [queued]
        assert only.total == 1
        assert none.executions == []
        assert none.total == 0
        # The chips are counted ignoring the status filter, so both agree.
        assert only.status_counts["queued"] == none.status_counts["queued"] == 1

        await _release_everything(world)

    async def test_search_that_misses_it_does_not_list_it(self, world: _World) -> None:
        _, queued = await _two_running_one_queued(world)

        assert (await _listed(q=queued[-6:])).total == 1
        assert (await _listed(q="nothing-like-it")).total == 0

        await _release_everything(world)

    async def test_the_dashboards_default_window_judges_when_it_was_accepted(
        self, world: _World
    ) -> None:
        """The dashboard asks for the last 24h by default; a queued start is in it."""
        _, queued = await _two_running_one_queued(world)
        now = datetime.now(UTC)

        recent = await _listed(started_after=now - timedelta(hours=24))
        later = await _listed(started_after=now + timedelta(hours=1))

        assert queued in {e.workflow_execution_id for e in recent.executions}
        assert recent.status_counts["queued"] == 1
        assert "queued" not in later.status_counts

        await _release_everything(world)

    async def test_once_it_has_run_it_is_no_longer_queued(self, world: _World) -> None:
        await _two_running_one_queued(world)
        await _release_everything(world)
        await world.coordinate()

        listed = await _listed()

        assert [e for e in listed.executions if e.status == "queued"] == []
        assert listed.status_counts.get("queued", 0) == 0


class TestTheListIsDurable:
    async def test_after_a_restart_the_recorded_start_is_still_listed(self, world: _World) -> None:
        """No process holds it now; its durable request record still owes it a start."""
        _, queued = await _two_running_one_queued(world)
        await world.coordinate()
        await world.restart()

        listed = await _listed(status="queued")

        rows = {e.workflow_execution_id: e for e in listed.executions}
        assert queued in rows
        info = rows[queued].start_queue
        assert info is not None
        assert info.held is False
        assert info.position is None
        assert info.reason_display.startswith("awaiting pickup (")


class TestACancelledQueuedStartLeavesTheList:
    async def test_withdrawn_it_is_not_queued(self, world: _World) -> None:
        _, queued = await _two_running_one_queued(world)

        assert (await _cancel(queued)).state == "cancelled"
        await world.coordinate()
        listed = await _listed()

        assert queued not in {e.workflow_execution_id for e in listed.executions}
        assert listed.status_counts.get("queued", 0) == 0

        await _release_everything(world)


class TestAdmissionPaused:
    async def test_the_budget_says_so(self, world: _World) -> None:
        await world.maintenance.set_mode(active=True, reason="deploy", actor="test")  # type: ignore[attr-defined]

        listed = await _listed()

        assert listed.budget is not None
        assert listed.budget.admission_paused is True
        assert listed.budget.display.endswith("(admission paused)")
