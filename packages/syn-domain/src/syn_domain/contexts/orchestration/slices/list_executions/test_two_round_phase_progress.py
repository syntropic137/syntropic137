"""Progress for a run of the installed two-round SDLC workflows (2026-10-07).

The owner capped repair at two rounds, so a new `sdlc-implement-v3` run has
eight phases, not ten, and `sdlc-reverify-pr-v1` seven, not nine. Nothing in
the read path hard-codes a round count: the denominator is whatever the
execution's start event declared. So these cases take the phase definitions
from the workflow YAML exactly as `POST /workflows` installs it, drive both
execution read models with the skips `next_phase` decides, and read progress
back through each projection's query. Old ten-phase runs are covered by
test_phase_progress.py, which keeps its own three-round definition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import (
    next_phase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.domain.read_models.phase_progress import (
    PhaseProgress,
)
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[8] / "workflows" / "sdlc"
_EXECUTION = "exec-two-rounds"
_REVIEWS = {"verify", "reverify", "reverify_2"}


def _installed(directory: str) -> tuple[str, list[PhaseDefinition]]:
    command = build_command_from_definition(
        WorkflowDefinition.from_file(_SDLC / directory / "workflow.yaml")
    )
    phases = sorted(
        (PhaseDefinition(phase_id=p.phase_id, name=p.name, order=p.order) for p in command.phases),
        key=lambda p: p.order,
    )
    return command.aggregate_id, phases


async def _progress(
    directory: str, verdicts: dict[str, ReviewVerdict], *, finish: bool
) -> PhaseProgress:
    """Run the installed workflow until it ends or `verdicts` runs out of reviews."""
    workflow_id, phases = _installed(directory)
    read_models = (
        WorkflowExecutionListProjection(InMemoryProjectionStore()),
        WorkflowExecutionDetailProjection(InMemoryProjectionStore()),
    )
    for rm in read_models:
        await rm.on_workflow_execution_started(
            {
                "execution_id": _EXECUTION,
                "workflow_id": workflow_id,
                "workflow_name": workflow_id,
                "started_at": "2026-10-08T00:00:00+00:00",
                "total_phases": len(phases),
                "phases": [],
            }
        )
    completed = 0
    current: PhaseDefinition | None = phases[0]
    while current is not None:
        if current.phase_id in _REVIEWS and current.phase_id not in verdicts:
            break
        for rm in read_models:
            await rm.on_phase_completed(
                {"execution_id": _EXECUTION, "phase_id": current.phase_id, "duration_seconds": 1.0}
            )
        completed += 1
        decided = next_phase(phases, current.order, verdicts.get(current.phase_id))
        if decided is None:
            break
        event = decided.event(
            workflow_id=workflow_id, execution_id=_EXECUTION, completed_phase_id=current.phase_id
        ).model_dump(mode="json")
        for rm in read_models:
            await rm.on_next_phase_ready(event)
        current = next(p for p in phases if p.phase_id == event["next_phase_id"])
    if finish:
        for rm in read_models:
            await rm.on_workflow_completed(
                {
                    "execution_id": _EXECUTION,
                    "completed_at": "2026-10-08T01:00:00+00:00",
                    "completed_phases": completed,
                    "total_phases": len(phases),
                }
            )
    summary = await read_models[0].get_by_id(_EXECUTION)
    detail = await read_models[1].get_by_id(_EXECUTION)
    assert summary is not None
    assert detail is not None
    assert summary.phase_progress == detail.phase_progress
    return summary.phase_progress


_BLOCKED_EVERY_ROUND = dict.fromkeys(_REVIEWS, ReviewVerdict.BLOCKED)


@pytest.mark.parametrize(("directory", "phases"), [("implement-v3", 8), ("reverify-pr", 7)])
class TestTwoRoundProgress:
    async def test_running_before_any_review_counts_out_of_the_two_round_total(
        self, directory: str, phases: int
    ) -> None:
        progress = await _progress(directory, {}, finish=False)

        assert progress.possible == phases
        assert progress.display.endswith(f"of up to {phases}")

    async def test_blocked_every_round_finishes_all_of_them(
        self, directory: str, phases: int
    ) -> None:
        progress = await _progress(directory, _BLOCKED_EVERY_ROUND, finish=True)

        assert (progress.completed, progress.skipped, progress.possible) == (phases, 0, phases)
        assert progress.display == f"{phases} of {phases}"

    async def test_certified_at_round_one_skips_only_the_one_remaining_round(
        self, directory: str, phases: int
    ) -> None:
        verdicts = {"verify": ReviewVerdict.BLOCKED, "reverify": ReviewVerdict.CERTIFIED}
        progress = await _progress(directory, verdicts, finish=True)

        assert (progress.skipped, progress.possible) == (2, phases - 2)
        assert progress.display == f"{phases - 2} of {phases - 2} (2 phases not needed)"
