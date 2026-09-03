"""Unit tests for WorkflowPhaseMetricsProjection.

Covers: stub creation, metric accumulation, missed-PhaseStarted handling,
multi-phase isolation, status transitions, overlapping executions of the same
phase, and empty/invalid event guards.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from syn_domain.contexts.orchestration.slices.workflow_phase_metrics.projection import (
    WorkflowPhaseMetricsProjection,
)


class MockProjectionStore:
    """Minimal projection store for testing (no DB required)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def save(self, projection_name: str, key: str, data: dict[str, Any]) -> None:
        self._data.setdefault(projection_name, {})[key] = data

    async def get(self, projection_name: str, key: str) -> dict[str, Any] | None:
        return self._data.get(projection_name, {}).get(key)

    async def delete_all(self, projection_name: str) -> None:
        self._data.pop(projection_name, None)


@pytest.fixture
def store() -> MockProjectionStore:
    return MockProjectionStore()


@pytest.fixture
def projection(store: MockProjectionStore) -> WorkflowPhaseMetricsProjection:
    return WorkflowPhaseMetricsProjection(store)


@pytest.mark.unit
class TestPhaseStarted:
    """PhaseStarted creates a stub entry with status=running."""

    async def test_creates_stub_on_first_event(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build"}
        )
        phases = await projection.get_phase_metrics("wf-1")
        assert "p-1" in phases
        assert phases["p-1"].phase_name == "Build"
        assert phases["p-1"].status == "running"
        assert phases["p-1"].input_tokens == 0
        # Cost is Lane 2 (#695) — projection no longer stores cost_usd
        assert not hasattr(phases["p-1"], "cost_usd")

    async def test_does_not_overwrite_existing_stub(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build"}
        )
        # Simulate a second PhaseStarted (replay / re-delivery)
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build"}
        )
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-1"].status == "running"  # not duplicated / reset

    async def test_falls_back_to_phase_id_when_name_missing(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started({"workflow_id": "wf-1", "phase_id": "p-99"})
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-99"].phase_name == "p-99"

    async def test_ignores_event_missing_ids(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started({"phase_name": "Orphan"})  # no workflow_id or phase_id
        # Nothing should be stored
        phases = await projection.get_phase_metrics("")
        assert phases == {}


@pytest.mark.unit
class TestPhaseCompleted:
    """PhaseCompleted accumulates metrics and sets final status."""

    async def test_accumulates_tokens(self, projection: WorkflowPhaseMetricsProjection) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Test"}
        )
        await projection.on_phase_completed(
            {
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "duration_seconds": 5.0,
                "success": True,
            }
        )
        phases = await projection.get_phase_metrics("wf-1")
        p = phases["p-1"]
        assert p.input_tokens == 100
        assert p.output_tokens == 50
        assert p.total_tokens == 150
        # Cost is Lane 2 (#695) — not stored here
        assert p.duration_seconds() == 5.0
        assert p.status == "completed"

    async def test_accumulates_across_multiple_completions(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        """Two PhaseCompleted events for the same phase accumulate (e.g. retries)."""
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Retry"}
        )
        for _ in range(2):
            await projection.on_phase_completed(
                {
                    "workflow_id": "wf-1",
                    "phase_id": "p-1",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "duration_seconds": 1.0,
                    "success": True,
                }
            )
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-1"].input_tokens == 20

    async def test_sets_failed_status_on_failure(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Flaky"}
        )
        await projection.on_phase_completed(
            {"workflow_id": "wf-1", "phase_id": "p-1", "success": False}
        )
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-1"].status == "failed"

    async def test_increments_artifact_count(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build"}
        )
        await projection.on_phase_completed(
            {"workflow_id": "wf-1", "phase_id": "p-1", "artifact_id": "art-001", "success": True}
        )
        await projection.on_phase_completed(
            {"workflow_id": "wf-1", "phase_id": "p-1", "artifact_id": "art-002", "success": True}
        )
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-1"].artifact_count == 2

    async def test_no_artifact_increment_when_no_artifact_id(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build"}
        )
        await projection.on_phase_completed(
            {"workflow_id": "wf-1", "phase_id": "p-1", "success": True}
        )
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-1"].artifact_count == 0


@pytest.mark.unit
class TestMissedPhaseStarted:
    """PhaseCompleted without a preceding PhaseStarted creates a stub gracefully."""

    async def test_creates_stub_from_completed(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_completed(
            {
                "workflow_id": "wf-2",
                "phase_id": "p-orphan",
                "input_tokens": 42,
                "output_tokens": 21,
                "total_tokens": 63,
                "cost_usd": "0.005",
                "duration_seconds": 2.5,
                "success": True,
            }
        )
        phases = await projection.get_phase_metrics("wf-2")
        assert "p-orphan" in phases
        assert phases["p-orphan"].phase_name == "p-orphan"  # falls back to phase_id
        assert phases["p-orphan"].input_tokens == 42
        assert phases["p-orphan"].status == "completed"


@pytest.mark.unit
class TestMultiPhaseIsolation:
    """Multiple phases within a workflow are keyed independently."""

    async def test_two_phases_do_not_share_metrics(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        for phase_id, name, tokens in [("p-1", "Build", 100), ("p-2", "Deploy", 200)]:
            await projection.on_phase_started(
                {"workflow_id": "wf-3", "phase_id": phase_id, "phase_name": name}
            )
            await projection.on_phase_completed(
                {
                    "workflow_id": "wf-3",
                    "phase_id": phase_id,
                    "input_tokens": tokens,
                    "output_tokens": 0,
                    "total_tokens": tokens,
                    "success": True,
                }
            )
        phases = await projection.get_phase_metrics("wf-3")
        assert phases["p-1"].input_tokens == 100
        assert phases["p-2"].input_tokens == 200

    async def test_separate_workflows_do_not_share_phases(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        for wf_id in ("wf-A", "wf-B"):
            await projection.on_phase_started(
                {"workflow_id": wf_id, "phase_id": "p-1", "phase_name": "Build"}
            )
            await projection.on_phase_completed(
                {"workflow_id": wf_id, "phase_id": "p-1", "input_tokens": 10, "success": True}
            )
        phases_a = await projection.get_phase_metrics("wf-A")
        phases_b = await projection.get_phase_metrics("wf-B")
        assert phases_a is not phases_b
        assert phases_a["p-1"].input_tokens == 10
        assert phases_b["p-1"].input_tokens == 10


# Four to six executions of the same workflow run concurrently in production,
# so two of them are routinely inside the same phase at the same time. A fixed
# clock makes every number below exact rather than a lower bound.
STARTED = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
SECOND_STARTED = STARTED + timedelta(seconds=100)
FIRST_ENDED = STARTED + timedelta(seconds=250)
READ_AT = STARTED + timedelta(seconds=400)

FIRST_RAN_FOR = 250.0
"""What the first execution's run measured: FIRST_ENDED - STARTED."""

SECOND_STILL_RUNNING_FOR = 300.0
"""What the second execution's run has run at READ_AT: READ_AT - SECOND_STARTED."""


def _started(execution_id: str, at: datetime) -> dict[str, str]:
    return {
        "workflow_id": "wf-1",
        "execution_id": execution_id,
        "phase_id": "p-1",
        "phase_name": "Build",
        "started_at": at.isoformat(),
    }


@pytest.mark.unit
class TestOverlappingExecutions:
    """One execution finishing a phase must not close another's run of it.

    The entry is shared by the whole workflow, so before runs were keyed by
    execution the first completion wrote "completed" over it: GET /metrics
    reported the phase terminal while other executions were still in it, and
    their elapsed time dropped out of the total.
    """

    async def test_both_runs_survive_the_store_round_trip(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        """Every handler reloads the entry, so the runs have to be stored.

        Two starts, and the second must not overwrite the first on the way
        through the projection store.
        """
        await projection.on_phase_started(_started("exec-1", STARTED))
        await projection.on_phase_started(_started("exec-2", SECOND_STARTED))

        phases = await projection.get_phase_metrics("wf-1")
        assert set(phases["p-1"].active_runs) == {"exec-1", "exec-2"}

    async def test_completing_one_execution_leaves_the_other_running(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        """The blocker verbatim: the phase is still running, and still timed.

        Its total is the finished run's measured time plus the live run's
        elapsed time. Reporting either alone - 250 or 300 - is the defect;
        550 can only come from both.
        """
        await projection.on_phase_started(_started("exec-1", STARTED))
        await projection.on_phase_started(_started("exec-2", SECOND_STARTED))

        await projection.on_phase_completed(
            {
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "duration_seconds": FIRST_RAN_FOR,
                "completed_at": FIRST_ENDED.isoformat(),
                "success": True,
            }
        )

        phase = (await projection.get_phase_metrics("wf-1"))["p-1"]
        assert phase.status == "running"
        assert phase.duration_seconds(now=READ_AT) == FIRST_RAN_FOR + SECOND_STILL_RUNNING_FOR

    async def test_a_failed_execution_leaves_the_other_running(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        """Same collision by the failure route, which is a separate writer."""
        await projection.on_phase_started(_started("exec-1", STARTED))
        await projection.on_phase_started(_started("exec-2", SECOND_STARTED))

        await projection.on_workflow_failed(
            {
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "failed_phase_id": "p-1",
                "failed_phase_duration_seconds": FIRST_RAN_FOR,
                "failed_at": FIRST_ENDED.isoformat(),
            }
        )

        phase = (await projection.get_phase_metrics("wf-1"))["p-1"]
        assert phase.status == "running"
        assert phase.duration_seconds(now=READ_AT) == FIRST_RAN_FOR + SECOND_STILL_RUNNING_FOR

    async def test_the_phase_settles_when_its_last_run_finishes(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        """Keeping every run open would be the opposite defect: never terminal.

        Once no execution is in the phase it reports how the last one ended,
        and its total stops moving.
        """
        await projection.on_phase_started(_started("exec-1", STARTED))
        await projection.on_phase_started(_started("exec-2", SECOND_STARTED))

        for execution_id, ran_for in (("exec-1", FIRST_RAN_FOR), ("exec-2", 400.0)):
            await projection.on_phase_completed(
                {
                    "workflow_id": "wf-1",
                    "execution_id": execution_id,
                    "phase_id": "p-1",
                    "duration_seconds": ran_for,
                    "success": True,
                }
            )

        phase = (await projection.get_phase_metrics("wf-1"))["p-1"]
        assert phase.status == "completed"
        assert phase.active_runs == {}
        assert phase.duration_seconds(now=READ_AT) == FIRST_RAN_FOR + 400.0
        assert phase.duration_seconds(now=READ_AT + timedelta(hours=1)) == FIRST_RAN_FOR + 400.0


@pytest.mark.unit
class TestAbandonedRuns:
    """An execution that stopped is not running any phase, whichever way it stopped.

    Runs no longer overwrite each other, so nothing papers over one that was
    never closed: it would report the phase running and keep billing it
    wall-clock time forever (#1036, now per execution).
    """

    @pytest.mark.parametrize(
        ("handler", "event_extra", "expected_status"),
        [
            ("on_execution_cancelled", {"cancelled_at": FIRST_ENDED.isoformat()}, "cancelled"),
            ("on_workflow_interrupted", {"interrupted_at": FIRST_ENDED.isoformat()}, "interrupted"),
        ],
    )
    async def test_stopping_an_execution_stops_its_clock(
        self,
        projection: WorkflowPhaseMetricsProjection,
        handler: str,
        event_extra: dict[str, str],
        expected_status: str,
    ) -> None:
        """Neither event records a duration, so the run is timed to its end.

        Against the wall clock instead, the phase's total would keep growing
        after the run stopped - which is what it did, because neither event
        reached this projection at all.
        """
        await projection.on_phase_started(_started("exec-1", STARTED))

        await getattr(projection, handler)(
            {
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "p-1",
                **event_extra,
            }
        )

        phase = (await projection.get_phase_metrics("wf-1"))["p-1"]
        assert phase.status == expected_status
        assert phase.duration_seconds(now=READ_AT) == FIRST_RAN_FOR
        assert phase.duration_seconds(now=READ_AT + timedelta(hours=1)) == FIRST_RAN_FOR

    async def test_stopping_one_execution_leaves_the_others_alone(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        """A cancel is scoped to one execution, like every other way out."""
        await projection.on_phase_started(_started("exec-1", STARTED))
        await projection.on_phase_started(_started("exec-2", SECOND_STARTED))

        await projection.on_execution_cancelled(
            {
                "workflow_id": "wf-1",
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "cancelled_at": FIRST_ENDED.isoformat(),
            }
        )

        phase = (await projection.get_phase_metrics("wf-1"))["p-1"]
        assert phase.status == "running"
        assert set(phase.active_runs) == {"exec-2"}
        assert phase.duration_seconds(now=READ_AT) == FIRST_RAN_FOR + SECOND_STILL_RUNNING_FOR


@pytest.mark.unit
class TestQueryAndClear:
    """get_phase_metrics and clear_all_data behave correctly."""

    async def test_returns_empty_dict_for_unknown_workflow(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        phases = await projection.get_phase_metrics("nonexistent")
        assert phases == {}

    async def test_clear_all_data_removes_stored_data(
        self, projection: WorkflowPhaseMetricsProjection, store: MockProjectionStore
    ) -> None:
        await projection.on_phase_started(
            {"workflow_id": "wf-1", "phase_id": "p-1", "phase_name": "Build"}
        )
        await projection.clear_all_data()
        phases = await projection.get_phase_metrics("wf-1")
        assert phases == {}
