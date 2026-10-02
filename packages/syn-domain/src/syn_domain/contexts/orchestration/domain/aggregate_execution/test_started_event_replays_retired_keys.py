"""A start event written before `can_open_pr` was removed still replays TYPED.

`WorkflowExecutionStarted` forbids extra fields, and that strictness reaches
the `ExecutablePhase` dataclasses nested in `pinned_phases`. Every start event
written between #1454 and the removal carries `pinned_phases[*].can_open_pr`.
Without `started_payload_for_replay` those events fail typed validation and
ADR-023 replays them as a `GenericDomainEvent` - logged at debug, so nothing
says it happened. Nothing breaks loudly; the execution's own typed history
silently stops being typed.

The fixtures are built from a real event's stored shape with the key put back,
which is exactly what the event store holds for those executions.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from event_sourcing import DomainEvent, EventEnvelope, EventMetadata

from syn_domain.contexts.orchestration._shared import retired_phase_fields
from syn_domain.contexts.orchestration.domain.aggregate_execution.start_pins import (
    read_pinned_phases,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    INHERITED_PHASE_OWNERS,
    REMOVED_EXECUTABLE_PHASE_KEYS,
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

pytestmark = pytest.mark.unit

EXECUTION = "exec-pre-retirement"


def _pinned() -> list[ExecutablePhase]:
    """Configured the way no default would produce, so a lost pin shows."""
    return [
        ExecutablePhase(
            phase_id=p,
            name=p.title(),
            order=i + 1,
            agent_config=AgentConfiguration(model=f"model-for-{p}"),
            prompt_template=f"{p} as pinned",
            timeout_seconds=600 * (i + 1),
        )
        for i, p in enumerate(("research", "open_pr"))
    ]


def _stored_before_retirement(**stored_keys: JsonValue) -> str:
    """A start event's JSON as written while `ExecutablePhase` had the field.

    ``stored_keys`` are top-level keys the stored document also carried.
    """
    phases = _pinned()
    event = WorkflowExecutionStartedEvent(
        workflow_id="wf-1",
        execution_id=EXECUTION,
        workflow_name="Pre-retirement",
        started_at=datetime(2026, 9, 30, tzinfo=UTC),
        total_phases=len(phases),
        inputs={"task": "replay me"},
        pinned_phases=phases,
    )
    payload = event.model_dump(mode="json")
    payload["pinned_phases"] = [
        {**phase, "can_open_pr": phase["phase_id"] == "open_pr"}
        for phase in payload["pinned_phases"]
    ]
    return json.dumps({**payload, **stored_keys})


class TestAStartEventWrittenBeforeRetirement:
    def test_it_validates_as_the_typed_event(self) -> None:
        """The trap: anything but a typed event here is the silent generic downgrade."""
        event = WorkflowExecutionStartedEvent.model_validate_json(_stored_before_retirement())

        assert event.pinned_phases == _pinned()

    def test_its_execution_reads_the_pins_typed_and_can_be_resumed_from_them(self) -> None:
        """The consumer of the pins: what a resume would run comes back intact."""
        event = WorkflowExecutionStartedEvent.model_validate_json(_stored_before_retirement())
        aggregate = WorkflowExecutionAggregate()

        aggregate.rehydrate(
            [
                EventEnvelope[DomainEvent](
                    event=event,
                    metadata=EventMetadata(
                        aggregate_id=EXECUTION,
                        aggregate_type="WorkflowExecution",
                        aggregate_nonce=1,
                    ),
                )
            ]
        )

        assert aggregate.start_pins.pinned_phases == _pinned()

    def test_owners_are_still_restored(self) -> None:
        """Composing the drop with #1462's owner restore must keep both."""
        grandparent = "exec-grandparent"
        stored = _stored_before_retirement(
            resumed_from={
                "parent_execution_id": "exec-parent",
                "inherited_phases": [{"phase_id": "research", "artifact_ids": ["art-1"]}],
                "resume_phase_id": "open_pr",
            },
            **{INHERITED_PHASE_OWNERS: {"research": grandparent}},
        )

        event = WorkflowExecutionStartedEvent.model_validate_json(stored)

        assert event.pinned_phases == _pinned()
        assert event.resumed_from is not None
        inherited = event.resumed_from.inherited_phases[0]
        assert event.resumed_from.owner_of(inherited) == grandparent

    def test_generic_replay_still_reads_the_pins(self) -> None:
        """ADR-023's other path: `read_pinned_phases` on the raw stored list."""
        stored = json.loads(_stored_before_retirement())["pinned_phases"]

        assert read_pinned_phases(stored) == _pinned()

    def test_tolerance_does_not_depend_on_the_authoring_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rejecting the key at authoring time (#1496) must not break replay.

        The authoring policy will change; stored history will not. If the event
        adapter ever reads the authoring table again, emptying it here fails
        this test before it fails a production replay.
        """
        monkeypatch.setattr(retired_phase_fields, "RETIRED_PHASE_FIELDS", ())
        monkeypatch.setattr(retired_phase_fields, "_RETIRED_NAMES", frozenset())

        event = WorkflowExecutionStartedEvent.model_validate_json(_stored_before_retirement())

        assert event.pinned_phases == _pinned()


class TestANewStartEvent:
    def test_it_does_not_write_the_key(self) -> None:
        payload = WorkflowExecutionStartedEvent.model_validate_json(
            _stored_before_retirement()
        ).model_dump(mode="json")

        assert all("can_open_pr" not in p for p in payload["pinned_phases"])

    def test_removed_keys_are_not_live_fields(self) -> None:
        """Re-adding a field under a removed name would be stripped from history."""
        live = {f.name for f in dataclasses.fields(ExecutablePhase)}

        assert REMOVED_EXECUTABLE_PHASE_KEYS.isdisjoint(live)
