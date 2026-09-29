"""What an installation token request says, and how a token is ended (#725).

A token minted with no ``repositories`` reaches EVERY repository the
installation covers. A workspace provisioned for one repository was holding a
credential for all of them, for an hour, with nothing able to end it early.
So the request names the repositories, the cache keys on them (a token for one
repo set must never be handed out for another), and a token can be revoked
with ``DELETE /installation/token``, authenticated by the token itself.

What these assert is what went on the wire, because that is the only thing
GitHub reads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from syn_adapters.github.agent_token import mint_agent_token
from syn_adapters.github.client import GitHubAuthError
from syn_adapters.github.client_token import (
    TokenRequest,
    installation_token,
    revoke_installation_token,
)

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient, InstallationToken

pytestmark = pytest.mark.unit

_GRANTED = {"contents": "write", "pull_requests": "write", "metadata": "read"}


class _FakeHttp:
    """Records every request, and answers as GitHub does."""

    def __init__(self, *, revocation_status: int = 204) -> None:
        self.token_requests: list[TokenRequest | None] = []
        self.deletes: list[tuple[str, str]] = []
        self._revocation_status = revocation_status

    async def get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(
            200, json={"id": 42, "permissions": _GRANTED}, request=httpx.Request("GET", path)
        )

    async def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        json: dict[str, dict[str, str] | list[str]] | None = None,
    ) -> httpx.Response:
        self.token_requests.append(None if json is None else TokenRequest.model_validate(json))
        expires = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={
                "token": f"ghs_{len(self.token_requests)}",
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
                "permissions": _GRANTED,
                "repository_selection": "selected",
            },
            request=httpx.Request("POST", path),
        )

    async def delete(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        self.deletes.append((path, (headers or {}).get("Authorization", "")))
        return httpx.Response(self._revocation_status, request=httpx.Request("DELETE", path))


class _FakeClient:
    def __init__(self, http: _FakeHttp) -> None:
        self._http = http
        self._cached_tokens: dict[str, InstallationToken] = {}

    def _generate_jwt(self) -> str:
        return "jwt-for-tests"


def _client(http: _FakeHttp) -> GitHubAppClient:
    return cast("GitHubAppClient", _FakeClient(http))


class TestTheRequestNamesTheRepositories:
    async def test_an_agent_token_is_requested_for_the_named_repositories_only(self) -> None:
        http = _FakeHttp()

        await mint_agent_token(
            _client(http), "42", can_open_pr=False, repositories=["repo-b", "repo-a"]
        )

        (request,) = http.token_requests
        assert request is not None
        assert request.repositories == ["repo-a", "repo-b"]

    async def test_it_goes_on_the_wire_under_the_name_github_reads(self) -> None:
        """GitHub ignores a key it does not know - and grants every repository."""
        body = TokenRequest(repositories=["repo-a"]).to_json()

        assert body == {"repositories": ["repo-a"]}

    async def test_a_publishing_token_is_repository_scoped_too(self) -> None:
        """`can_open_pr` widens WHAT a token may do, never WHERE."""
        http = _FakeHttp()

        await mint_agent_token(_client(http), "42", can_open_pr=True, repositories=["repo-a"])

        (request,) = http.token_requests
        assert request is not None
        assert request.repositories == ["repo-a"]

    async def test_no_repositories_still_means_no_repositories_key(self) -> None:
        """Callers that pass none - the repo-less gh credential - keep today's request."""
        http = _FakeHttp()

        await mint_agent_token(_client(http), "42", can_open_pr=True)

        assert http.token_requests == [None]


class TestTheCacheKeysOnTheRepositorySet:
    async def test_a_token_for_one_repo_set_is_never_reused_for_another(self) -> None:
        http = _FakeHttp()
        client = _client(http)

        for_a = await installation_token(client, "42", repositories=["repo-a"])
        for_b = await installation_token(client, "42", repositories=["repo-b"])

        assert for_a.token != for_b.token
        assert len(http.token_requests) == 2

    async def test_the_same_repo_set_in_any_order_is_one_token(self) -> None:
        http = _FakeHttp()
        client = _client(http)

        first = await installation_token(client, "42", repositories=["repo-a", "repo-b"])
        second = await installation_token(client, "42", repositories=["repo-b", "repo-a"])

        assert first.token == second.token
        assert len(http.token_requests) == 1


class TestRevocation:
    async def test_a_token_is_revoked_by_presenting_it(self) -> None:
        """Not the App's JWT: only the token itself can authenticate its revocation."""
        http = _FakeHttp()

        await revoke_installation_token(_client(http), "ghs_to_end")

        assert http.deletes == [("/installation/token", "token ghs_to_end")]

    @pytest.mark.parametrize("status", [401, 404, 500])
    async def test_anything_but_204_is_not_reported_as_a_revocation(self, status: int) -> None:
        http = _FakeHttp(revocation_status=status)

        with pytest.raises(GitHubAuthError, match=str(status)):
            await revoke_installation_token(_client(http), "ghs_to_end")
