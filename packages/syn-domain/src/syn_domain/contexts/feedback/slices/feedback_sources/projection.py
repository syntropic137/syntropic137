"""feedback_sources projection: one row per enrolled Source (ADR-076-feedback-ticketing).

Intake (plan PR 3) refreshes its in-process source set from these rows and
verifies every signed request against ``FeedbackSource.credentials``. The
rows hold public verification keys only.

A pure projection: replaying it any number of times writes the same rows and
calls nothing outside its store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import CheckpointedProjection, ProjectionCheckpoint, ProjectionResult

from syn_domain.contexts.feedback.domain.events import (
    SourceEnrolledEvent,
    SourceKeyRotatedEvent,
    SourceRevokedEvent,
    SourceThrottledEvent,
    SourceThrottleLiftedEvent,
)
from syn_domain.contexts.feedback.slices.feedback_sources.FeedbackSource import (
    FeedbackSource,
    SourceEvent,
)

if TYPE_CHECKING:
    from event_sourcing import (
        DispatchContext,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
        ProjectionStore,
    )

PROJECTION_NAME = "feedback_sources"

_EVENT_TYPES: dict[str, type[SourceEvent]] = {
    "SourceEnrolled": SourceEnrolledEvent,
    "SourceKeyRotated": SourceKeyRotatedEvent,
    "SourceThrottled": SourceThrottledEvent,
    "SourceThrottleLifted": SourceThrottleLiftedEvent,
    "SourceRevoked": SourceRevokedEvent,
}


class FeedbackSourcesProjection(CheckpointedProjection):
    """Builds ``feedback_sources`` from the Source streams."""

    VERSION = 1

    def __init__(self, store: ProjectionStore) -> None:
        self._store = store

    def get_name(self) -> str:
        return PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return set(_EVENT_TYPES)

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        event_class = _EVENT_TYPES.get(envelope.metadata.event_type or "")
        if event_class is None:
            return ProjectionResult.SKIP
        # The store may deliver a generic event; re-validating gives the typed one.
        event = event_class.model_validate(envelope.event.model_dump())
        await self._save(event)
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=PROJECTION_NAME,
                global_position=envelope.metadata.global_nonce or 0,
                updated_at=datetime.now(UTC),
                version=self.VERSION,
            )
        )
        return ProjectionResult.SUCCESS

    async def _save(self, event: SourceEvent) -> None:
        current = await self.get(event.source_id)
        if current is None:
            if not isinstance(event, SourceEnrolledEvent):
                return  # no stream starts without SourceEnrolled; nothing to update
            row = FeedbackSource.enrolled(event)
        else:
            row = current.apply(event)
        await self._store.save(PROJECTION_NAME, row.source_id, row.model_dump(mode="json"))

    async def get(self, source_id: str) -> FeedbackSource | None:
        data = await self._store.get(PROJECTION_NAME, source_id)
        return None if data is None else FeedbackSource.model_validate(data)

    async def get_all(self) -> list[FeedbackSource]:
        return [
            FeedbackSource.model_validate(d) for d in await self._store.get_all(PROJECTION_NAME)
        ]

    async def clear_all_data(self) -> None:
        await self._store.delete_all(PROJECTION_NAME)
