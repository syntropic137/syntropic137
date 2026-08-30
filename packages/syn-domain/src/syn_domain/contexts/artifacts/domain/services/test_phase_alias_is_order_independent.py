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
    created_at: datetime,
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
        deliverable = _artifact("art-a", "# Plan", _EARLIER, is_primary=True)
        secondary = _artifact("art-b", "review: ok", _LATER, is_primary=False)

        # updated_at DESC -> most recently written row first.
        service = ArtifactQueryService(_ProjectionReturning([secondary, deliverable]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_insertion_order_yields_the_same_answer(self) -> None:
        """The answer must not change with row order. Same data, order flipped."""
        deliverable = _artifact("art-a", "# Plan", _EARLIER, is_primary=True)
        secondary = _artifact("art-b", "review: ok", _LATER, is_primary=False)

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
        first = _artifact("art-a", "# Plan", _EARLIER, is_primary=True)
        second = _artifact("art-b", "review: ok", _LATER, is_primary=True)

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
        late_primary = _artifact("art-a", "# Plan", _LATER, is_primary=True)
        early_other = _artifact("art-b", "review: ok", _EARLIER, is_primary=False)

        service = ArtifactQueryService(_ProjectionReturning([early_other, late_primary]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"

    @pytest.mark.asyncio
    async def test_identical_timestamps_are_broken_by_the_flag(self) -> None:
        """Two files collected in the same loop can share a timestamp.

        The timestamp tiebreak cannot separate them, so the flag must.
        """
        primary = _artifact("art-a", "# Plan", _EARLIER, is_primary=True)
        secondary = _artifact("art-b", "review: ok", _EARLIER, is_primary=False)

        service = ArtifactQueryService(_ProjectionReturning([secondary, primary]))

        outputs = await service.get_for_phase_injection("exec-1", ["research"])

        assert outputs["research"] == "# Plan"
