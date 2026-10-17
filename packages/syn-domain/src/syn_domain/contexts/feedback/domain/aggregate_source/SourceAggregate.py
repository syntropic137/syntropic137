"""Source aggregate root: one enrolled deployment and its signing keys (ADR-076-feedback-ticketing).

Holds public verification keys only. The signing key stays on the source's
own Relay; nothing in this stream can sign a request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

from syn_domain.contexts.feedback._shared.value_objects import SourceKey, SourceStatus, rotate_keys
from syn_domain.contexts.feedback.domain.events import (
    SourceEnrolledEvent,
    SourceKeyRotatedEvent,
    SourceRevokedEvent,
    SourceThrottledEvent,
    SourceThrottleLiftedEvent,
)
from syn_domain.contexts.feedback.domain.RequestSignature import SourceCredentials

if TYPE_CHECKING:
    from syn_domain.contexts.feedback.domain.commands import (
        EnrollSourceCommand,
        LiftSourceThrottleCommand,
        RevokeSourceCommand,
        RotateSourceKeyCommand,
        ThrottleSourceCommand,
    )


@aggregate("Source")
class SourceAggregate(AggregateRoot["SourceEnrolledEvent"]):
    """A deployment allowed to sign feedback submissions.

    Enrolment retries and repeated throttle/lift/revoke are no-ops, as on
    Ticket: SourceGuard and the enrol CLI may both re-send after a crash.
    """

    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._status = SourceStatus.ACTIVE
        self._daily_quota = 0
        # Every key this source has ever held, current last. A key id is never reused.
        self._keys: tuple[SourceKey, ...] = ()

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def status(self) -> SourceStatus:
        return self._status

    @property
    def daily_quota(self) -> int:
        return self._daily_quota

    @property
    def current_key_id(self) -> str | None:
        return self._keys[-1].key_id if self._keys else None

    @property
    def credentials(self) -> SourceCredentials:
        return SourceCredentials(
            source_id=self._source_id,
            revoked=self._status is SourceStatus.REVOKED,
            keys=self._keys,
        )

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    @command_handler("EnrollSourceCommand")
    def enroll(self, command: EnrollSourceCommand) -> None:
        enrolled = self._keys[0] if self._keys else None
        if enrolled is not None and (enrolled.key_id, enrolled.verification_key) != (
            command.key_id,
            command.verification_key,
        ):
            msg = f"Source {self.id} is already enrolled with a different key"
            raise ValueError(msg)
        if self.id is not None:
            return  # a retry of the same enrolment: no-op success
        self._initialize(command.aggregate_id)
        self._apply(
            SourceEnrolledEvent(
                source_id=command.aggregate_id,
                key_id=command.key_id,
                verification_key=command.verification_key,
                daily_quota=command.daily_quota,
                enrolled_at=command.enrolled_at,
            )
        )

    @command_handler("RotateSourceKeyCommand")
    def rotate_key(self, command: RotateSourceKeyCommand) -> None:
        self._require_exists()
        if self._status is SourceStatus.REVOKED:
            msg = f"Cannot rotate the key of source {self.id}: it is revoked"
            raise ValueError(msg)
        if command.key_id == self.current_key_id:
            if self._keys[-1].verification_key != command.verification_key:
                # A key id names one key: the same id with other material is not a retry.
                msg = f"Key id {command.key_id} of source {self.id} already names a different key"
                raise ValueError(msg)
            return  # a retry of the rotation just applied
        if any(key.key_id == command.key_id for key in self._keys):
            msg = f"Key id {command.key_id} was already used by source {self.id}; key ids are never reused"
            raise ValueError(msg)
        self._apply(
            SourceKeyRotatedEvent(
                source_id=self._source_id,
                retired_key_id=self._keys[-1].key_id,
                key_id=command.key_id,
                verification_key=command.verification_key,
                rotated_at=command.rotated_at,
            )
        )

    @command_handler("ThrottleSourceCommand")
    def throttle(self, command: ThrottleSourceCommand) -> None:
        self._require_exists()
        if self._status is SourceStatus.REVOKED:
            msg = f"Cannot throttle source {self.id}: it is revoked"
            raise ValueError(msg)
        if self._status is SourceStatus.THROTTLED:
            return
        self._apply(SourceThrottledEvent(source_id=self._source_id, reason=command.reason))

    @command_handler("LiftSourceThrottleCommand")
    def lift_throttle(self, command: LiftSourceThrottleCommand) -> None:
        self._require_exists()
        if self._status is SourceStatus.REVOKED:
            msg = f"Cannot lift the throttle of source {self.id}: it is revoked"
            raise ValueError(msg)
        if self._status is not SourceStatus.THROTTLED:
            return
        self._apply(SourceThrottleLiftedEvent(source_id=self._source_id, by=command.by))

    @command_handler("RevokeSourceCommand")
    def revoke(self, command: RevokeSourceCommand) -> None:
        if self.id is None:
            msg = "Cannot revoke a source that is not enrolled"
            raise ValueError(msg)
        if self._status is SourceStatus.REVOKED:
            return
        self._apply(
            SourceRevokedEvent(source_id=self._source_id, by=command.by, reason=command.reason)
        )

    # =========================================================================
    # GUARDS
    # =========================================================================

    @property
    def _source_id(self) -> str:
        self._require_exists()
        return str(self.id)

    def _require_exists(self) -> None:
        if self.id is None:
            msg = "Source is not enrolled"
            raise ValueError(msg)

    # =========================================================================
    # EVENT SOURCING HANDLERS
    # =========================================================================

    @event_sourcing_handler("SourceEnrolled")
    def on_enrolled(self, event: SourceEnrolledEvent) -> None:
        self._daily_quota = event.daily_quota
        self._keys = (SourceKey(key_id=event.key_id, verification_key=event.verification_key),)

    @event_sourcing_handler("SourceKeyRotated")
    def on_key_rotated(self, event: SourceKeyRotatedEvent) -> None:
        self._keys = rotate_keys(
            self._keys,
            retired_key_id=event.retired_key_id,
            new_key=SourceKey(key_id=event.key_id, verification_key=event.verification_key),
            rotated_at=event.rotated_at,
        )

    @event_sourcing_handler("SourceThrottled")
    def on_throttled(self, _event: SourceThrottledEvent) -> None:
        self._status = SourceStatus.THROTTLED

    @event_sourcing_handler("SourceThrottleLifted")
    def on_throttle_lifted(self, _event: SourceThrottleLiftedEvent) -> None:
        self._status = SourceStatus.ACTIVE

    @event_sourcing_handler("SourceRevoked")
    def on_revoked(self, _event: SourceRevokedEvent) -> None:
        self._status = SourceStatus.REVOKED
