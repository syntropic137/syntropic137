"""A terminal outcome applies itself to the run; the processor does not unpack it.

`PhaseFailure` was a four-field carrier that `WorkflowExecutionProcessor._fail_execution`
took apart: it read `failure.result`, decided the None rule, and appended; it read
`failure.reason` and chose which of the runtime's two completion verbs to hand it to,
and which literal to abandon under. `CancelledExecution` was unpacked the same way one
method above. Every one of those was a decision about the OUTCOME being made at the call
site, which is what #1205 recorded: failure construction could not change without editing
the processor.

These tests pin the boundary from the outside. They construct an outcome and hand it a
recording double, asserting only what the outcome does to its sinks - never how it decided
to. The ordering assertions are the load-bearing ones: `abandon_all` clears the session
managers that `report_failed`/`report_cancelled` iterate, so completing sessions after
releasing them closes nothing and no other test in the suite would notice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    cancelled_execution,
    failed_phase_outcome,
)

pytestmark = pytest.mark.unit

_START = datetime(2026, 3, 4, 4, 59, 20, tzinfo=UTC)
#: 407 seconds. Not a default, not a round number, not derivable from zeros.
_END = _START + timedelta(seconds=407)
PHASE = "implement"

#: A message no default produces: `str(error)` on a bare exception is "", and the
#: describe-the-exception fallback names the type. This one is neither.
_MESSAGE = "output contract unmet for phase implement"


class _RecordingRuntime:
    """The teardown face of `PhaseRuntime`, logging what an outcome asks of it.

    Structural, not a subclass: if `PhaseRuntime` renames one of these three, the
    Protocol in `phase_outcome` stops being satisfied and pyright says so at the
    processor's call site rather than here.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def report_failed(self, error_message: str) -> None:
        self.calls.append(("report_failed", error_message))

    async def report_cancelled(self, reason: str) -> None:
        self.calls.append(("report_cancelled", reason))

    async def abandon_all(self, context: str) -> None:
        self.calls.append(("abandon_all", context))


def _failure(*, phase_id: str | None = PHASE):
    return failed_phase_outcome(
        RuntimeError(_MESSAGE),
        phase_id,
        {PHASE: _START} if phase_id else {},
        {PHASE: "sess-real"} if phase_id else {},
        now=_END,
    )


async def test_a_failure_ends_its_own_sessions_as_failed() -> None:
    """The verb and the abandon context are the failure's, not the caller's.

    Reported failed - not cancelled - carrying the same account of why that every
    other sink got, and only then released.
    """
    runtime = _RecordingRuntime()

    await _failure().wind_down(runtime)

    assert runtime.calls == [
        ("report_failed", _MESSAGE),
        ("abandon_all", "failure"),
    ]


async def test_a_cancellation_ends_its_own_sessions_as_cancelled() -> None:
    """The sibling instance of the same defect: `cancellation.reason` was unpacked too."""
    runtime = _RecordingRuntime()

    await cancelled_execution("operator stopped the run", [], []).wind_down(runtime)

    assert runtime.calls == [
        ("report_cancelled", "operator stopped the run"),
        ("abandon_all", "cancel"),
    ]


async def test_a_cancellation_winds_down_under_its_resolved_reason() -> None:
    """The default is resolved once, and the sessions are closed with THAT.

    A caller that passed `cancel_reason` straight through would close the sessions
    with None while the returned result said "Cancelled by user".
    """
    runtime = _RecordingRuntime()

    await cancelled_execution(None, [], []).wind_down(runtime)

    assert runtime.calls[0] == ("report_cancelled", "Cancelled by user")


def test_a_failed_phase_records_itself_in_the_run() -> None:
    """The result reaches the run's list without the caller knowing there is one."""
    phase_results: list[object] = []

    _failure().record_in(phase_results)  # type: ignore[arg-type]

    assert len(phase_results) == 1
    recorded = phase_results[0]
    assert recorded.phase_id == PHASE  # type: ignore[attr-defined]
    # Could not have arisen from a default: the map that held it is emptied by
    # teardown, and the failure had to read it before that (#1036).
    assert recorded.session_id == "sess-real"  # type: ignore[attr-defined]
    assert recorded.error_message == _MESSAGE  # type: ignore[attr-defined]


def test_a_failure_with_no_started_phase_records_nothing() -> None:
    """The None rule is the failure's. Inventing a result would put a phase that
    never ran into the execution's results, and counting it would move the metrics."""
    phase_results: list[object] = []

    _failure(phase_id=None).record_in(phase_results)  # type: ignore[arg-type]

    assert phase_results == []
