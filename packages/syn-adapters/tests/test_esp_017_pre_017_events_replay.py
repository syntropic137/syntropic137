"""Events written before ESP v0.17.0 still replay through the client we ship.

ESP v0.17.0 (ADR-027) put one envelope under every SDK and changed how a
stored event is read back:

* the event version is read from metadata, and 0 (never set) reads as 1;
* a payload the registered class rejects RAISES ``EventPayloadError`` instead
  of becoming a ``GenericDomainEvent`` (ADR-023), and in a subscription a
  raised decode error halts the coordinator at that event.

Every event in a syn137 store was written by the v0.16 client: the payload is
``model_dump(mode="json")`` of the event, ``event_version`` is 1. The bytes
below are built that way, not with the v0.17 encoder, and decoded with the
client exactly as ``_create_grpc_client`` configures it.

The legacy un-pause ``ExecutionResumed`` is the case that matters: its
validator refuses it on purpose (``legacy_event_shapes``) so that it replays
generic and owes nothing. Under the v0.17 default it would halt every
projection instead.

It is also the ONLY rejected payload admitted (#1737 review). Admitting every
rejected payload, as ``on_invalid_payload="generic"`` does, would let an
``ExecutionRequested`` missing its ``workflow_id`` replay generic and be
checkpointed past unapplied. Anything that is not a known legacy shape must
still raise, so the coordinator halts where it can be seen.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from event_sourcing import GenericDomainEvent
from event_sourcing.client.grpc_client import GrpcEventStoreClient
from event_sourcing.core.errors import EventPayloadError
from event_sourcing.proto.eventstore.v1 import eventstore_pb2

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage import event_store_client
from syn_domain.contexts.orchestration.domain.events.ExecutionResumedEvent import (
    ExecutionResumedEvent,
)
from syn_domain.contexts.orchestration.slices.start_resume.ResumeStartProcessManager import (
    ResumeStartProcessManager,
)

pytestmark = pytest.mark.unit

PARENT = "exec-parent-1"

#: An un-pause, as `ExecutionResumed` meant before 2026-09-29.
LEGACY_UNPAUSE = {
    "workflow_id": "wf-1",
    "execution_id": PARENT,
    "phase_id": "plan",
    "resumed_at": "2026-09-01T00:00:00+00:00",
}

#: A resume, as the v0.16 client wrote one.
V016_RESUME = ExecutionResumedEvent(
    workflow_id="wf-1",
    execution_id=PARENT,
    resume_execution_id="exec-child-1",
    inherited_phases=[],
    resume_phase_id="implement",
    resumed_at=datetime(2026, 9, 30, tzinfo=UTC),
)


def _stored(
    payload: str, *, event_version: int = 1, event_type: str = "ExecutionResumed"
) -> eventstore_pb2.EventData:
    """A row as the v0.16 client appended it; ``payload`` is its JSON text."""
    return eventstore_pb2.EventData(
        meta=eventstore_pb2.EventMetadata(
            event_id="e-1",
            aggregate_id=PARENT,
            aggregate_type="WorkflowExecution",
            aggregate_nonce=3,
            global_nonce=41,
            event_type=event_type,
            event_version=event_version,
            content_type="application/json",
        ),
        payload=payload.encode("utf-8"),
    )


def _shipped_client() -> GrpcEventStoreClient:
    """The client production builds; constructing it opens no connection."""
    client = event_store_client._create_grpc_client()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(client, GrpcEventStoreClient)
    return client


class _Checkpoints:
    async def save_checkpoint(self, checkpoint: object) -> None:
        del checkpoint

    async def get_checkpoint(self, projection_name: str) -> None:
        del projection_name

    async def delete_checkpoint(self, projection_name: str) -> None:
        del projection_name


class TestAPre017UnpauseStillReplaysGeneric:
    def test_it_decodes_generic_with_its_type(self) -> None:
        envelope = _shipped_client()._proto_to_envelope(_stored(json.dumps(LEGACY_UNPAUSE)))  # pyright: ignore[reportPrivateUsage]

        assert isinstance(envelope.event, GenericDomainEvent)
        assert envelope.metadata.event_type == "ExecutionResumed"
        assert envelope.event.model_dump()["phase_id"] == "plan"

    def test_the_v017_default_would_have_raised(self) -> None:
        """The control: the setting is what keeps it replaying, not the payload."""
        with pytest.raises(EventPayloadError):
            GrpcEventStoreClient()._proto_to_envelope(_stored(json.dumps(LEGACY_UNPAUSE)))  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_it_still_owes_no_start(self) -> None:
        envelope = _shipped_client()._proto_to_envelope(_stored(json.dumps(LEGACY_UNPAUSE)))  # pyright: ignore[reportPrivateUsage]
        store = InMemoryProjectionStore()

        await ResumeStartProcessManager(resume_starter=None, store=store).handle_event(
            envelope, _Checkpoints()
        )

        assert await store.get(ResumeStartProcessManager.PROJECTION_NAME, PARENT) is None


class TestAPre017ResumeStillReplaysTyped:
    @pytest.mark.parametrize("event_version", [1, 0])
    def test_it_decodes_as_the_event(self, event_version: int) -> None:
        """v0.16 wrote version 1; an unset version (0) is read as 1."""
        stored = _stored(
            json.dumps(V016_RESUME.model_dump(mode="json")), event_version=event_version
        )

        envelope = _shipped_client()._proto_to_envelope(stored)  # pyright: ignore[reportPrivateUsage]

        assert isinstance(envelope.event, ExecutionResumedEvent)
        assert envelope.event == V016_RESUME
        assert envelope.metadata.event_version == 1

    def test_an_echoed_event_type_key_is_dropped_not_refused(self) -> None:
        """Older producers put `event_type` in the payload; the strict model forbids extras."""
        stored = _stored(
            json.dumps({**V016_RESUME.model_dump(mode="json"), "event_type": "ExecutionResumed"})
        )

        envelope = _shipped_client()._proto_to_envelope(stored)  # pyright: ignore[reportPrivateUsage]

        assert isinstance(envelope.event, ExecutionResumedEvent)

    @pytest.mark.asyncio
    async def test_it_owes_one_start(self) -> None:
        """The other half: a gate that refused everything would pass the class above."""
        envelope = _shipped_client()._proto_to_envelope(  # pyright: ignore[reportPrivateUsage]
            _stored(json.dumps(V016_RESUME.model_dump(mode="json")))
        )
        store = InMemoryProjectionStore()

        await ResumeStartProcessManager(resume_starter=None, store=store).handle_event(
            envelope, _Checkpoints()
        )

        assert await store.get(ResumeStartProcessManager.PROJECTION_NAME, PARENT) is not None


class TestOnlyTheKnownLegacyShapeIsAdmitted:
    """A rejected payload that is not a known legacy shape fails closed."""

    REQUEST_WITHOUT_WORKFLOW = json.dumps(
        {"execution_id": "exec-1", "requested_at": "2026-10-01T00:00:00+00:00"}
    )

    def test_a_request_missing_its_workflow_raises(self) -> None:
        stored = _stored(self.REQUEST_WITHOUT_WORKFLOW, event_type="ExecutionRequested")

        with pytest.raises(EventPayloadError):
            _shipped_client()._proto_to_envelope(stored)  # pyright: ignore[reportPrivateUsage]

    def test_a_blanket_generic_policy_would_have_admitted_it(self) -> None:
        """The control: the narrowing is what refuses it, not the payload."""
        stored = _stored(self.REQUEST_WITHOUT_WORKFLOW, event_type="ExecutionRequested")
        lenient = GrpcEventStoreClient(on_invalid_payload="generic")

        envelope = lenient._proto_to_envelope(stored)  # pyright: ignore[reportPrivateUsage]

        assert isinstance(envelope.event, GenericDomainEvent)

    def test_an_ambiguous_resumed_payload_raises(self) -> None:
        """Neither marker is not a legacy shape; it is refused, not guessed."""
        stored = _stored(json.dumps({"workflow_id": "wf-1", "execution_id": PARENT}))

        with pytest.raises(EventPayloadError):
            _shipped_client()._proto_to_envelope(stored)  # pyright: ignore[reportPrivateUsage]

    def test_a_payload_that_is_not_json_raises(self) -> None:
        with pytest.raises(EventPayloadError):
            _shipped_client()._proto_to_envelope(_stored("{not json"))  # pyright: ignore[reportPrivateUsage]
