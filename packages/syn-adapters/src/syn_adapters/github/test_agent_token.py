"""Every agent phase holds the installation's own permissions (#1477).

#1197 minted non-publishing phases a token with `pull_requests: read`, meaning
to block `gh pr create` and believing `gh pr comment` still worked through
`issues: write`. It did not: GitHub refused the comment through GraphQL
`addComment` and through the REST issues endpoint alike (measured 2026-10-01),
and there is no comment-only permission. Phases are ephemeral and open their
own PRs, so these tests pin that NO phase token asks for a permission subset.

Repository scoping (#725) is unaffected; its tests live beside this file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from syn_adapters.github.agent_token import mint_agent_token
from syn_adapters.github.client_token import TokenRequest

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient, InstallationToken

# What the syntropic137 App actually holds, as returned by
# GET /app/installations/{id}. `pull_requests: write` is the one that makes
# `gh pr create` work.
_GRANTED = {
    "contents": "write",
    "issues": "write",
    "pull_requests": "write",
    "checks": "read",
    "metadata": "read",
}


class _FakeHttp:
    """Records what was asked of GitHub, and answers as GitHub would.

    It keeps the JSON body verbatim, because that is what a transport has:
    the request only becomes a `TokenRequest` when something reads it, which
    is exactly the hop GitHub performs. Every reader below goes through
    `last_token_request()` and gets it typed.
    """

    def __init__(self, granted: dict[str, str]) -> None:
        self._granted = granted
        self.token_request_bodies: list[dict[str, dict[str, str] | list[str]] | None] = []
        self.minted = 0

    def last_token_request(self) -> TokenRequest | None:
        """The most recent token request, parsed as the endpoint parses it.

        None means no body went on the wire at all - the case that grants the
        installation's full permission set, and so the one that decides
        whether a phase can publish (#1197).
        """
        assert self.token_request_bodies, "no installation token was ever requested"
        body = self.token_request_bodies[-1]
        return None if body is None else TokenRequest.model_validate(body)

    async def get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        assert path.startswith("/app/installations/")
        return httpx.Response(
            200,
            json={"id": 42, "permissions": self._granted},
            request=httpx.Request("GET", path),
        )

    async def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        json: dict[str, dict[str, str] | list[str]] | None = None,
        extensions: object = None,
    ) -> httpx.Response:
        self.token_request_bodies.append(json)
        self.minted += 1
        # GitHub echoes back the permissions the token actually carries. A
        # request with no body at all gets the installation's full set - which
        # is exactly the behaviour that let `implement` publish.
        requested = self.last_token_request()
        effective = (
            self._granted
            if requested is None or requested.permissions is None
            else requested.permissions
        )
        expires = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={
                "token": f"ghs_token_{self.minted}",
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
                "permissions": effective,
                "repository_selection": "selected",
            },
            request=httpx.Request("POST", path),
        )


class _FakeClient:
    """The surface `client_token`/`agent_token` actually use of GitHubAppClient."""

    def __init__(self, granted: dict[str, str] | None = None) -> None:
        self.http = _FakeHttp(granted if granted is not None else dict(_GRANTED))
        self._http = self.http
        self._cached_tokens: dict[str, InstallationToken] = {}

    def _generate_jwt(self) -> str:
        return "jwt-for-tests"


def _as_client(fake: _FakeClient) -> GitHubAppClient:
    return cast("GitHubAppClient", fake)


def _requested_permissions(fake: _FakeClient) -> dict[str, str] | None:
    """The scope the last token request asked for, or None for the full grant."""
    requested = fake.http.last_token_request()
    return None if requested is None else requested.permissions


@pytest.mark.unit
async def test_a_phase_token_requests_no_permission_downgrade() -> None:
    """The regression: no body means GitHub grants the installation's full set.

    A `permissions` subset here is how #1197 took `pull_requests: write` away,
    and with it every PR comment a review phase was told to post.
    """
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", repositories=["repo-a"])

    requested = fake.http.last_token_request()
    assert requested is not None
    assert requested.permissions is None, (
        "a phase token must not narrow the installation's permissions: "
        "pull_requests: read refuses `gh pr comment` (#1477)"
    )


@pytest.mark.unit
async def test_a_phase_token_is_still_scoped_to_its_repositories() -> None:
    """Dropping the permission downgrade must not drop WHERE the token reaches (#725)."""
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", repositories=["repo-b", "repo-a"])

    requested = fake.http.last_token_request()
    assert requested is not None
    assert requested.repositories == ["repo-a", "repo-b"]


@pytest.mark.unit
async def test_the_token_carries_pull_requests_write_when_the_installation_grants_it() -> None:
    """What the agent can actually do: comment on and open pull requests."""
    fake = _FakeClient()

    minted = await mint_agent_token(_as_client(fake), "42", repositories=["repo-a"])

    assert minted.permissions["pull_requests"] == "write"


@pytest.mark.unit
async def test_a_phase_token_is_reused_rather_than_reminted() -> None:
    """The cache still has to work, or every phase pays an API call."""
    fake = _FakeClient()

    first = await mint_agent_token(_as_client(fake), "42", repositories=["repo-a"])
    second = await mint_agent_token(_as_client(fake), "42", repositories=["repo-a"])

    assert first == second
    assert fake.http.minted == 1
