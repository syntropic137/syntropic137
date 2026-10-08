"""A stored `WorkflowFailed` event still loads after `DelegationFailure` moved (#894),
and with or without either of its optional failure accounts (#894, #1593).

The delegation-failure types moved from `aggregate_execution.delegation_failure`
into `aggregate_execution.value_objects`, because an event may import value
objects and nothing else from its aggregate (VSA). A move of the Python class
must not move the stored shape: these payloads are written exactly as the
event store holds them - plain JSON, no class names - and must load and
re-serialise to the same bytes.
"""

from __future__ import annotations

import json

import pytest

from syn_domain.contexts.agent_sessions import DelegationOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    FailExecutionCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.lifecycle_events import (
    failed_event,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DelegationFailure,
    DelegationFailureReason,
    FailureClassification,
    UpstreamFailureKind,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    DelegationFailedError,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_outcome import (
    failed_phase_outcome,
)
from syn_shared.upstream_failure import UpstreamFailureError

pytestmark = pytest.mark.unit

_BASE = {
    "workflow_id": "wf-894",
    "execution_id": "exec-894",
    "failed_at": "2026-10-01T12:00:00Z",
    "error_message": "declared delegation did not happen",
    "completed_phases": 0,
    "total_phases": 2,
}

# As written by the head before the move (1a2cca12): the nested shape is
# `reason` / `attempts[]` / `detail`, each attempt
# `delegate_id` / `target_harness` / `outcome` / `exit_code` / `reason`.
_STORED_DELEGATION = {
    "reason": "failed",
    "attempts": [
        {
            "delegate_id": "d-1",
            "target_harness": "codex",
            "outcome": DelegationOutcome.FAILED.value,
            "exit_code": 2,
            "reason": None,
        },
        {
            "delegate_id": "d-2",
            "target_harness": "codex",
            "outcome": None,
            "exit_code": None,
            "reason": "binary missing",
        },
    ],
    "detail": None,
}


def test_a_stored_delegation_failure_loads_and_reserialises_unchanged() -> None:
    stored = json.loads(json.dumps({**_BASE, "delegation_failure": _STORED_DELEGATION}))

    event = WorkflowFailedEvent.model_validate(stored)

    assert isinstance(event.delegation_failure, DelegationFailure)
    assert event.delegation_failure.reason is DelegationFailureReason.FAILED
    assert [a.delegate_id for a in event.delegation_failure.attempts] == ["d-1", "d-2"]
    assert event.delegation_failure.attempts[0].outcome is DelegationOutcome.FAILED
    assert event.delegation_failure.attempts[1].reason == "binary missing"
    # Written before `required_delegate` existed, so it loads as None and is
    # re-serialised with that one key added; every stored key is unchanged.
    assert event.model_dump(mode="json")["delegation_failure"] == {
        **_STORED_DELEGATION,
        "required_delegate": None,
    }


def test_an_unverifiable_delegation_failure_keeps_its_detail() -> None:
    stored = {
        **_BASE,
        "delegation_failure": {
            "reason": "unverifiable",
            "attempts": [],
            "detail": "journal unreadable",
        },
    }

    event = WorkflowFailedEvent.model_validate(stored)

    assert event.delegation_failure == DelegationFailure(
        reason=DelegationFailureReason.UNVERIFIABLE, detail="journal unreadable"
    )


def test_an_event_written_before_894_still_loads_with_no_delegation_failure() -> None:
    event = WorkflowFailedEvent.model_validate(dict(_BASE))

    assert event.delegation_failure is None


# #894 and #1593 each added one optional field to this event, in parallel
# branches. Every combination the store can hold must load: events written
# before both, before either one, and after both.
@pytest.mark.parametrize(
    ("upstream", "delegation"),
    [
        (None, None),
        (UpstreamFailureKind.UNAVAILABLE, None),
        (None, DelegationFailureReason.FAILED),
        (UpstreamFailureKind.UNAVAILABLE, DelegationFailureReason.FAILED),
    ],
    ids=["neither", "upstream-only", "delegation-only", "both"],
)
def test_each_combination_of_the_two_failure_accounts_replays(
    upstream: UpstreamFailureKind | None,
    delegation: DelegationFailureReason | None,
) -> None:
    # A key absent rather than null, as the store holds events written before
    # the field existed.
    written = dict(_BASE)
    if upstream is not None:
        written["upstream_failure_kind"] = upstream.value
    if delegation is not None:
        written["delegation_failure"] = {**_STORED_DELEGATION, "reason": delegation.value}
    stored = json.loads(json.dumps(written))

    event = WorkflowFailedEvent.model_validate(stored)

    assert event.upstream_failure_kind is upstream
    if delegation is None:
        assert event.delegation_failure is None
    else:
        assert event.delegation_failure is not None
        assert event.delegation_failure.reason is delegation
    # Re-serialised as the store writes it (`model_dump(mode="json")`) and
    # loaded again, it is the same event: what replay does on every restart.
    again = WorkflowFailedEvent.model_validate(
        json.loads(json.dumps(event.model_dump(mode="json")))
    )
    assert again == event


def _stored_failure(error: BaseException) -> WorkflowFailedEvent:
    """`error` through every hop to the store and back: account, command, event, JSON."""
    outcome = failed_phase_outcome(error, "phase-1", {}, {})
    command = outcome.as_command("exec-894", completed_phases=0, total_phases=2)
    written = json.dumps(failed_event(command, "wf-894").model_dump(mode="json"))
    return WorkflowFailedEvent.model_validate(json.loads(written))


def test_a_failed_delegation_lands_in_its_own_field_not_the_upstream_one() -> None:
    # The two fields arrived as the third slot of the same `FailureAccount` in
    # two branches; read positionally, a delegation would be stored as an
    # upstream kind.
    event = _stored_failure(
        DelegationFailedError(
            phase_id="phase-1",
            required_delegate="codex",
            reason=DelegationFailureReason.NOT_ATTEMPTED,
        )
    )

    assert event.upstream_failure_kind is None
    assert event.delegation_failure is not None
    assert event.delegation_failure.required_delegate == "codex"
    assert event.delegation_failure.reason is DelegationFailureReason.NOT_ATTEMPTED


def test_an_upstream_failure_lands_in_its_own_field_not_the_delegation_one() -> None:
    event = _stored_failure(
        UpstreamFailureError("GitHub 503", upstream_kind=UpstreamFailureKind.UNAVAILABLE)
    )

    assert event.upstream_failure_kind is UpstreamFailureKind.UNAVAILABLE
    assert event.delegation_failure is None


def test_a_command_carrying_both_records_both() -> None:
    delegation = DelegationFailure(
        required_delegate="codex", reason=DelegationFailureReason.UNVERIFIABLE, detail="x"
    )
    command = FailExecutionCommand(
        execution_id="exec-894",
        error="both",
        error_type=None,
        failed_phase_id="phase-1",
        completed_phases=0,
        total_phases=2,
        classification=FailureClassification.PLATFORM,
        upstream_failure_kind=UpstreamFailureKind.AUTH,
        delegation_failure=delegation,
    )

    event = WorkflowFailedEvent.model_validate(
        json.loads(json.dumps(failed_event(command, "wf-894").model_dump(mode="json")))
    )

    assert event.upstream_failure_kind is UpstreamFailureKind.AUTH
    assert event.delegation_failure == delegation
