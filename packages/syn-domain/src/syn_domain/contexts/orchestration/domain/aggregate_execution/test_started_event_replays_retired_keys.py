"""Stored start events carrying a removed pinned-phase key replay TYPED, forever.

Every `WorkflowExecutionStarted` written since #1454 pins each phase, and until
the field was retired each pin carried `can_open_pr`. The event forbids extra
keys, so once `ExecutablePhase` stopped declaring it those payloads would fail
typed validation and ADR-023 would replay them as a generic event, logged only
at debug. A resume reads its parent's pins from that event, so the downgrade
surfaces much later as a refused resume.

The payloads here are written the way the store holds them: a typed event
serialised to JSON, with the removed key put back where it used to be written.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from syn_domain.contexts.orchestration._shared import retired_phase_fields
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    read_pinned_phases,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    INHERITED_PHASE_OWNERS,
    REMOVED_EXECUTABLE_PHASE_KEYS,
    ExecutablePhase,
    InheritedPhase,
    ResumeOrigin,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)

pytestmark = pytest.mark.unit

GRANDPARENT = "exec-grandparent"
PARENT = "exec-parent"


def _event(resumed_from: ResumeOrigin | None = None) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id="wf",
        execution_id="exec-child",
        workflow_name="wf",
        started_at=datetime(2026, 9, 1, tzinfo=UTC),
        total_phases=2,
        inputs={},
        pinned_phases=[
            ExecutablePhase(phase_id="research", name="Research", order=1),
            ExecutablePhase(phase_id="open_pr", name="Open PR", order=2),
        ],
        resumed_from=resumed_from,
    )


def _stored_before_retirement(event: WorkflowExecutionStartedEvent) -> object:
    """The event as it was stored while `ExecutablePhase` still had the field."""
    payload = event.model_dump(mode="json")
    payload["pinned_phases"] = [
        {**phase, "can_open_pr": phase["phase_id"] == "open_pr"}
        for phase in payload["pinned_phases"]
    ]
    return payload


class TestAStoredStartEventReplaysTyped:
    def test_a_start_event_written_before_retirement_validates_typed(self) -> None:
        event = WorkflowExecutionStartedEvent.model_validate(_stored_before_retirement(_event()))

        assert event.pinned_phases is not None
        assert [p.phase_id for p in event.pinned_phases] == ["research", "open_pr"]

    def test_owners_are_still_restored(self) -> None:
        """Composing the strip must not lose the #1462 owner restore."""
        origin = ResumeOrigin(
            parent_execution_id=PARENT,
            inherited_phases=[
                InheritedPhase(
                    phase_id="research", artifact_ids=["a1"], origin_execution_id=GRANDPARENT
                )
            ],
            resume_phase_id="open_pr",
        )
        stored = _stored_before_retirement(_event(resumed_from=origin))
        assert isinstance(stored, dict) and INHERITED_PHASE_OWNERS in stored

        event = WorkflowExecutionStartedEvent.model_validate(stored)

        assert event.resumed_from is not None
        assert event.resumed_from.owners() == {"research": GRANDPARENT}
        assert event.pinned_phases is not None and len(event.pinned_phases) == 2

    def test_tolerance_does_not_depend_on_the_authoring_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rejecting the key at authoring time must never break replay (#1502)."""
        monkeypatch.setattr(retired_phase_fields, "RETIRED_PHASE_FIELDS", ())

        event = WorkflowExecutionStartedEvent.model_validate(_stored_before_retirement(_event()))

        assert event.pinned_phases is not None and len(event.pinned_phases) == 2

    def test_generic_replay_still_reads_pins(self) -> None:
        """The other reader of stored pins, used when an event replays generic."""
        payload = _stored_before_retirement(_event())
        assert isinstance(payload, dict)

        phases = read_pinned_phases(payload["pinned_phases"])

        assert [p.phase_id for p in phases] == ["research", "open_pr"]


class TestTheKeyIsGoneForGood:
    def test_a_new_start_event_does_not_write_the_key(self) -> None:
        pinned = _event().model_dump(mode="json")["pinned_phases"]

        assert all("can_open_pr" not in phase for phase in pinned)

    def test_removed_keys_are_not_live_fields(self) -> None:
        """A re-added field with a removed name would be stripped from history."""
        live = {f.name for f in dataclasses.fields(ExecutablePhase)}

        assert REMOVED_EXECUTABLE_PHASE_KEYS.isdisjoint(live)
