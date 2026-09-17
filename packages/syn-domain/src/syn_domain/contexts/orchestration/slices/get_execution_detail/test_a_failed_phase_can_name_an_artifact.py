"""#1321: the read model an operator opens has to show what a failure kept.

The processor now takes a failing phase's deliverable out of the workspace
before that workspace is abandoned, and ``WorkflowFailed`` carries the ids.
This is the other end of that: until this handler reads them, the artifact is
stored and nothing in the execution detail points at it - which is the same
"delivered nothing" the issue reports, one layer further out.

``artifact_id`` on a failed phase was unconditionally ``None`` before, because
the only handler that ever set it was ``on_phase_completed``. So the one field
an operator looks at to find a refused phase's work was the one field
guaranteed to be empty for a refused phase.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

pytestmark = pytest.mark.unit


def _running_execution() -> dict[str, Any]:
    return {
        "execution_id": "exec-1321",
        "workflow_id": "wf-1321",
        "status": "running",
        # Shaped as ``PhaseDetail.to_dict`` writes it: ``artifact_id`` is
        # present and None, which is what a running phase always looked like
        # and what a failed one used to be stuck at.
        "phases": [
            {
                "phase_id": "research",
                "name": "Research",
                "status": "running",
                "artifact_id": None,
            }
        ],
        "artifact_ids": [],
    }


def _failure(**extra: Any) -> dict[str, Any]:
    event = {
        "execution_id": "exec-1321",
        "workflow_id": "wf-1321",
        "failed_phase_id": "research",
        "error_message": "Phase research reported an unreadable TASK_RESULT",
        "failed_at": "2026-09-17T10:00:00Z",
    }
    event.update(extra)
    return event


async def _project(event: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    store = AsyncMock()
    store.get = AsyncMock(return_value=stored)
    store.save = AsyncMock()
    await WorkflowExecutionDetailProjection(store).on_workflow_failed(event)
    saved: dict[str, Any] = store.save.call_args[0][2]
    return saved


class TestAFailedPhaseNamesWhatWasKept:
    async def test_the_failed_phase_carries_the_artifact_id(self) -> None:
        saved = await _project(
            _failure(failed_phase_artifact_ids=["art-1"]), _running_execution()
        )

        assert saved["phases"][0]["artifact_id"] == "art-1", (
            "The failed phase's record must name what was kept from it; None "
            "here is an artifact nothing links to."
        )
        assert saved["phases"][0]["status"] == "failed", "The phase still failed."

    async def test_the_execution_lists_the_artifact(self) -> None:
        """``artifact_ids: []`` on a failed execution is the line in the issue."""
        saved = await _project(
            _failure(failed_phase_artifact_ids=["art-1", "art-2"]), _running_execution()
        )

        assert saved["artifact_ids"] == ["art-1", "art-2"]

    async def test_an_orphaned_failure_still_lists_them(self) -> None:
        """No stored execution to attach a phase to (#598) - the ids are still
        real, and dropping them here would lose exactly the artifacts nothing
        else records."""
        saved = await _project(_failure(failed_phase_artifact_ids=["art-1"]), None)

        assert saved["artifact_ids"] == ["art-1"]

    async def test_an_event_that_kept_nothing_changes_neither(self) -> None:
        """Every failure that predates #1321 and every failure that wrote no
        file: absent or empty, the phase keeps its None and the execution its
        empty list."""
        saved = await _project(_failure(), _running_execution())

        assert saved["phases"][0]["artifact_id"] is None
        assert saved["artifact_ids"] == []
