"""FeedbackSource: one enrolled Source as Intake sees it (ADR-076-feedback-ticketing).

The feedback_sources read model's row, and how one Source event changes it.
Public verification keys only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.feedback._shared.value_objects import (
    SourceKey,
    SourceStatus,
    rotate_keys,
)
from syn_domain.contexts.feedback.domain.events import (
    SourceEnrolledEvent,
    SourceKeyRotatedEvent,
    SourceRevokedEvent,
    SourceThrottledEvent,
    SourceThrottleLiftedEvent,
)
from syn_domain.contexts.feedback.domain.RequestSignature import SourceCredentials

SourceEvent = (
    SourceEnrolledEvent
    | SourceKeyRotatedEvent
    | SourceThrottledEvent
    | SourceThrottleLiftedEvent
    | SourceRevokedEvent
)


class FeedbackSource(BaseModel):
    """One enrolled Source as Intake sees it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    status: SourceStatus
    daily_quota: int = Field(gt=0)
    keys: tuple[SourceKey, ...]

    @property
    def credentials(self) -> SourceCredentials:
        return SourceCredentials(
            source_id=self.source_id,
            revoked=self.status is SourceStatus.REVOKED,
            keys=self.keys,
        )

    def apply(self, event: SourceEvent) -> FeedbackSource:
        """This row after ``event``. Enrolment is ``enrolled``; it never reaches here."""
        match event:
            case SourceKeyRotatedEvent():
                keys = rotate_keys(
                    self.keys,
                    retired_key_id=event.retired_key_id,
                    new_key=SourceKey(key_id=event.key_id, verification_key=event.verification_key),
                    rotated_at=event.rotated_at,
                )
                return self.model_copy(update={"keys": keys})
            case SourceThrottledEvent():
                return self.model_copy(update={"status": SourceStatus.THROTTLED})
            case SourceThrottleLiftedEvent():
                return self.model_copy(update={"status": SourceStatus.ACTIVE})
            case SourceRevokedEvent():
                return self.model_copy(update={"status": SourceStatus.REVOKED})
            case SourceEnrolledEvent():
                return self  # a redelivered enrolment changes nothing

    @classmethod
    def enrolled(cls, event: SourceEnrolledEvent) -> FeedbackSource:
        return cls(
            source_id=event.source_id,
            status=SourceStatus.ACTIVE,
            daily_quota=event.daily_quota,
            keys=(SourceKey(key_id=event.key_id, verification_key=event.verification_key),),
        )
