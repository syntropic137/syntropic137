"""list_installations returns every installation, however GitHub pages them."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from syn_adapters.github.client import GitHubAppError
from syn_adapters.github.client_endpoints import list_installations

pytestmark = pytest.mark.unit

_API = "https://api.github.com"


def _github(installations: int) -> httpx.MockTransport:
    """Serve GET /app/installations the way GitHub does.

    Pages default to 30 items, ``per_page`` is capped at 100, and every page
    but the last carries a ``Link: <...>; rel="next"`` header.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/app/installations"
        per_page = min(int(request.url.params.get("per_page", 30)), 100)
        page = int(request.url.params.get("page", 1))
        start = (page - 1) * per_page
        items = [{"id": i} for i in range(start, min(start + per_page, installations))]
        headers = {}
        if start + per_page < installations:
            headers["Link"] = (
                f'<{_API}/app/installations?per_page={per_page}&page={page + 1}>; rel="next", '
                f'<{_API}/app/installations?per_page={per_page}&page=999>; rel="last"'
            )
        return httpx.Response(200, json=items, headers=headers)

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport) -> MagicMock:
    client = MagicMock()
    client._generate_jwt.return_value = "jwt"
    client._http = httpx.AsyncClient(base_url=_API, transport=transport)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("installations", [0, 31, 250])
async def test_every_installation_is_returned(installations: int) -> None:
    result = await list_installations(_client(_github(installations)))
    assert [item["id"] for item in result] == list(range(installations))


@pytest.mark.asyncio
async def test_pages_beyond_the_safety_cap_raise_rather_than_truncate() -> None:
    """A truncated list would let a caller report the installations as complete."""
    with pytest.raises(GitHubAppError):
        await list_installations(_client(_github(100 * 50 + 1)))
