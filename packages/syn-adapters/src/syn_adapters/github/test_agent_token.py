"""The credential an agent phase holds is what decides whether it can publish (#1197).

`implement` opened its own pull request four minutes before it finished, and
`open_pr` - the phase whose entire job is to refuse publication when
verification finds a defect - never ran. The implement prompt already said
"Do not open a PR", in those words. The prompt was not the gate; nothing was.

So the question these tests ask is not "was the agent told not to" but "could
it have". A phase that may not publish is handed an installation token whose
`pull_requests` permission is `read`, and `POST /repos/{o}/{r}/pulls` returns
403 to it - through `gh pr create`, through `curl`, through the API directly,
and on a codex phase where a tool allowlist would not have applied at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from syn_adapters.github.agent_token import mint_agent_token

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
    """Records what was asked of GitHub, and answers as GitHub would."""

    def __init__(self, granted: dict[str, str]) -> None:
        self._granted = granted
        self.token_requests: list[dict[str, Any] | None] = []
        self.minted = 0

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
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self.token_requests.append(json)
        self.minted += 1
        # GitHub echoes back the permissions the token actually carries. When
        # `permissions` is omitted the token gets the installation's full set -
        # which is exactly the behaviour that let `implement` publish.
        effective = json["permissions"] if json and "permissions" in json else self._granted
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
    assert fake.http.token_requests, "no installation token was ever requested"
    body = fake.http.token_requests[-1]
    return None if body is None else body.get("permissions")


@pytest.mark.unit
async def test_a_phase_that_may_not_publish_cannot_create_a_pull_request() -> None:
    """The reproduction, at the only layer that could have stopped it."""
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    requested = _requested_permissions(fake)
    assert requested is not None, (
        "no `permissions` in the token request means GitHub grants the "
        "installation's full set, including pull_requests: write"
    )
    assert requested["pull_requests"] == "read"


@pytest.mark.unit
async def test_that_phase_can_still_push_read_prs_and_talk_to_issues() -> None:
    """Scoping publication away must not take the work with it.

    `implement` pushes a branch, `gh pr checkout`s the PR it is reworking and
    reads the issue it is fixing. A token that blocked those would trade one
    broken workflow for another.
    """
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    requested = _requested_permissions(fake)
    assert requested is not None
    assert requested["contents"] == "write"  # push the branch
    assert requested["pull_requests"] == "read"  # gh pr checkout / view / diff
    assert requested["issues"] == "write"  # gh issue view, and commenting
    assert requested["checks"] == "read"  # gh pr checks


@pytest.mark.unit
async def test_the_publishing_phase_is_the_one_that_gets_write() -> None:
    """`open_pr` exists to publish; scoping it down would break the gate itself."""
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", can_open_pr=True)

    assert _requested_permissions(fake) is None


@pytest.mark.unit
async def test_we_never_ask_for_a_permission_the_installation_does_not_hold() -> None:
    """GitHub 422s a token request that exceeds the installation's own grant.

    An enumerated "what a phase needs" list would break any deployment whose
    App is configured differently from ours. The scope is derived from what
    the installation actually holds, so it cannot exceed it.
    """
    fake = _FakeClient({"contents": "write", "metadata": "read"})

    await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    requested = _requested_permissions(fake)
    assert requested is not None
    assert set(requested) == {"contents", "metadata"}
    assert "pull_requests" not in requested


@pytest.mark.unit
async def test_a_publishing_phase_does_not_hand_its_token_to_a_scoped_one() -> None:
    """Tokens are cached per installation, and both phases share an installation.

    `open_pr` and `implement` run under the same installation id in the same
    process. A cache keyed on that id alone would serve `implement` the
    unscoped token `open_pr` minted, and the boundary would hold only until
    the first execution that published anything.
    """
    fake = _FakeClient()

    publishing = await mint_agent_token(_as_client(fake), "42", can_open_pr=True)
    scoped = await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    assert scoped != publishing
    assert _requested_permissions(fake) is not None
    assert fake.http.minted == 2


@pytest.mark.unit
async def test_a_scoped_token_is_reused_rather_than_reminted() -> None:
    """The cache still has to work, or every phase pays two API calls."""
    fake = _FakeClient()

    first = await mint_agent_token(_as_client(fake), "42", can_open_pr=False)
    second = await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    assert first == second
    assert fake.http.minted == 1


@pytest.mark.unit
async def test_a_scope_we_cannot_establish_yields_no_token_at_all() -> None:
    """Fail closed. An unscoped token handed out on a lookup error is the bug."""

    class _Broken(_FakeClient):
        async def _boom(self, *args: object, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("installation lookup failed")

    fake = _Broken()
    fake.http.get = fake._boom  # type: ignore[method-assign]

    with pytest.raises(httpx.HTTPError):
        await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    assert fake.http.minted == 0
