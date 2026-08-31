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

from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    completed_phase,
    failed_phase_elapsed_seconds,
)

pytestmark = pytest.mark.unit

_START = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
#: 407 seconds. Not a default, not a round number, and not derivable from zeros.
_END = _START + timedelta(seconds=407)


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


def test_one_phase_reports_one_duration() -> None:
    """The command and the returned value must be the SAME measurement.

    Deliberately does NOT pin `now`. Every other test here passes a fixed
    timestamp, and that is exactly what hid this: with `now` pinned, code that
    reads the clock twice is indistinguishable from code that reads it once.
    Unpinned, two `datetime.now()` calls differ by microseconds and this fails.

    It matters because the two values go to different places - the command to
    the aggregate and its event, the returned duration to observability - so a
    split reading puts two different durations on one phase.
    """
    outcome = completed_phase(
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id="implement",
        session_id="sess-1",
        started_at=datetime.now(UTC) - timedelta(seconds=5),
        artifact_ids=["art-1"],
        auth_tokens=(1, 1, 0, 0),
    )

    assert outcome.duration_seconds == outcome.command.duration_seconds
