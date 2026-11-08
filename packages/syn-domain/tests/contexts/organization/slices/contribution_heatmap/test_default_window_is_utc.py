"""The default heatmap window is made of UTC days, whatever zone the host is in.

WHAT WENT WRONG (#1907)

``GetContributionHeatmapQuery`` defaulted its window to ``date.today()``, the
HOST's local day. Every day the heatmap returns is a UTC day (#1371), so on a
host behind UTC, between 00:00Z and local midnight, the window ended on the
previous UTC day and every session from the current UTC day was dropped. The
dashboard calls the endpoint with no dates, so it always takes that default.
CI runs in UTC and never saw it; a self-host in America/Los_Angeles did
(1992 of 2000 seeded sessions in test_dashboard_latency_budget.py).

HOW THIS FILE ASKS

The clock is frozen to 2030-01-15T00:05Z: five minutes into a UTC day that is
still 2030-01-14 in Los Angeles. One session is seeded on that UTC day, and
the result is read through ``GetContributionHeatmapHandler`` with a pool that
honours the ``day BETWEEN $1 AND $2`` bound the real SQL applies. So what is
asserted is what the dashboard would show, not a field on the query object.

The frozen instant is years from any real "today", so a default that still
read the real clock cannot pass by coincidence.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.organization.domain.queries import get_contribution_heatmap
from syn_domain.contexts.organization.domain.queries.get_contribution_heatmap import (
    GetContributionHeatmapQuery,
)
from syn_domain.contexts.organization.slices.conftest import (
    FakeProjectionStore,
    _make_projections,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.GetContributionHeatmapHandler import (
    GetContributionHeatmapHandler,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syn_domain.contexts.organization.domain.read_models.contribution_heatmap import (
        ContributionHeatmapResult,
    )

_NOW = datetime(2030, 1, 15, 0, 5, tzinfo=UTC)
_UTC_TODAY = date(2030, 1, 15)


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` is ``_NOW``, seen from whatever zone is asked."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FrozenDatetime:  # type: ignore[override]
        return cls.fromtimestamp(_NOW.timestamp(), tz)


@dataclass(frozen=True)
class _Row:
    """One rollup row in the shape asyncpg returns: a single session on ``day``."""

    day: date
    sessions: int = 1
    executions: int = 0
    commits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)


def _pool_with_session_on(day: date) -> MagicMock:
    """A pool holding one session on ``day``, bounded the way the SQL bounds it."""

    async def fetch(_sql: str, start: date, end: date, *_args: object) -> list[_Row]:
        return [_Row(day)] if start <= day <= end else []

    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=fetch)
    conn.execute = AsyncMock()
    conn.transaction = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False)
        )
    )
    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None)
        )
    )
    return pool


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    # raising=False: before #1907 the module had no `datetime` to replace, and
    # the test must then fail on its assertion, not on this line.
    monkeypatch.setattr(get_contribution_heatmap, "datetime", _FrozenDatetime, raising=False)


def _host_zone(zone: str) -> Iterator[None]:
    """Run as if the host's local zone were ``zone``, then put the real one back."""
    original = os.environ.get("TZ")
    os.environ["TZ"] = zone
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = original
        time.tzset()


@pytest.fixture
def host_behind_utc() -> Iterator[None]:
    yield from _host_zone("America/Los_Angeles")


@pytest.fixture
def host_in_utc() -> Iterator[None]:
    yield from _host_zone("UTC")


async def _heatmap(query: GetContributionHeatmapQuery) -> ContributionHeatmapResult:
    _, repo_proj = await _make_projections("sys-1", "Backend", "org-1", ["acme/api"])
    handler = GetContributionHeatmapHandler(
        pool=_pool_with_session_on(_UTC_TODAY),
        store=FakeProjectionStore(),
        repo_projection=repo_proj,
    )
    return await handler.handle(query)


@pytest.mark.unit
class TestDefaultWindowIsUtc:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("host_behind_utc", "frozen_clock")
    async def test_session_from_current_utc_day_is_counted_on_host_behind_utc(self) -> None:
        # The premise of the test: the host really is still on the previous day.
        assert time.localtime(_NOW.timestamp()).tm_mday == 14

        result = await _heatmap(GetContributionHeatmapQuery(metric="sessions"))

        assert result.end_date == "2030-01-15"
        assert result.start_date == "2029-01-15"
        assert result.total == 1.0

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("host_in_utc", "frozen_clock")
    async def test_default_window_is_unchanged_on_host_in_utc(self) -> None:
        defaulted = await _heatmap(GetContributionHeatmapQuery(metric="sessions"))
        explicit = await _heatmap(
            GetContributionHeatmapQuery(
                metric="sessions", start_date=date(2029, 1, 15), end_date=_UTC_TODAY
            )
        )

        assert defaulted == explicit
        assert defaulted.total == 1.0
