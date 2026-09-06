"""The backfill has to move the read model, and must not invent a date (#1215).

Two defects the first round of this work could not have caught, both the same
shape -- a step that reports success without the effect it claims:

1. ``_apply`` appended ``ArtifactCreationTimeRecovered``, returned ``True`` and
   printed a count, while the list the API serves still answered ``null``. The
   event had no entry in the projection dispatcher's handler map, so the write
   landed in the store and reached no reader. A migration whose effect is
   invisible to the surface it was written to fix has not run in any sense that
   matters, and asserting the append succeeded cannot tell the two apart.

2. "A row with no derivable source stays null" was asserted against a
   hand-authored projection payload, never against the script's own decision.
   It passed unchanged when ``_recover`` was mutated to return
   ``datetime.now(UTC)`` -- the one behaviour the issue forbids outright,
   because a fabricated date silently places an artifact in a window it does
   not belong to and nothing downstream can tell, whereas a null is honest and
   is now counted out loud.

So every test here drives the script's real functions and then reads the answer
back off ``list_artifacts`` -- the surface a client calls -- rather than off the
event store the script just wrote to.

NOT covered here: ``_read_candidates``, whose ``SELECT`` needs a live Postgres
and so cannot run under ``-m unit``. What is covered is every decision the
script makes about a row once it has been read.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projections.sync import sync_published_events_to_projections
from syn_adapters.storage import get_artifact_repository
from syn_api.routes.artifacts import list_artifacts
from syn_api.types import ArtifactSummary, Ok
from syn_domain.contexts.artifacts import ArtifactType, CreateArtifactCommand
from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
    ArtifactAggregate,
)
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
    ArtifactCreatedEvent,
)

if TYPE_CHECKING:
    from syn_domain.pagination import Page

# scripts/backfill is not a package and is not on pythonpath; the sibling
# script tests reach their subject the same way.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backfill"))

from backfill_artifact_created_at import _apply, _Candidate, _recover

pytestmark = pytest.mark.unit

#: The instant the append record carries for the seeded row, and therefore the
#: instant a correct recovery must produce. Far enough in the past that it could
#: not be confused with a fabricated "now".
APPENDED_AT = datetime(2024, 3, 1, 9, 30, tzinfo=UTC)
APPENDED_MS = int(APPENDED_AT.timestamp() * 1000)


async def _seed_undated_artifact(artifact_id: str) -> None:
    """Write an artifact as the store actually holds the 274 of them.

    Their ``ArtifactCreated`` predates v4 (#920), so the event states no time at
    all. No command can produce that any more -- ``create_artifact`` stamps
    ``datetime.now(UTC)`` unconditionally, which is the hole #920 closed -- so
    the event is applied directly. That is the point: the fixture value could
    not have arisen from today's write path, only from history.
    """
    artifact = ArtifactAggregate()
    artifact._initialize(artifact_id)
    artifact._apply(
        ArtifactCreatedEvent(
            artifact_id=artifact_id,
            workflow_id="wf-1",
            phase_id="implement",
            artifact_type=ArtifactType.CODE,
            content_type="text/markdown",
            content="# Old output",
            content_hash="deadbeef",
            size_bytes=12,
            title="Written before v4",
            created_at=None,
        )
    )
    await get_artifact_repository().save_new(artifact)
    await sync_published_events_to_projections()


async def _create_artifact_normally(artifact_id: str) -> None:
    """An artifact written by today's write path, which stamps its own date."""
    artifact = ArtifactAggregate()
    artifact.create_artifact(
        CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id="wf-1",
            phase_id="implement",
            artifact_type=ArtifactType.CODE,
            content="# Fresh",
            title="Written today",
        )
    )
    await get_artifact_repository().save_new(artifact)
    await sync_published_events_to_projections()


async def _page(**query: object) -> Page[ArtifactSummary]:
    """One page of the list ``GET /artifacts`` serves.

    Deliberately the list surface and not ``repository.get_by_id``: the event
    store holding the value is exactly the state that looked like success while
    every client still saw ``null``.
    """
    result = await list_artifacts(workflow_id="wf-1", **query)  # type: ignore[arg-type]  # kwargs forwarded to a typed signature
    assert isinstance(result, Ok), result
    return result.value


async def _created_at_on_the_list(artifact_id: str) -> datetime | None:
    """What the list reports for one artifact, or None if it is still undated."""
    [row] = [a for a in (await _page(limit=100)).rows if a.id == artifact_id]
    return row.created_at


async def test_a_recovered_date_reaches_the_list_the_api_serves():
    """The whole point of the migration, asserted where a client would see it.

    Fails if the recovery event reaches the store but not the dispatcher --
    which is what it did.
    """
    await _seed_undated_artifact("a1")
    assert await _created_at_on_the_list("a1") is None, "fixture must start undated"

    written, skipped = await _apply([_recover("a1", APPENDED_MS, None)])

    assert (written, skipped) == (1, 0)
    on_the_list = await _created_at_on_the_list("a1")
    assert on_the_list is not None, (
        "the append succeeded and the read model did not move -- this is the "
        "defect, not evidence against it"
    )
    assert on_the_list == APPENDED_AT


