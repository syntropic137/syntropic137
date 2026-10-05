"""When did the running deployment go live? ``started_at`` on every build route.

The dashboard's version tooltip reads this to say "Deployed 2h ago". Asserted
on the serialized payload of the real routes, not on ``get_build_info()``,
because the way to lose it is one hop later: a ``BuildInfo`` that computes it
and a response that drops it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from syn_api import build_info
from syn_api.main import create_app

#: An instant no clock reading during this test could produce, so a payload
#: carrying it can only have come from the captured value.
PINNED = datetime(2031, 2, 3, 4, 5, 6, tzinfo=UTC)

BUILD_ROUTES = [
    pytest.param("/health", "build", id="health"),
    pytest.param("/version", None, id="version"),
]


@dataclass(frozen=True)
class _WireDeployTime:
    """The two deploy-time fields exactly as the route serialized them."""

    started_at: str
    started_at_display: str


async def _build_via(route: str, key: str | None) -> _WireDeployTime:
    """Read the fields off the wire, not off ``BuildInfo``, so a dropped key fails here."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(route)
    assert response.status_code == 200, response.text
    body = json.loads(response.text)
    build = body[key] if key else body
    return _WireDeployTime(
        started_at=build["started_at"], started_at_display=build["started_at_display"]
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("route", "key"), BUILD_ROUTES)
async def test_the_process_start_reaches_the_payload(
    monkeypatch: pytest.MonkeyPatch, route: str, key: str | None
) -> None:
    monkeypatch.setattr(build_info, "STARTED_AT", PINNED)

    build = await _build_via(route, key)

    assert isinstance(build.started_at, str)
    assert datetime.fromisoformat(build.started_at) == PINNED
    assert build.started_at_display == "2031-02-03 04:05 UTC"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("route", "key"), BUILD_ROUTES)
async def test_the_start_is_captured_once_not_per_request(route: str, key: str | None) -> None:
    """A per-request ``datetime.now()`` would also be a valid UTC timestamp.

    What tells them apart is that the deploy time does not move between
    requests, and that it is earlier than any request this test makes.
    """
    before_requests = datetime.now(UTC)

    first = await _build_via(route, key)
    second = await _build_via(route, key)

    assert first.started_at == second.started_at
    started = datetime.fromisoformat(first.started_at)
    assert started.tzinfo is not None
    assert started == build_info.STARTED_AT
    assert started < before_requests
