"""Source aggregate and signed-request verification: the PR 2 acceptance rows of the feedback plan (#1970, #2010).

Revocation and rotation are asserted on credentials read back from the
feedback_sources projection after it consumed the events the aggregate
emitted, because that row is what Intake verifies against. A key that is
retired correctly on the aggregate and dropped one hop later would pass every
test that stopped at the aggregate.

Test keys are derived from public labels (``sha256(b"syn-feedback-test-key-a")``).
They are not secrets and sign nothing outside this file.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from event_sourcing import (
    DomainEvent,
    EventEnvelope,
    MemoryCheckpointStore,
    MemoryProjectionStore,
    ProjectionCheckpoint,
)

from syn_domain.contexts.feedback import (
    Ed25519Signatures,
    EnrollSourceCommand,
    FeedbackSourcesProjection,
    LiftSourceThrottleCommand,
    RevokeSourceCommand,
    RotateSourceKeyCommand,
    SignatureVerifier,
    SignedRequest,
    SourceAggregate,
    SourceCredentials,
    SourceStatus,
    ThrottleSourceCommand,
    Verification,
    canonical_string,
)

pytestmark = pytest.mark.unit

SOURCE = "inst-0192a3b4-test"
SEED_A = hashlib.sha256(b"syn-feedback-test-key-a").digest()
SEED_B = hashlib.sha256(b"syn-feedback-test-key-b").digest()
PUBLIC_A = "iL8HsalXLERnkvSr5oG7VavzohRuqi6wVWuYcKMykTc="
PUBLIC_B = "pxpaJHHNS035xrimbLHj4c/65Z+5fdIhh4xPLvbQvKM="
PUBLIC_C = "CEhiji0Bd2FU+bo2kqlvGfXw+SO14ev2GripDw4MIEU="  # from sha256(b"syn-feedback-test-key-c")
OVERLAP = timedelta(hours=24)

T0 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
TS0 = 1792238400  # T0 as Unix seconds
BODY = b'{"comment":"the save button does nothing"}'
NONCE = "0192a3b4-0000-7000-8000-00000000n001"
PATH = "/intake/v1/submissions"

#: Ed25519 over the canonical string of (POST, PATH, TS0, NONCE, BODY) with key A.
#: Pinned, so a change to the canonical string's format fails here, not in production.
FIXED_SIGNATURE = (
    "V5xpayHvuWzU+0bnQ+OO7zbd4muAU3Dg6tqxlgVa50wj2uuIvRFnECMaSF1S7OiVSSkIhb0ZU/K01PYJqYymBg=="
)

ED25519 = Ed25519Signatures()
VERIFIER = SignatureVerifier(ED25519, rotation_overlap=OVERLAP)


def _signed(
    *, seed: bytes = SEED_A, key_id: str = "key-a", timestamp: int = TS0, body: bytes = BODY
) -> SignedRequest:
    message = canonical_string(
        method="POST", path=PATH, timestamp=timestamp, nonce=NONCE, body=body
    )
    return SignedRequest(
        method="POST",
        path=PATH,
        timestamp=timestamp,
        nonce=NONCE,
        body=body,
        key_id=key_id,
        signature=ED25519.sign(seed, message),
    )


class _Source:
    """A Source stream, reloaded before every command, and the projection fed from it."""

    def __init__(self) -> None:
        self.history: list[EventEnvelope[DomainEvent]] = []

    def run(self, *commands: object) -> _Source:
        for command in commands:
            source = self.load()
            source._handle_command(command)  # ESP's own dispatch, by command class name
            self.history.extend(source.get_uncommitted_events())
        return self

    def load(self) -> SourceAggregate:
        source = SourceAggregate()
        if self.history:
            source.rehydrate(self.history)
        return source

    def stored(self) -> list[EventEnvelope[DomainEvent]]:
        """The stream as the real store hands it back: JSON round-tripped, type stamped.

        Same transform as ``syn_domain.testing.stored_replay``, which reads from a
        memory client this test does not need.
        """
        return [
            envelope.model_copy(
                update={
                    "event": type(envelope.event).model_validate_json(
                        envelope.event.model_dump_json()
                    ),
                    "metadata": envelope.metadata.model_copy(
                        update={"event_type": envelope.event.event_type}
                    ),
                }
            )
            for envelope in self.history
        ]

    async def projected(self) -> SourceCredentials:
        projection = FeedbackSourcesProjection(MemoryProjectionStore())
        checkpoints = MemoryCheckpointStore()
        for envelope in self.stored():
            await projection.handle_event(envelope, checkpoints)
        row = await projection.get(SOURCE)
        assert row is not None
        return row.credentials


def _enroll() -> EnrollSourceCommand:
    return EnrollSourceCommand(
        aggregate_id=SOURCE,
        key_id="key-a",
        verification_key=PUBLIC_A,
        daily_quota=200,
        enrolled_at=T0 - timedelta(days=30),
    )


def _rotate(at: datetime = T0) -> RotateSourceKeyCommand:
    return RotateSourceKeyCommand(
        aggregate_id=SOURCE, key_id="key-b", verification_key=PUBLIC_B, rotated_at=at
    )


def _rotate_to_c(at: datetime = T0 + timedelta(hours=1)) -> RotateSourceKeyCommand:
    return RotateSourceKeyCommand(
        aggregate_id=SOURCE, key_id="key-c", verification_key=PUBLIC_C, rotated_at=at
    )


def _revoke() -> RevokeSourceCommand:
    return RevokeSourceCommand(aggregate_id=SOURCE, by="owner", reason="decommissioned")


def _enrolled_credentials() -> SourceCredentials:
    return _Source().run(_enroll()).load().credentials


class TestCanonicalSignature:
    def test_the_fixed_vector_verifies(self) -> None:
        request = SignedRequest(
            method="POST",
            path=PATH,
            timestamp=TS0,
            nonce=NONCE,
            body=BODY,
            key_id="key-a",
            signature=FIXED_SIGNATURE,
        )
        assert VERIFIER.verify(request, _enrolled_credentials(), now=T0) is Verification.VERIFIED

    def test_the_fixed_vector_is_what_the_signer_produces(self) -> None:
        assert _signed().signature == FIXED_SIGNATURE

    def test_a_one_byte_body_change_fails(self) -> None:
        tampered = _signed().model_copy(update={"body": BODY.replace(b"save", b"sbve")})
        assert len(tampered.body) == len(BODY)
        assert (
            VERIFIER.verify(tampered, _enrolled_credentials(), now=T0) is Verification.BAD_SIGNATURE
        )

    def test_a_tampered_timestamp_inside_the_window_fails(self) -> None:
        # Re-dating a captured request by a minute keeps it inside the window,
        # so only the signature can catch it.
        tampered = _signed().model_copy(update={"timestamp": TS0 + 60})
        assert (
            VERIFIER.verify(tampered, _enrolled_credentials(), now=T0) is Verification.BAD_SIGNATURE
        )

    def test_a_tampered_nonce_fails(self) -> None:
        tampered = _signed().model_copy(update={"nonce": "0192a3b4-0000-7000-8000-00000000n002"})
        assert (
            VERIFIER.verify(tampered, _enrolled_credentials(), now=T0) is Verification.BAD_SIGNATURE
        )

    def test_a_signature_by_another_key_fails(self) -> None:
        forged = _signed(seed=SEED_B, key_id="key-a")
        assert (
            VERIFIER.verify(forged, _enrolled_credentials(), now=T0) is Verification.BAD_SIGNATURE
        )

    def test_a_malformed_signature_is_refused_not_raised(self) -> None:
        garbled = _signed().model_copy(update={"signature": "not base64!"})
        assert (
            VERIFIER.verify(garbled, _enrolled_credentials(), now=T0) is Verification.BAD_SIGNATURE
        )

    def test_an_unknown_key_id_fails(self) -> None:
        request = _signed(key_id="key-z")
        assert VERIFIER.verify(request, _enrolled_credentials(), now=T0) is Verification.UNKNOWN_KEY


class TestTimestampWindow:
    @pytest.mark.parametrize("skew", [-300, 300])
    def test_300_seconds_either_side_verifies(self, skew: int) -> None:
        request = _signed(timestamp=TS0 + skew)
        assert VERIFIER.verify(request, _enrolled_credentials(), now=T0) is Verification.VERIFIED

    @pytest.mark.parametrize("skew", [-301, 301])
    def test_301_seconds_either_side_fails(self, skew: int) -> None:
        request = _signed(timestamp=TS0 + skew)
        assert (
            VERIFIER.verify(request, _enrolled_credentials(), now=T0)
            is Verification.STALE_TIMESTAMP
        )

    @pytest.mark.parametrize("timestamp", [253402300800, -62135596801, 10**30, -(10**30)])
    def test_a_timestamp_no_datetime_can_hold_is_refused_not_raised(self, timestamp: int) -> None:
        # Past year 9999, before year 1, and past what a float holds: the header
        # is the sender's, so every integer must get a verdict, never an exception.
        request = _signed(timestamp=timestamp)
        assert (
            VERIFIER.verify(request, _enrolled_credentials(), now=T0)
            is Verification.STALE_TIMESTAMP
        )


class TestRevocation:
    async def test_a_revoked_source_fails_with_a_valid_signature(self) -> None:
        credentials = await _Source().run(_enroll(), _revoke()).projected()
        assert VERIFIER.verify(_signed(), credentials, now=T0) is Verification.REVOKED

    async def test_revocation_outranks_the_rotation_overlap(self) -> None:
        credentials = await _Source().run(_enroll(), _rotate(), _revoke()).projected()
        old_key = _signed()
        assert (
            VERIFIER.verify(old_key, credentials, now=T0 + timedelta(hours=1))
            is Verification.REVOKED
        )

    async def test_the_same_source_verifies_before_revocation(self) -> None:
        credentials = await _Source().run(_enroll()).projected()
        assert VERIFIER.verify(_signed(), credentials, now=T0) is Verification.VERIFIED


class TestRotation:
    async def test_the_old_key_passes_inside_the_overlap(self) -> None:
        credentials = await _Source().run(_enroll(), _rotate(at=T0)).projected()
        now = T0 + OVERLAP - timedelta(seconds=1)
        request = _signed(timestamp=int(now.timestamp()))
        assert VERIFIER.verify(request, credentials, now=now) is Verification.VERIFIED

    async def test_the_old_key_fails_after_the_overlap(self) -> None:
        credentials = await _Source().run(_enroll(), _rotate(at=T0)).projected()
        now = T0 + OVERLAP
        request = _signed(timestamp=int(now.timestamp()))
        assert VERIFIER.verify(request, credentials, now=now) is Verification.KEY_RETIRED

    async def test_the_new_key_passes_after_the_overlap(self) -> None:
        credentials = await _Source().run(_enroll(), _rotate(at=T0)).projected()
        now = T0 + OVERLAP + timedelta(days=1)
        request = _signed(seed=SEED_B, key_id="key-b", timestamp=int(now.timestamp()))
        assert VERIFIER.verify(request, credentials, now=now) is Verification.VERIFIED

    async def test_the_projection_and_the_aggregate_agree(self) -> None:
        stream = _Source().run(_enroll(), _rotate(at=T0))
        assert await stream.projected() == stream.load().credentials


class _CheckpointWriteFails(MemoryCheckpointStore):
    """Saves no checkpoint while ``failing``: the row is written and the checkpoint is not."""

    failing = False

    async def save_checkpoint(self, checkpoint: ProjectionCheckpoint) -> None:
        if self.failing:
            raise OSError("checkpoint write interrupted")
        await super().save_checkpoint(checkpoint)


class TestRedelivery:
    """A projection is handed an event again when its checkpoint did not save; the row must not move."""

    async def _projected(
        self, stream: _Source
    ) -> tuple[FeedbackSourcesProjection, MemoryCheckpointStore]:
        projection = FeedbackSourcesProjection(MemoryProjectionStore())
        checkpoints = MemoryCheckpointStore()
        for envelope in stream.stored():
            await projection.handle_event(envelope, checkpoints)
        return projection, checkpoints

    async def test_a_redelivered_rotation_leaves_the_row_unchanged(self) -> None:
        stream = _Source().run(_enroll(), _rotate())
        projection, checkpoints = await self._projected(stream)
        before = await projection.get(SOURCE)
        await projection.handle_event(stream.stored()[-1], checkpoints)
        after = await projection.get(SOURCE)
        assert after == before
        assert after is not None
        assert [key.key_id for key in after.keys] == ["key-a", "key-b"]

    async def test_an_older_rotation_redelivered_keeps_the_later_retirement(self) -> None:
        stream = _Source().run(_enroll(), _rotate(), _rotate_to_c())
        projection, checkpoints = await self._projected(stream)
        before = await projection.get(SOURCE)
        await projection.handle_event(stream.stored()[1], checkpoints)  # A -> B, again
        after = await projection.get(SOURCE)
        assert after == before
        assert after is not None
        assert [key.key_id for key in after.keys] == ["key-a", "key-b", "key-c"]
        assert after.keys[1].retired_at == T0 + timedelta(hours=1)

    async def test_a_rotation_retried_after_its_checkpoint_failed_is_applied_once(self) -> None:
        stream = _Source().run(_enroll(), _rotate())
        enrolment, rotation = stream.stored()
        projection = FeedbackSourcesProjection(MemoryProjectionStore())
        checkpoints = _CheckpointWriteFails()
        await projection.handle_event(enrolment, checkpoints)
        after_enrolment = await checkpoints.get_checkpoint("feedback_sources")
        checkpoints.failing = True
        with pytest.raises(OSError, match="checkpoint write interrupted"):
            await projection.handle_event(rotation, checkpoints)
        # The row has the rotation; the checkpoint does not, so the rotation comes again.
        assert await checkpoints.get_checkpoint("feedback_sources") == after_enrolment
        saved = await projection.get(SOURCE)
        assert saved is not None
        assert [key.key_id for key in saved.keys] == ["key-a", "key-b"]
        checkpoints.failing = False
        await projection.handle_event(rotation, checkpoints)  # the coordinator's retry
        retried = await projection.get(SOURCE)
        assert retried == saved
        assert retried is not None
        assert [key.key_id for key in retried.keys] == ["key-a", "key-b"]
        assert retried.credentials == stream.load().credentials


class TestSourceAggregate:
    def test_enrolling_twice_with_the_same_key_is_a_no_op(self) -> None:
        stream = _Source().run(_enroll(), _enroll())
        assert len(stream.history) == 1

    def test_enrolling_again_with_a_different_key_raises(self) -> None:
        other = _enroll().model_copy(update={"key_id": "key-other"})
        with pytest.raises(ValueError, match="different key"):
            _Source().run(_enroll(), other)

    def test_enrolling_again_with_the_same_key_id_and_other_material_raises(self) -> None:
        other = EnrollSourceCommand.model_validate(
            {**_enroll().model_dump(mode="json"), "verification_key": PUBLIC_B}
        )
        stream = _Source().run(_enroll())
        with pytest.raises(ValueError, match="different key"):
            stream.run(other)
        assert len(stream.history) == 1

    def test_a_retried_enrolment_after_a_rotation_is_a_no_op(self) -> None:
        stream = _Source().run(_enroll(), _rotate(), _enroll())
        assert len(stream.history) == 2

    def test_a_retried_rotation_is_a_no_op(self) -> None:
        stream = _Source().run(_enroll(), _rotate(), _rotate())
        assert len(stream.history) == 2

    def test_rotating_to_the_current_key_id_with_other_material_raises(self) -> None:
        other = RotateSourceKeyCommand.model_validate(
            {**_rotate().model_dump(mode="json"), "verification_key": PUBLIC_C}
        )
        stream = _Source().run(_enroll(), _rotate())
        with pytest.raises(ValueError, match="different key"):
            stream.run(other)
        assert len(stream.history) == 2
        assert stream.load().credentials.keys[-1].verification_key == PUBLIC_B

    def test_a_key_id_is_never_reused(self) -> None:
        back_to_a = RotateSourceKeyCommand(
            aggregate_id=SOURCE, key_id="key-a", verification_key=PUBLIC_A, rotated_at=T0
        )
        with pytest.raises(ValueError, match="never reused"):
            _Source().run(_enroll(), _rotate(), back_to_a)

    def test_a_revoked_source_cannot_rotate_or_be_throttled(self) -> None:
        stream = _Source().run(_enroll(), _revoke())
        with pytest.raises(ValueError, match="revoked"):
            stream.run(_rotate())
        with pytest.raises(ValueError, match="revoked"):
            stream.run(ThrottleSourceCommand(aggregate_id=SOURCE, reason="spam"))

    async def test_throttle_and_lift_reach_the_projection(self) -> None:
        stream = _Source().run(_enroll(), ThrottleSourceCommand(aggregate_id=SOURCE, reason="spam"))
        assert stream.load().status is SourceStatus.THROTTLED
        projection = FeedbackSourcesProjection(MemoryProjectionStore())
        checkpoints = MemoryCheckpointStore()
        for envelope in stream.stored():
            await projection.handle_event(envelope, checkpoints)
        row = await projection.get(SOURCE)
        assert row is not None
        assert row.status is SourceStatus.THROTTLED
        stream.run(LiftSourceThrottleCommand(aggregate_id=SOURCE, by="owner"))
        await projection.handle_event(stream.stored()[-1], checkpoints)
        row = await projection.get(SOURCE)
        assert row is not None
        assert row.status is SourceStatus.ACTIVE

    def test_commands_on_an_unenrolled_source_raise(self) -> None:
        with pytest.raises(ValueError, match="not enrolled"):
            _Source().run(_revoke())
