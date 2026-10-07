"""Phase progress reaches the list response clients render (PC-63).

The read model's skips are dropped if any hop between it and the response -
`_to_execution_summary`, then `_build_execution_summary_response` - forgets
them, and a certified run reads "6/10" again. So this starts from the domain
row and reads the HTTP response model.
"""

from __future__ import annotations

import pytest

from syn_api.routes.executions.queries import (
    _build_execution_summary_response,
    _to_execution_summary,
)
from syn_domain.contexts.orchestration.domain.read_models import WorkflowExecutionSummary

pytestmark = pytest.mark.unit


def test_a_run_certified_at_round_one_reads_six_of_six() -> None:
    row = WorkflowExecutionSummary(
        workflow_execution_id="exec-1",
        workflow_id="sdlc-implement-v3",
        workflow_name="implement-v3",
        status="completed",
        started_at="2026-10-06T00:00:00+00:00",
        completed_at="2026-10-06T01:00:00+00:00",
        completed_phases=6,
        total_phases=10,
        total_tokens=0,
        skipped_phase_ids=("fix_2", "reverify_2", "fix_3", "reverify_3"),
    )

    response = _build_execution_summary_response(_to_execution_summary(row, {}, {}))

    assert response.phase_progress.display == "6 of 6 (4 phases not needed)"
    assert response.phase_progress.skipped == 4
    assert response.phase_progress.percent == 100
    # The raw fields keep their meaning for programmatic consumers.
    assert (response.completed_phases, response.total_phases) == (6, 10)
