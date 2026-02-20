"""Unit tests for WorkflowPhaseMetricsProjection.

Covers: stub creation, metric accumulation, missed-PhaseStarted handling,
multi-phase isolation, status transitions, and empty/invalid event guards.
"""

from decimal import Decimal
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
        assert phases["p-1"]["phase_name"] == "Build"
        assert phases["p-1"]["status"] == "running"
        assert phases["p-1"]["input_tokens"] == 0
        assert phases["p-1"]["cost_usd"] == "0"

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
        assert phases["p-1"]["status"] == "running"  # not duplicated / reset

    async def test_falls_back_to_phase_id_when_name_missing(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
        await projection.on_phase_started({"workflow_id": "wf-1", "phase_id": "p-99"})
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-99"]["phase_name"] == "p-99"

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

    async def test_accumulates_tokens_and_cost(
        self, projection: WorkflowPhaseMetricsProjection
    ) -> None:
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
                "cost_usd": "0.003",
                "duration_seconds": 5.0,
                "success": True,
            }
        )
        phases = await projection.get_phase_metrics("wf-1")
        p = phases["p-1"]
        assert p["input_tokens"] == 100
        assert p["output_tokens"] == 50
        assert p["total_tokens"] == 150
        assert Decimal(p["cost_usd"]) == Decimal("0.003")
        assert p["duration_seconds"] == 5.0
        assert p["status"] == "completed"

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
                    "cost_usd": "0.001",
                    "duration_seconds": 1.0,
                    "success": True,
                }
            )
        phases = await projection.get_phase_metrics("wf-1")
        assert phases["p-1"]["input_tokens"] == 20
        assert Decimal(phases["p-1"]["cost_usd"]) == Decimal("0.002")

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
        assert phases["p-1"]["status"] == "failed"

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
        assert phases["p-1"]["artifact_count"] == 2

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
        assert phases["p-1"]["artifact_count"] == 0


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
        assert phases["p-orphan"]["phase_name"] == "p-orphan"  # falls back to phase_id
        assert phases["p-orphan"]["input_tokens"] == 42
        assert phases["p-orphan"]["status"] == "completed"


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
        assert phases["p-1"]["input_tokens"] == 100
        assert phases["p-2"]["input_tokens"] == 200

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
        assert phases_a["p-1"]["input_tokens"] == 10
        assert phases_b["p-1"]["input_tokens"] == 10


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
