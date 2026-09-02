"""What a phase reports when it ends, on either path.

These exist because extracting the success half out of
`WorkflowExecutionProcessor` exposed that it was never tested: deleting the
`zero_tokens` warning and dropping the completed result both left the whole
suite green. That is not a regression from the extraction - the code was
untested inside the processor too - but a helper is testable where a 900-line
method's private middle was not, so the coverage is owed now.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow import phase_outcome
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    completed_phase,
    failed_phase_elapsed_seconds,
)

pytestmark = pytest.mark.unit

_START = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
#: 407 seconds. Not a default, not a round number, and not derivable from zeros.
_END = _START + timedelta(seconds=407)


class _ClockStub:
    """Stands in for the `datetime` module, handing out a new time per `now()`.

    Deliberately not a frozen timestamp: a frozen clock cannot distinguish one
    read from two, which is the whole point of the test that uses this.
    """

    def __init__(self, next_now):
        self._next_now = next_now

    def now(self, tz=None):
        return self._next_now(tz)


def _outcome(
    *, artifact_ids: list[str] | None = None, auth: tuple[int, int, int, int] | None = None
):
    return completed_phase(
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id="implement",
        session_id="sess-1",
        started_at=_START,
        artifact_ids=[] if artifact_ids is None else artifact_ids,
        auth_tokens=auth,
        now=_END,
    )


def test_duration_comes_from_when_the_phase_started() -> None:
    """407s cannot arise from a default: the zero value here is 0.0."""
    assert _outcome().duration_seconds == 407.0
    assert _outcome().command.duration_seconds == 407.0


def test_absent_authoritative_tokens_fall_back_to_zero_not_to_a_guess() -> None:
    """A partial phase reports zeros; Lane 2 holds the real cost.

    Asserting zero is only meaningful alongside the case below, which proves a
    non-zero value survives - otherwise this passes against code that always
    returns zero.
    """
    outcome = _outcome(auth=None)

    assert outcome.total_tokens == 0
    assert outcome.command.total_tokens == 0


def test_authoritative_tokens_are_carried_and_totalled() -> None:
    outcome = _outcome(auth=(11, 22, 33, 44))

    assert (outcome.input_tokens, outcome.output_tokens) == (11, 22)
    assert (outcome.cache_creation_tokens, outcome.cache_read_tokens) == (33, 44)
    assert outcome.total_tokens == 110
    assert outcome.command.total_tokens == 110
    assert outcome.result.total_tokens == 110


def test_a_phase_that_burned_no_tokens_is_flagged() -> None:
    """Deleting this warning left the whole suite green before these tests."""
    assert "zero_tokens" in _outcome(auth=(0, 0, 5, 5)).result.metadata["warnings"]


def test_a_phase_that_produced_nothing_is_flagged() -> None:
    assert "no_artifacts" in _outcome(auth=(1, 1, 0, 0)).result.metadata["warnings"]


def test_a_healthy_phase_is_flagged_as_neither() -> None:
    """Without this, a rule that warned unconditionally would pass every case above."""
    outcome = _outcome(artifact_ids=["art-1"], auth=(1, 1, 0, 0))

    assert outcome.result.metadata.get("warnings", []) == []


def test_the_first_artifact_is_the_one_the_command_carries() -> None:
    outcome = _outcome(artifact_ids=["first", "second"], auth=(1, 1, 0, 0))

    assert outcome.command.artifact_id == "first"


def test_a_phase_that_never_started_has_no_duration_rather_than_zero() -> None:
    """None and 0.0 differ: 0.0 claims it began and took no time."""
    assert failed_phase_elapsed_seconds(None) is None
    assert failed_phase_elapsed_seconds(_START, now=_END) == 407.0


def test_one_phase_reports_one_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command and the returned value must be the SAME measurement.

    Uses a clock that advances a full second on every read, rather than relying
    on real `datetime.now()` calls happening to differ. The first version of this
    test did rely on that, and a cross-model review pointed out it is flaky
    exactly where it matters: two consecutive `now()` calls can return the same
    value, and then code that reads the clock twice passes.

    A regression test for a timing bug that depends on timing to detect it is not
    a regression test. With this clock, one read gives equal durations and two
    reads differ by a second, deterministically.

    It matters because the two values go to different places - the command to the
    aggregate and its event, the returned duration to observability - so a split
    reading puts two different durations on one phase.
    """
    ticks = iter([_START + timedelta(seconds=n) for n in (100, 200, 300, 400)])
    monkeypatch.setattr(
        phase_outcome, "datetime", _ClockStub(lambda _tz: next(ticks)), raising=True
    )

    outcome = completed_phase(
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id="implement",
        session_id="sess-1",
        started_at=_START,
        artifact_ids=["art-1"],
        auth_tokens=(1, 1, 0, 0),
    )

    assert outcome.duration_seconds == outcome.command.duration_seconds
    # And the single read is the FIRST tick, not some later one: 100s, not 200s.
    assert outcome.duration_seconds == 100.0


