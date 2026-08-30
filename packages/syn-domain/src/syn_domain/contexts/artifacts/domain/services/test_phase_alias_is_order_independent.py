"""The flat phase alias must not depend on query ordering (#997).

`artifacts/input/<phase-id>.md` is chosen by two different code paths:
the live one (in-process cache, first file collected) and the cold one
(projection, after a restart). Production Postgres returns an unordered
query as ``updated_at DESC``, which is the LAST file collected -- so the
two paths disagree on the same execution, and only after a restart.

These tests model that ordering rather than trusting a fake that happens
to preserve insertion order.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)

_EARLIER = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 8, 29, 12, 0, 5, tzinfo=UTC)


def _artifact(
    artifact_id: str,
    content: str,
    created_at: datetime | str | None,
    *,
    is_primary: bool,
) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id,
        workflow_id="wf-1",
        execution_id="exec-1",
        session_id="sess-1",
        phase_id="research",
        artifact_type="markdown",
        name=f"{artifact_id}.md",
        created_at=created_at,
        content=content,
        is_primary_deliverable=is_primary,
    )


class _ProjectionReturning:
    """A projection that returns rows in a caller-chosen order."""

    def __init__(self, rows: list[ArtifactSummary]) -> None:
        self._rows = rows

    async def get_by_execution(self, execution_id: str) -> list[ArtifactSummary]:
        return list(self._rows)


@pytest.mark.unit
class TestColdPathIgnoresRowOrder:
    """The cold path must pick the primary deliverable, not row 0."""

    @pytest.mark.asyncio
    async def test_updated_at_desc_order_still_yields_the_first_collected_file(
        self,
    ) -> None:
        """Production returns B before A; the alias must still be A.

        A was collected first, so the live path injects it. If the cold
        path takes row 0 it injects B, and the next phase silently reads
        a different document after a restart.
        """
        deliverable = _artifact("z-earlier", "# Plan", _EARLIER, is_primary=True)
        secondary = _artifact("a-later", "review: ok", _LATER, is_primary=False)

        # updated_at DESC -> most recently written row first.
        service = ArtifactQueryService(_ProjectionReturning([secondary, deliverable]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_insertion_order_yields_the_same_answer(self) -> None:
        """The answer must not change with row order. Same data, order flipped."""
        deliverable = _artifact("z-earlier", "# Plan", _EARLIER, is_primary=True)
        secondary = _artifact("a-later", "review: ok", _LATER, is_primary=False)

        service = ArtifactQueryService(_ProjectionReturning([deliverable, secondary]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_legacy_rows_with_no_explicit_primary_fall_back_to_earliest(
        self,
    ) -> None:
        """Executions predating the flag have every row primary.

        Nothing can be back-filled, so the tiebreak must reproduce what
        the live path did at the time: the earliest-created row.
        """
        first = _artifact("z-earlier", "# Plan", _EARLIER, is_primary=True)
        second = _artifact("a-later", "review: ok", _LATER, is_primary=True)

        service = ArtifactQueryService(_ProjectionReturning([second, first]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"


@pytest.mark.unit
class TestTheFlagIsWhatDecides:
    """Isolate the flag from the timestamp tiebreak.

    In real data the primary is also the earliest-created, so a test where
    both agree passes even if the flag is ignored entirely. These force
    them to disagree, so only the flag can produce the expected answer.
    """

    @pytest.mark.asyncio
    async def test_primary_wins_even_when_it_was_created_last(self) -> None:
        late_primary = _artifact("z-primary", "# Plan", _LATER, is_primary=True)
        early_other = _artifact("a-secondary", "review: ok", _EARLIER, is_primary=False)

        service = ArtifactQueryService(_ProjectionReturning([early_other, late_primary]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_identical_timestamps_are_broken_by_the_flag(self) -> None:
        """Two files collected in the same loop can share a timestamp.

        The timestamp tiebreak cannot separate them, so the flag must.
        """
        primary = _artifact("z-primary", "# Plan", _EARLIER, is_primary=True)
        secondary = _artifact("a-secondary", "review: ok", _EARLIER, is_primary=False)

        service = ArtifactQueryService(_ProjectionReturning([secondary, primary]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"


@pytest.mark.unit
class TestTimestampsAreInstantsNotStrings:
    """ISO strings do not sort chronologically.

    `...T10:00:00+02:00` is 08:00Z and `...T09:00:00+00:00` is 09:00Z, but
    the first sorts LAST as a string because "10" > "09". Legacy rows are
    exactly where mixed offsets and formats live, which is exactly where
    the tiebreak is load-bearing.
    """

    @pytest.mark.asyncio
    async def test_a_later_wall_clock_in_a_different_offset_is_still_earlier(
        self,
    ) -> None:
        # 08:00Z -- the earlier instant, but the larger-looking string.
        earlier = _artifact("z-earlier", "# Plan", "2026-08-29T10:00:00+02:00", is_primary=True)
        # 09:00Z -- the later instant.
        later = _artifact("a-later", "review: ok", "2026-08-29T09:00:00+00:00", is_primary=True)

        service = ArtifactQueryService(_ProjectionReturning([later, earlier]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_a_space_separator_does_not_reorder(self) -> None:
        """`"2026-08-29 10:00..."` sorts before `"2026-08-29T09:00..."`
        as a string because " " < "T", inverting the real order."""
        earlier = _artifact("z-earlier", "# Plan", "2026-08-29 09:00:00+00:00", is_primary=True)
        later = _artifact("a-later", "review: ok", "2026-08-29T10:00:00+00:00", is_primary=True)

        service = ArtifactQueryService(_ProjectionReturning([later, earlier]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_rows_with_no_timestamp_still_resolve_the_same_way(self) -> None:
        """Two untimed rows must not fall back to row order."""
        a = _artifact("z-one", "# Plan", None, is_primary=True)
        b = _artifact("a-two", "review: ok", None, is_primary=True)

        forward = ArtifactQueryService(_ProjectionReturning([a, b]))
        reverse = ArtifactQueryService(_ProjectionReturning([b, a]))

        assert (await forward.get_for_phase_injection("exec-1", ["research"])) == (
            await reverse.get_for_phase_injection("exec-1", ["research"])
        )


@pytest.mark.unit
class TestEmptyContentIsNotADeliverable:
    """`CreateArtifactCommand` rejects empty content, the live cache skips
    it and the multi-file path skips it. The alias must agree, or a
    legacy row can win here and appear nowhere else."""

    @pytest.mark.asyncio
    async def test_an_empty_primary_does_not_win_over_real_content(self) -> None:
        empty_primary = _artifact("z-empty", "", _EARLIER, is_primary=True)
        real = _artifact("a-real", "# Plan", _LATER, is_primary=False)

        service = ArtifactQueryService(_ProjectionReturning([empty_primary, real]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"


@pytest.mark.unit
class TestTheTreeAgreesWithTheAlias:
    """Both cold-path readers must name the same artifact.

    `get_for_phase_injection` feeds `<phase-id>.md`; `get_files_for_phase_injection`
    (#988) feeds `<phase-id>/<source_path>`. `_tree_files()` dedups by
    destination path first-wins, so the LIST ORDER here decides which content
    the tree keeps. If the two disagree, a restart injects two different
    versions of one deliverable -- worse than either being wrong alone.
    """

    @pytest.mark.asyncio
    async def test_a_duplicated_source_path_resolves_the_same_way_in_both(
        self,
    ) -> None:
        earlier = _artifact("z-earlier", "# Plan", _EARLIER, is_primary=True)
        later = _artifact("a-later", "# Superseded", _LATER, is_primary=True)

        # updated_at DESC -> the later row arrives first.
        service = ArtifactQueryService(_ProjectionReturning([later, earlier]))

        alias = await service.get_for_phase_injection("exec-1", ["research"])
        tree = await service.get_files_for_phase_injection("exec-1", ["research"])

        # `_tree_files` keeps the first entry per destination path.
        assert tree["research"][0].content == alias["research"]

    @pytest.mark.asyncio
    async def test_the_tree_order_does_not_depend_on_row_order(self) -> None:
        earlier = _artifact("z-earlier", "# Plan", _EARLIER, is_primary=True)
        later = _artifact("a-later", "# Superseded", _LATER, is_primary=False)

        forward = ArtifactQueryService(_ProjectionReturning([earlier, later]))
        reverse = ArtifactQueryService(_ProjectionReturning([later, earlier]))

        a = await forward.get_files_for_phase_injection("exec-1", ["research"])
        b = await reverse.get_files_for_phase_injection("exec-1", ["research"])

        assert [f.content for f in a["research"]] == [f.content for f in b["research"]]