async def test_a_recovered_artifact_enters_the_window_it_belongs_to():
    """Undated rows are excluded from every bounded window, so a recovery that
    does not reach the read model leaves the artifact exactly as invisible as
    it was. The count of what a window could not judge must drop by one, and
    the row must appear -- in the window its append record puts it in, not the
    window it would land in if someone stamped it "now"."""
    await _seed_undated_artifact("a1")

    window = {"created_after": APPENDED_AT - timedelta(days=1)}

    before = await _page(**window)
    assert before.rows == []
    assert before.total == 0
    assert before.excluded_undated == 1

    await _apply([_recover("a1", APPENDED_MS, None)])

    after = await _page(**window)
    assert [a.id for a in after.rows] == ["a1"]
    assert after.total == 1
    assert after.excluded_undated == 0


async def test_a_recovered_row_and_a_normal_row_can_be_listed_together():
    """The list has to be able to ORDER what the backfill wrote.

    A projection handler that assigned the payload's ``created_at`` straight
    into the stored row left recovered rows holding a ``datetime`` while every
    row written by ``on_artifact_created`` holds the ISO string ``to_dict``
    produces -- ``model_dump()`` is what a dispatcher hands a projection, not
    JSON. One of each in the same collection is all it takes: ordering them
    raised ``TypeError`` and GET /artifacts answered 500 for every caller,
    after the migration had reported success. So this lists a backfilled row
    beside an ordinary one, which is the state production is in the moment the
    migration touches its first artifact.
    """
    await _seed_undated_artifact("a1")
    await _create_artifact_normally("a2")

    await _apply([_recover("a1", APPENDED_MS, None)])

    rows = (await _page(limit=100)).rows
    assert [a.id for a in rows] == ["a2", "a1"], (
        "newest first: the recovered row is from 2024 and the other was made "
        "just now, and both have to be comparable for that to be answerable"
    )


async def test_an_artifact_with_no_derivable_source_is_left_null():
    """The rule the issue is emphatic about, asserted on the resulting value.

    ``timestamp_unix_ms`` carries ``DEFAULT 0``, so a zero is the absence of a
    time wearing a date, not 1970. With no second source either there is
    nothing to recover, and a fabricated date is worse than the null: null is
    honest and visibly excluded from window queries, an invented one silently
    places the artifact in a window it does not belong to.

    This drives ``_recover`` and ``_apply`` -- the script's own decision and its
    own write -- so mutating either to fabricate a timestamp fails it. The
    previous version asserted a hand-built payload against the projection and
    passed with the fabrication in place.
    """
    await _seed_undated_artifact("a1")

    candidate = _recover("a1", 0, 0)
    written, skipped = await _apply([candidate])

    # The read model first, deliberately. It is the assertion the defect has to
    # get past, and putting it behind the check on _recover would let the one
    # that matters be shadowed by the one that is easy.
    assert await _created_at_on_the_list("a1") is None, (
        "the artifact now carries a date no record of it states"
    )
    assert candidate.when is None, (
        "no append time and no recorded time is unrecoverable; any date here was invented"
    )
    assert (written, skipped) == (0, 0), "nothing to write, and nothing skipped as already-dated"


async def test_the_recorded_time_is_used_only_as_a_second_choice_and_says_so():
    """When the append record is empty but the store's accept time is not, that
    is the nearest true statement available -- recorded AS the accept time, in
    ``recovered_from``, rather than passed off as the event's own. Provenance is
    the whole reason a recovered date is trustworthy at all."""
    recorded = APPENDED_AT + timedelta(hours=2)

    assert _recover("a1", APPENDED_MS, int(recorded.timestamp() * 1000)) == _Candidate(
        "a1", APPENDED_AT, "events.timestamp_unix_ms"
    )
    assert _recover("a1", 0, int(recorded.timestamp() * 1000)) == _Candidate(
        "a1", recorded, "events.recorded_time_unix_ms"
    )


async def test_a_second_run_writes_nothing_and_moves_nothing():
    """Re-runnable, asserted through the read model rather than through the
    return value. An idempotent migration that reports "0 written" while the
    date shifts underneath it would satisfy the counter and fail the promise."""
    await _seed_undated_artifact("a1")
    candidate = _recover("a1", APPENDED_MS, None)

    await _apply([candidate])
    first = await _created_at_on_the_list("a1")

    written, skipped = await _apply([candidate])

    assert (written, skipped) == (0, 1), "the second run must recognise the row as already dated"
    assert await _created_at_on_the_list("a1") == first


async def test_recovery_cannot_displace_a_date_the_artifact_already_states():
    """The guard that makes a re-run safe, driven from the script rather than
    from the aggregate: an artifact created today already states its time, and
    the backfill must not move it even when handed a different one."""
    await _create_artifact_normally("a2")
    real = await _created_at_on_the_list("a2")
    assert real is not None

    written, skipped = await _apply([_recover("a2", APPENDED_MS, None)])

    assert (written, skipped) == (0, 1)
    assert await _created_at_on_the_list("a2") == real
