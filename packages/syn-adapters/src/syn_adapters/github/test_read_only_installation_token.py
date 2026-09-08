"""A phase that cannot push gets a token GitHub will not let it push with (#1161).

Three times a codex verify phase wrote the change it then certified and pushed
it to the PR branch. The control is the credential's SCOPE, so these tests
follow the scope to the two places it is consumed: the HTTP request that mints
the token, and the cache that decides whether an existing one is reused.

Run: pytest -m unit packages/syn-adapters/src/syn_adapters/github/test_read_only_installation_token.py -v
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from syn_adapters.github.client_token import (
    READ_ONLY_TOKEN_PERMISSIONS,
    get_installation_token,
    token_cache_key,
)

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _MintCall:
    """One request to the access-tokens endpoint, as it went out."""

    path: str
    headers: dict[str, str]
    json_body: dict[str, dict[str, str]] | None


class _RecordingHttp:
    """Captures the POST so the test can assert on the request itself."""

    def __init__(self, token: str = "ghs_minted") -> None:
        self.token = token
        self.calls: list[_MintCall] = []

    async def post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        json: dict[str, dict[str, str]] | None = None,
    ) -> MagicMock:
        self.calls.append(_MintCall(path=path, headers=headers, json_body=json))
        response = MagicMock()
        response.status_code = 201
        response.json.return_value = {
            "token": self.token,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "permissions": {"contents": "read"},
            "repository_selection": "all",
        }
        return response


def _client(http: _RecordingHttp) -> MagicMock:
    client = MagicMock()
    client._http = http
    client._cached_tokens = {}
    client._generate_jwt.return_value = "jwt"
    return client


@pytest.mark.asyncio
async def test_read_only_request_asks_github_to_withhold_write_permission() -> None:
    """The mint call must carry a permissions body, or the token can push.

    This is the whole control. Everything downstream - the credential file, the
    gh host entry, the clone - is byte-identical between the two scopes, so if
    this request goes out unrestricted nothing else in the system differs and
    the verify phase can push exactly as before.
    """
    http = _RecordingHttp()

    await get_installation_token(_client(http), "12345", read_only=True)

    assert len(http.calls) == 1
    body = http.calls[0].json_body
    assert body is not None
    permissions = body["permissions"]
    assert permissions == READ_ONLY_TOKEN_PERMISSIONS
    # Named explicitly rather than only compared to the constant: a future edit
    # that adds `contents: write` to that dict would satisfy the equality above
    # and hand every verify phase its push access back.
    assert permissions["contents"] == "read"
    assert "write" not in set(permissions.values())


@pytest.mark.asyncio
async def test_a_pushing_phase_sends_no_permissions_body_at_all() -> None:
    """`json=None`, not `json={}`.

    An empty permissions object is a request for NO permissions, so sending one
    by default would break every phase that legitimately pushes - the failure
    mode of v0.28.0-beta.5, arriving from the other direction.
    """
    http = _RecordingHttp()

    await get_installation_token(_client(http), "12345")

    assert http.calls[0].json_body is None


@pytest.mark.asyncio
async def test_a_pushing_phase_does_not_warm_the_cache_for_a_read_only_one() -> None:
    """The dangerous direction: read-write first, read-only second.

    Both phases resolve to the same installation. If scope were not part of the
    cache key, the second call would be served the FIRST token - a full-access
    credential - and every observable surface would look identical. That is the
    #1161 failure re-created inside the cache, so it is asserted on the token
    the second caller actually receives, not on the key.
    """
    http = _RecordingHttp(token="ghs_read_write")
    client = _client(http)

    pushing = await get_installation_token(client, "12345")
    assert pushing == "ghs_read_write"

    http.token = "ghs_read_only"
    verifying = await get_installation_token(client, "12345", read_only=True)

    assert verifying == "ghs_read_only"
    assert len(http.calls) == 2, "the read-only phase reused the read-write token"
    assert http.calls[1].json_body == {"permissions": READ_ONLY_TOKEN_PERMISSIONS}


@pytest.mark.asyncio
async def test_two_read_only_phases_share_one_token() -> None:
    """Scoping the key must not defeat caching within a scope."""
    http = _RecordingHttp()
    client = _client(http)

    await get_installation_token(client, "12345", read_only=True)
    await get_installation_token(client, "12345", read_only=True)

    assert len(http.calls) == 1


def test_cache_keys_of_different_scopes_never_collide() -> None:
    """Installation ids are integers, so the suffix cannot be forged into one."""
    assert token_cache_key("12345", read_only=False) != token_cache_key("12345", read_only=True)
