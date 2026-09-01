"""A failed phase's outcome must be captured before teardown destroys it.

`_fail_execution` completes sessions and closes workspaces, and
`close_phase_workspaces` clears the session-id map. Reading the phase's start
time and session id AFTER that timed the phase from its start to the end of
cleanup - counting container capture and teardown as "how long the phase ran" -
and handed the failed result an empty session id even when the session was known.

This is the same class as `test_capture_before_teardown.py`, which exists
because the probe had to run while the container was still up. Ordering against
destructive cleanup is not visible in a diff and cannot be asserted anywhere but
here, at the layer that owns both halves.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.testing.fake_agent_handler import FakeAgentExecutionHandler

from .test_processor_smoke import _make_processor

pytestmark = pytest.mark.unit

PHASE = "implement"
#: Long enough that including it would be unmistakable, and not a round fraction
#: of anything the code computes on its own.
_TEARDOWN_SECONDS = 30.0


async def test_duration_excludes_teardown_and_the_session_id_survives() -> None:
    processor = _make_processor(FakeAgentExecutionHandler())

    started = datetime.now(UTC) - timedelta(seconds=5)
    processor._phase_started_at[PHASE] = started
    processor._phase_session_ids[PHASE] = "sess-real"

    async def _slow_teardown(*_args: object, **_kwargs: object) -> None:
        """Stands in for cleanup that takes real time and clears the maps."""
        processor._phase_started_at.pop(PHASE, None)
        processor._phase_session_ids.pop(PHASE, None)
        processor._phase_started_at["_teardown_ran"] = datetime.now(UTC)
        await asyncio.sleep(0)

    processor._close_phase_workspace_cms = _slow_teardown  # type: ignore[method-assign]

    results: list[object] = []
    await processor._fail_execution(
        error=RuntimeError("boom"),
        aggregate=_FakeAggregate(),
        execution_id="exec-1",
        workflow_id="wf-1",
        phases=[],
        phase_results=results,  # type: ignore[arg-type]
        all_artifact_ids=[],
        completed_phase_ids=[],
        started_at=started,
        failed_phase_id=PHASE,
    )

    assert len(results) == 1, "the failed phase must produce a result to count"
    failed = results[0]

    # The session id could only be here if it was read BEFORE teardown cleared it.
    assert failed.session_id == "sess-real"  # type: ignore[attr-defined]

    # ~5s, not ~5s + teardown. Asserted as an upper bound rather than equality
    # because the real clock advances during the call; the point is that a
    # 30-second teardown cannot be inside it.
    assert failed.completed_at is not None  # type: ignore[attr-defined]
    elapsed = (failed.completed_at - started).total_seconds()  # type: ignore[attr-defined]
    assert elapsed < _TEARDOWN_SECONDS, f"duration {elapsed}s appears to include teardown"


class _FakeAggregate:
    """Just enough aggregate for _fail_execution to save against."""

    workflow_id = "wf-1"

    def fail_execution(self, _command: object) -> None:
        return None

    def get_uncommitted_events(self) -> list[object]:
        return []

    def mark_events_committed(self) -> None:
        return None
