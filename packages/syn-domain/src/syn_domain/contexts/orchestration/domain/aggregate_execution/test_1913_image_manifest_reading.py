"""The image manifest reading: its three states, and its replay (#1913).

The reading is consumed where it is persisted, the execution aggregate rebuilt
from the JSON of its events, so a field dropped by the command, the event or the
event handler fails here. The real-store round trip is
`tests/integration/test_1913_the_image_manifest_survives_the_real_store.py`.
"""

from __future__ import annotations

import json

import pytest
from event_sourcing import EventEnvelope, GenericDomainEvent, resolve_event_type
from pydantic import ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    ProvisionWorkspaceCompletedCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.image_provenance import (
    IMAGE_MANIFEST_FILE,
    ImageManifestContent,
    ImageManifestReading,
    ImageManifestState,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    StartExecutionCommand,
    StartPhaseCommand,
    WorkflowExecutionAggregate,
)

pytestmark = pytest.mark.unit

MANIFEST = {
    "provider": "claude-cli",
    "provider_version": "1.1.0",
    "components": {"claude_cli": "2.1.76", "rtk": "0.34.3"},
    "build_commit": "e63b4458332a",
    "built_at": "2026-10-01T00:00:00+00:00",
    "manifest_digest": "d55e27a49de81850",
}


def _replayed(reading: ImageManifestReading | None, *, drop: str | None = None):  # noqa: ANN202
    aggregate = WorkflowExecutionAggregate()
    aggregate._handle_command(
        StartExecutionCommand(
            execution_id="exec-1913",
            workflow_id="wf-1913",
            workflow_name="Image provenance",
            total_phases=1,
            inputs={},
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id="exec-1913",
            workflow_id="wf-1913",
            phase_id="build",
            phase_name="Build",
            phase_order=1,
        )
    )
    aggregate.provision_workspace_completed(
        ProvisionWorkspaceCompletedCommand(
            execution_id="exec-1913",
            phase_id="build",
            workspace_id="ws-1913",
            image_manifest=reading,
        )
    )
    envelopes = []
    for envelope in aggregate.get_uncommitted_events():
        payload = envelope.event.model_dump(mode="json")
        payload.pop(drop or "", None)
        metadata = envelope.metadata.model_copy(update={"event_type": envelope.event.event_type})
        concrete = resolve_event_type(envelope.event.event_type)
        assert concrete is not None
        envelopes.append(
            EventEnvelope(
                event=concrete.model_validate_json(json.dumps(payload)), metadata=metadata
            )
        )
    fresh = WorkflowExecutionAggregate()
    fresh.rehydrate(envelopes)
    return fresh


def test_a_manifest_file_is_read() -> None:
    reading = ImageManifestReading.from_files(
        [(IMAGE_MANIFEST_FILE, json.dumps(MANIFEST).encode())]
    )

    assert reading.state is ImageManifestState.READ
    assert reading.manifest == ImageManifestContent(**MANIFEST)


def test_no_manifest_file_is_absent_not_a_manifest_of_empty_fields() -> None:
    reading = ImageManifestReading.from_files([])

    assert reading.state is ImageManifestState.ABSENT
    assert reading.manifest is None
    assert reading.detail is None


@pytest.mark.parametrize(
    "content",
    [b"not json {{{", json.dumps({"provider": "claude-cli"}).encode()],
    ids=["malformed", "missing-fields"],
)
def test_a_file_that_is_not_a_manifest_is_unreadable_with_its_reason(content: bytes) -> None:
    reading = ImageManifestReading.from_files([(IMAGE_MANIFEST_FILE, content)])

    assert reading.state is ImageManifestState.UNREADABLE
    assert reading.detail is not None
    assert IMAGE_MANIFEST_FILE in reading.detail


def test_a_state_and_its_fields_cannot_disagree() -> None:
    with pytest.raises(ValidationError):
        ImageManifestReading(state=ImageManifestState.READ)
    with pytest.raises(ValidationError):
        ImageManifestReading(
            state=ImageManifestState.ABSENT, manifest=ImageManifestContent(**MANIFEST)
        )
    with pytest.raises(ValidationError):
        ImageManifestReading(state=ImageManifestState.UNREADABLE)


@pytest.mark.parametrize(
    "reading",
    [
        ImageManifestReading(
            state=ImageManifestState.READ, manifest=ImageManifestContent(**MANIFEST)
        ),
        ImageManifestReading.absent(),
        ImageManifestReading.unreadable("RuntimeError: sandbox gone"),
    ],
    ids=["read", "absent", "unreadable"],
)
def test_the_reading_survives_replay(reading: ImageManifestReading) -> None:
    assert _replayed(reading).image_manifest_for("build") == reading


def test_a_provisioning_recorded_before_the_field_existed_still_replays() -> None:
    replayed = _replayed(ImageManifestReading.absent(), drop="image_manifest")

    assert replayed.image_manifest_for("build") is None


def test_a_generic_stored_reading_replays_typed() -> None:
    """A stored event that only deserialises generically (ADR-023) still yields the reading."""
    reading = ImageManifestReading.unreadable("RuntimeError: sandbox gone")
    typed = _replayed(reading)
    event = GenericDomainEvent(
        event_type="WorkspaceProvisionedForPhase",
        phase_id="build",
        workspace_id="ws-1913",
        image_manifest=reading.model_dump(mode="json"),
    )
    typed.on_workspace_provisioned_for_phase(event)  # type: ignore[arg-type]

    assert typed.image_manifest_for("build") == reading
