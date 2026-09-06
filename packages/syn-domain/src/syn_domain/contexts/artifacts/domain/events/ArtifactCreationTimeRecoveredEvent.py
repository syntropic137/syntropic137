"""ArtifactCreationTimeRecovered - the creation time of an already-created artifact.

The fact this records is a RECOVERY, not a creation: someone read the artifact's
own append record out of the event store and is writing back the instant it
already showed. It is a separate event rather than a correction to
``ArtifactCreated`` because the event store is append-only by trigger - the row
cannot be edited - and because the two facts genuinely differ in provenance.
``created_at`` on v4+ ``ArtifactCreated`` was stamped by the aggregate at the
moment of creation; this one was read off the envelope afterwards, and
``recovered_from`` says which column it came from so a reader years later can
weigh it.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic needs it at runtime

from event_sourcing import DomainEvent, event


@event("ArtifactCreationTimeRecovered", "v1")
class ArtifactCreationTimeRecoveredEvent(DomainEvent):
    """Event emitted when a null ``created_at`` is filled from the artifact's own record.

    Only ever emitted for artifacts whose ``created_at`` is null - the aggregate
    refuses to emit it otherwise (#1215). So it can only ever ADD a date, never
    move one, which is what makes replaying it safe and the backfill re-runnable.
    """

    artifact_id: str

    created_at: datetime
    """The recovered instant. Not optional: an event that recovers nothing has
    nothing to record and must not be written."""

    recovered_from: str
    """Where the value was read - e.g. ``events.timestamp_unix_ms``.

    Provenance, kept because the alternative to a recovered date is a null, and
    a null is honest. Anyone auditing these rows needs to be able to tell a
    value read off the append record from one somebody inferred, without
    diffing a script that has since changed.
    """
