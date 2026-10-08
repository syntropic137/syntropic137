"""The gRPC event store client, admitting known legacy payload shapes only.

ESP v0.17.0 (ADR-027) decodes strictly: a stored payload its registered class
rejects raises ``EventPayloadError``, and a subscription halts at it. Its one
alternative, ``on_invalid_payload="generic"``, admits EVERY rejected payload as
a ``GenericDomainEvent``, and most consumers read a generic event of a type
they handle as an empty one: an ``ExecutionRequested`` without ``workflow_id``
would be checkpointed past unapplied, with no hold, no halt and no start.

So decoding stays strict, and a rejected payload is let through generic only
when the domain names it as a legacy shape it reads on purpose
(``legacy_event_shapes.replays_generic``). Everything else still raises.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from event_sourcing.client.grpc_client import GrpcEventStoreClient
from event_sourcing.core.errors import EventPayloadError

from syn_domain.contexts.orchestration import replays_generic

if TYPE_CHECKING:
    from event_sourcing import DomainEvent, EventEnvelope
    from event_sourcing.core.envelope import EventTypeFilter
    from event_sourcing.proto.eventstore.v1 import eventstore_pb2


class LegacyShapeTolerantGrpcClient(GrpcEventStoreClient):
    """Strict decoding, except for the payload shapes the domain admits."""

    def __init__(self, address: str, tenant_id: str) -> None:
        super().__init__(address=address, tenant_id=tenant_id, on_invalid_payload="raise")
        #: Decodes only what this client has already admitted. Never connected:
        #: decoding needs no channel.
        self._admitted = GrpcEventStoreClient(
            address=address, tenant_id=tenant_id, on_invalid_payload="generic"
        )

    def _proto_to_envelope(
        self,
        event_data: eventstore_pb2.EventData,
        event_types: EventTypeFilter | None = None,
    ) -> EventEnvelope[DomainEvent]:
        try:
            return super()._proto_to_envelope(event_data, event_types)
        except EventPayloadError:
            if not replays_generic(event_data.meta.event_type, _json_object(event_data.payload)):
                raise
            return self._admitted._proto_to_envelope(event_data, event_types)  # pyright: ignore[reportPrivateUsage]


def _json_object(payload: bytes) -> object:
    """The stored payload as JSON, or None when it is not JSON at all."""
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
