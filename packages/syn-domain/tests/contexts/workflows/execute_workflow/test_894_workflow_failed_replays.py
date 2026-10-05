"""A stored `WorkflowFailed` event still loads after `DelegationFailure` moved (#894).

The delegation-failure types moved from `aggregate_execution.delegation_failure`
into `aggregate_execution.value_objects`, because an event may import value
objects and nothing else from its aggregate (VSA). A move of the Python class
must not move the stored shape: these payloads are written exactly as the
event store holds them - plain JSON, no class names - and must load and
re-serialise to the same bytes.
"""

from __future__ import annotations

import json

from syn_domain.contexts.agent_sessions import DelegationOutcome
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DelegationFailure,
    DelegationFailureReason,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)

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