def test_a_failed_phase_is_counted_in_the_execution_metrics() -> None:
    """The synchronous execute response counts the failed phase (#1036 side effect).

    Before the failure path produced a `PhaseResult`, `ExecutionMetrics.from_results`
    never saw the failed phase: `total_phases` counted only the ones that finished,
    and `failed_phases` was always 0 for a run that failed. `POST /workflows/{id}/execute`
    builds its response straight from those metrics, so a synchronous failure
    reported counts that were quietly wrong.

    That correction rode along with this PR's extraction rather than being asked
    for, which is precisely why it needs a test: an unlabelled behaviour change is
    one nobody will notice regressing.
    """
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutionMetrics,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
        failed_phase_result,
    )

    succeeded = _outcome(artifact_ids=["art-1"], auth=(1, 1, 0, 0)).result
    failed = failed_phase_result("implement", _START, "sess-2", "timed out", ended_at=_START)
    assert failed is not None

    metrics = ExecutionMetrics.from_results([succeeded, failed])

    # 2, not 1: the failed phase used to be invisible here.
    assert metrics.total_phases == 2
    assert metrics.completed_phases == 1
    assert metrics.failed_phases == 1


def test_a_phase_that_started_and_died_produces_a_result_to_count() -> None:
    """The failure path must yield a result, or the metrics above see nothing.

    Pairs with the metrics test: that one proves `from_results` counts a failed
    result correctly, this one proves one exists to be counted.

    KNOWN GAP, stated rather than implied: neither covers the two lines in
    `WorkflowExecutionProcessor._fail_execution` that actually append it.
    Deleting them leaves this whole file green. Closing that needs a
    processor-level test with real repository plumbing, which is a larger piece
    than this PR - and a gap named is worth more than a gap assumed covered.
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
        failed_phase_outcome,
    )

    duration, result = failed_phase_outcome(
        "exec-1",
        "implement",
        {("exec-1", "implement"): _START},
        {("exec-1", "implement"): "sess-9"},
        "timed out",
    )

    assert result is not None
    assert result.phase_id == "implement"
    assert duration is not None and duration > 0

    # A phase with no recorded start yields neither, rather than a zero-duration
    # result that would enter the metrics as a phase that ran instantly.
    assert failed_phase_outcome("exec-1", "implement", {}, {}, "timed out") == (None, None)


async def test_a_failed_run_adds_to_workflow_duration_rather_than_replacing_it() -> None:
    """The metrics projection aggregates by workflow_id, across executions.

    `on_phase_completed` adds to `duration_seconds`; the failure handler must
    too. Assigning made a failed run erase the workflow's accumulated history -
    ten seconds of completed work then a three-second failure reported three,
    which is worse than the omission #1036 set out to fix.

    The fixture values discriminate: 10 and 3 share no factor with each other or
    with 0, so 13 cannot arise from assignment, from dropping either term, or
    from a default.
    """
    from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
    from syn_domain.contexts.orchestration.slices.workflow_phase_metrics.projection import (
        WorkflowPhaseMetricsProjection,
    )

    projection = WorkflowPhaseMetricsProjection(InMemoryProjectionStore())
    phase = {"workflow_id": "wf-1", "phase_id": "implement"}

    await projection.on_phase_started({**phase, "execution_id": "e1"})
    await projection.on_phase_completed({**phase, "execution_id": "e1", "duration_seconds": 10.0})
    await projection.on_phase_started({**phase, "execution_id": "e2"})
    await projection.on_workflow_failed(
        {
            "workflow_id": "wf-1",
            "failed_phase_id": "implement",
            "failed_phase_duration_seconds": 3.0,
        }
    )

    metrics = await projection.get_phase_metrics("wf-1")

    assert metrics["implement"]["duration_seconds"] == 13.0
    assert metrics["implement"]["status"] == "failed"


def test_the_failed_phase_duration_matches_its_own_completed_at() -> None:
    """One clock reading on the failure path, not two.

    `failed_phase_outcome` computed the duration and then `PhaseResultBuilder`
    independently read the clock for `completed_at`, so the two disagreed by
    however long the intervening work took. This is the same defect already
    fixed on the success path; a reader comparing a failed phase's timestamps
    against its recorded duration would find them inconsistent.

    Passing an explicit instant makes a second read unmissable: a builder that
    calls the clock itself stamps wall-now, not the instant supplied here, so
    the gap is hours rather than the microseconds a real clock would hide.
    """
    from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
        failed_phase_outcome,
    )

    ended = _START + timedelta(seconds=5)
    duration, result = failed_phase_outcome(
        "exec-1",
        "implement",
        {("exec-1", "implement"): _START},
        {("exec-1", "implement"): "sess-2"},
        "timed out",
        now=ended,
    )

    assert result is not None
    assert duration is not None
    assert (result.completed_at - result.started_at).total_seconds() == duration
    assert duration == 5.0
    assert result.completed_at == ended
