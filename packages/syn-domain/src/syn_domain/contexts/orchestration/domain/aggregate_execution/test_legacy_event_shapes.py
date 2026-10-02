"""The string `ExecutionResumed` changed meaning on 2026-09-29.

Before: un-pausing a paused execution (fields `phase_id`, `resumed_at`).
After: continuing an execution that did not finish (fields
`resume_execution_id`, `inherited_phases`, `resume_phase_id`).

Production held zero of the old kind when this shipped, but the window between
the merge and the deploy was not closed, and a developer's local stream may
hold either. A payload written under the old meaning must never be read as the
new one: that would make an execution look resumed when nobody resumed it, and
spend its one resume.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    LegacyEventShapeError,
    classify_resumed_payload,
    upcast_forked_payload,
)

pytestmark = pytest.mark.unit


def test_the_old_unpause_shape_is_recognised_and_refused() -> None:
    old = {
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "phase_id": "plan",
        "resumed_at": "2026-09-01T00:00:00Z",
    }

    with pytest.raises(LegacyEventShapeError, match="un-pausing"):
        classify_resumed_payload(old)


def test_the_new_resume_shape_passes() -> None:
    new = {
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "resume_execution_id": "exec-2",
        "inherited_phases": [],
        "resume_phase_id": "plan",
        "resumed_at": "2026-09-29T00:00:00Z",
    }

    assert classify_resumed_payload(new) is None


def test_a_payload_with_neither_marker_is_refused_rather_than_guessed() -> None:
    """Silence about which shape it is must not read as the new one.

    The new shape is the one that spends an execution's single resume, so a
    payload that cannot be identified is refused in the direction that costs
    a log line rather than the direction that costs a run.
    """
    with pytest.raises(LegacyEventShapeError, match="cannot be determined"):
        classify_resumed_payload({"workflow_id": "wf-1", "execution_id": "exec-1"})


def test_a_pre_rename_forked_payload_upcasts_rather_than_vanishing() -> None:
    """An `ExecutionForked` event from the pre-rename build must still be read.

    Dropping it silently would make its parent look unresumed and admit a
    second resume, which the one-resume rule exists to prevent.
    """
    forked = {
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "fork_execution_id": "exec-2",
        "inherited_phases": [],
        "resume_phase_id": "plan",
        "forked_at": "2026-09-26T00:00:00Z",
    }

    upcast = upcast_forked_payload(forked)

    assert upcast["resume_execution_id"] == "exec-2"
    assert upcast["resumed_at"] == "2026-09-26T00:00:00Z"
    assert "fork_execution_id" not in upcast
    assert "forked_at" not in upcast


def test_an_upcast_forked_payload_then_classifies_as_the_new_shape() -> None:
    """The two halves must compose: an upcast payload is readable as a resume.

    Tested because each half passing its own test says nothing about the
    handoff between them, and the handoff is the whole point.
    """
    forked = {
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "fork_execution_id": "exec-2",
        "inherited_phases": [],
        "resume_phase_id": "plan",
        "forked_at": "2026-09-26T00:00:00Z",
    }

    assert classify_resumed_payload(upcast_forked_payload(forked)) is None


def test_upcasting_does_not_mutate_what_it_was_given() -> None:
    """The caller's stored payload must survive the call unchanged.

    An in-place pop would corrupt the record an upcast failure needs to report.
    """
    forked = {"fork_execution_id": "exec-2", "forked_at": "2026-09-26T00:00:00Z"}

    upcast_forked_payload(forked)

    assert forked == {"fork_execution_id": "exec-2", "forked_at": "2026-09-26T00:00:00Z"}


class TestWhichFieldsIdentifyAResume:
    """Why the post-rename marker set has three members and not one.

    Keying on `resume_execution_id` alone looked sufficient and was not: under
    ADR-023 a stored event that fails typed validation replays as a generic
    one whose absent fields simply read as missing, so a resume that lost its
    child id would classify as an un-pause. The parent would then replay as
    never-resumed and a SECOND resume would be admitted - two runs on one
    piece of work, which is the failure the at-most-once rule exists to stop.

    The full unit suite caught this through `TestTheResumeGuardFailsClosed`.
    Pinned here too, beside the constant, so the next person to narrow the set
    is told why it is wide.
    """

    def test_a_resume_that_lost_its_child_id_is_still_a_resume(self) -> None:
        lost_the_id = {
            "workflow_id": "wf-1",
            "execution_id": "exec-1",
            "inherited_phases": [],
            "resume_phase_id": "implement",
            "resumed_at": "2026-09-29T00:00:00Z",
        }

        assert classify_resumed_payload(lost_the_id) is None

    def test_a_resume_that_lost_everything_but_its_phase_is_still_a_resume(self) -> None:
        """The narrowest survivable case: one marker left."""
        assert classify_resumed_payload({"resume_phase_id": "implement"}) is None

    def test_an_unpause_carries_none_of_the_three(self) -> None:
        """The control: widening the set must not swallow the un-pause shape."""
        with pytest.raises(LegacyEventShapeError, match="un-pausing"):
            classify_resumed_payload({"phase_id": "plan", "resumed_at": "2026-09-01T00:00:00Z"})
