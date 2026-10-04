"""When did the running deployment go live? ``started_at`` on /version and /health.

The dashboard's version label shows this on hover, and refetches /version to
notice a new deploy while a tab is open. Both depend on the value being the
moment the PROCESS started, not the moment of the request, so the tests that
matter are: it reaches the wire on both routes, it does not move between
requests, and its display sibling is derived from it.

Asserted on the serialized payload through the real routes, for the same reason
as ``test_build_identity_over_http.py``: the likely failure is a value computed
correctly and dropped at ``get_build_info()`` or the response model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api import build_info
from syn_api.main import create_app
from syn_api.types import BuildInfo

#: A start time no clock read during the test could produce, so seeing it on
#: the wire proves the captured value was carried, not recomputed.
LIVE_SINCE = datetime(2026, 3, 1, 9, 30, 15, tzinfo=UTC)

BUILD_ROUTES = [
    pytest.param("/health", "build", id="health"),
    pytest.param("/version", None, id="version"),
]


async def _build_via(route: str, key: str | None) -> dict[str, object]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(route)
    assert response.status_code == 200, response.text
    body = json.loads(response.text)
    return body[key] if key else body


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("route", "key"), BUILD_ROUTES)
async def test_the_process_start_time_reaches_the_payload(
    monkeypatch: pytest.MonkeyPatch, route: str, key: str | None
) -> None:
    monkeypatch.setattr(build_info, "STARTED_AT", LIVE_SINCE)

    build = await _build_via(route, key)

    assert datetime.fromisoformat(str(build["started_at"])) == LIVE_SINCE
    assert build["started_at_display"] == "2026-03-01 09:30 UTC"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_started_at_is_captured_once_not_per_request() -> None:
    """Two requests, and two apps, a measurable time apart report one start time.

    A per-request clock read would make every refetch look like a fresh deploy,
    which is exactly the signal the dashboard uses to offer a reload.
    """
    first = await _build_via("/version", None)
    second = await _build_via("/version", None)

    assert first["started_at"] == second["started_at"]
    started = datetime.fromisoformat(str(first["started_at"]))
    assert started == build_info.STARTED_AT
    assert started.utcoffset() == timedelta(0)
    assert started <= datetime.now(UTC)


@pytest.mark.unit
def test_the_display_is_always_utc_whatever_zone_it_was_given() -> None:
    """The display says UTC, so it must BE UTC even for an offset-aware input."""
    plus_two = timezone(timedelta(hours=2))
    build = BuildInfo(version="1.0.0", started_at=datetime(2026, 3, 1, 11, 30, tzinfo=plus_two))

    assert build.started_at_display == "2026-03-01 09:30 UTC"
