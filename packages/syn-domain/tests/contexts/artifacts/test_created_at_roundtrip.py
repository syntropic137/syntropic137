"""`created_at` on the write path and the recovery path (#1215).

A quarter of the artifact corpus has `created_at: null` and is therefore
invisible to every time-window query. Two separate questions follow, and this
file answers both on the hops that carry the value rather than on the objects
that hold it:

(d) can a NEW artifact still be written without one? No: it is DEFAULTED, not
    rejected. Nobody supplies it - `CreateArtifactCommand` has no such field -
    so there is no input to reject; the aggregate stamps `datetime.now(UTC)`
    unconditionally at the only place `ArtifactCreatedEvent` is constructed. A
    validator on the event would only fire if the aggregate stopped setting it,
    which is a different defect from the one that happened.

(e) can the historical rows be recovered? Only where the artifact's own record
    genuinely says so. The recovered value must survive as far as the read
    model, and a row with no source must stay null.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.artifacts import (
    ArtifactAggregate,
    ArtifactType,
    CreateArtifactCommand,
    RecoverArtifactCreationTimeCommand,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)

pytestmark = pytest.mark.unit

RECOVERED = datetime(2024, 3, 1, 9, 30, tzinfo=UTC)

#: What ``ArtifactSummary.to_dict`` emits, and what an ``ArtifactCreated``
#: payload carries for the fields these tests touch. Spelled concretely rather
#: than as an object-valued mapping so the assertions type-check against values.
type Row = dict[str, str | int | bool | None]


class _Store:
    """Minimal projection store: the rows the projection wrote."""

    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    async def save(self, _name: str, key: str, data: Row) -> None:
        self.rows[key] = data

    async def get(self, _name: str, key: str) -> Row | None:
        return self.rows.get(key)


def _created(**overrides: str) -> Row:
    """A pre-v4 ArtifactCreated payload: the key is ABSENT, as in the store."""
    payload: Row = {
        "artifact_id": "a1",
        "workflow_id": "wf-1",
        "artifact_type": "deliverable",
        "title": "Old artifact",
        "content": "x",
    }
    payload.update(overrides)
    return payload


def _emitted(artifact: ArtifactAggregate) -> list[object]:
    """The domain events an aggregate is holding, unwrapped from their envelopes."""
    return [envelope.event for envelope in artifact.get_uncommitted_events()]


async def _project(*events: tuple[str, Row]) -> _Store:
    store = _Store()
    projection = ArtifactListProjection(store)
    for name, payload in events:
        await getattr(projection, name)(payload)
    return store


# -- (d) the write path -------------------------------------------------------


def test_a_new_artifact_gets_a_creation_time_without_anyone_supplying_one():
    """Defaulted, not rejected - the caller is never asked, so there is nothing
    to reject. This is the hole that had to be closed before a backfill was
    worth doing; it was already closed by #920, and this pins it shut."""
    before = datetime.now(UTC)
    artifact = ArtifactAggregate()
    artifact.create_artifact(
        CreateArtifactCommand(
            workflow_id="wf-1",
            phase_id="implement",
            artifact_type=ArtifactType.CODE,
            content="# Output",
            title="Fresh",
        )
    )
    after = datetime.now(UTC)

    assert not hasattr(CreateArtifactCommand, "created_at"), (
        "if callers could supply it, 'defaulted' would no longer be the whole "
        "story and this file would owe a test for the value they can pass"
    )
    [event] = _emitted(artifact)
    assert event.created_at is not None
    assert before <= event.created_at <= after
    assert artifact.created_at == event.created_at


async def test_the_creation_time_reaches_the_read_model():
    """The named trap: a value set correctly and dropped one hop later. The
    aggregate stamping it means nothing if the projection does not read it."""
    artifact = ArtifactAggregate()
    artifact.create_artifact(
        CreateArtifactCommand(
            workflow_id="wf-1",
            phase_id="implement",
            artifact_type=ArtifactType.CODE,
            content="# Output",
            title="Fresh",
        )
    )
    [event] = _emitted(artifact)

    store = await _project(("on_artifact_created", event.model_dump(mode="json")))

    [row] = store.rows.values()
    assert row["created_at"], "the event states its time and the read model must keep it"


# -- (e) the recovery path ----------------------------------------------------


async def test_a_recovered_time_reaches_the_read_model():
    """End to end: undated row in, recovery event, dated row out.

    Through the projection, because that is what the list surfaces read. An
    event the store never applies leaves the 274 rows exactly as invisible as
    they were.
    """
    store = await _project(
        ("on_artifact_created", _created()),
        (
            "on_artifact_creation_time_recovered",
            {
                "artifact_id": "a1",
                "created_at": RECOVERED.isoformat(),
                "recovered_from": "events.timestamp_unix_ms",
            },
        ),
    )

    assert store.rows["a1"]["created_at"] == RECOVERED.isoformat()


async def test_a_row_with_no_derivable_source_stays_null():
    """No source, no event, no date. A fabricated timestamp is worse than a
    null, because null is honest and the window count now says how many."""
    store = await _project(("on_artifact_created", _created()))

    assert store.rows["a1"]["created_at"] is None


async def test_recovery_can_only_fill_a_null_never_move_a_real_date():
    """The rule that makes the backfill re-runnable, on the aggregate that owns
    it. Enforced here rather than in the script's WHERE clause: a second run, a
    concurrent run and a hand-issued command all have to hit the same guard."""
    artifact = ArtifactAggregate()
    artifact.create_artifact(
        CreateArtifactCommand(
            workflow_id="wf-1",
            phase_id="implement",
            artifact_type=ArtifactType.CODE,
            content="# Output",
            title="Fresh",
        )
    )
    real = artifact.created_at
    assert real is not None

    artifact.recover_creation_time(
        RecoverArtifactCreationTimeCommand(
            aggregate_id="a1",
            created_at=real - timedelta(days=400),
            recovered_from="events.timestamp_unix_ms",
        )
    )

    assert artifact.created_at == real
    assert len(_emitted(artifact)) == 1, (
        "an artifact that already states its creation time is the authority on "
        "it; recovery must emit nothing at all"
    )


async def test_the_projection_also_refuses_to_overwrite():
    """Second guard, on the replay side.

    The aggregate's rule protects what is APPENDED. A projection is rebuilt
    against whatever is already in the store, in whatever order, so it must
    reach the same answer without trusting that.
    """
    store = await _project(
        ("on_artifact_created", _created(created_at="2025-01-01T00:00:00+00:00")),
        (
            "on_artifact_creation_time_recovered",
            {
                "artifact_id": "a1",
                "created_at": RECOVERED.isoformat(),
                "recovered_from": "events.timestamp_unix_ms",
            },
        ),
    )

    assert store.rows["a1"]["created_at"] == "2025-01-01T00:00:00+00:00"
