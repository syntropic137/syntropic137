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
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from syn_adapters.github.agent_token import mint_agent_token
from syn_adapters.github.client_token import (
    TokenRequest,
    get_installation_token,
    revoke_installation_token,
)

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
        self.token_request_bodies: list[_Body | None] = []
        self.minted = 0
        # What GitHub remembers about each token it issued: the repo names it
        # may reach, or None for every repo the installation covers.
        self.scopes: dict[str, list[str] | None] = {}
        self.revoked: list[str] = []

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
        if path.startswith("/repos/"):
            return self._repo_get(path, headers or {})
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
        json: _Body | None = None,
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
        token = f"ghs_token_{self.minted}"
        self.scopes[token] = None if requested is None else requested.repositories
        expires = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={
                "token": token,
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
                "permissions": effective,
                "repository_selection": "selected",
            },
            request=httpx.Request("POST", path),
        )

    async def delete(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        assert path == "/installation/token"
        token = (headers or {}).get("Authorization", "").removeprefix("token ")
        self.revoked.append(token)
        return httpx.Response(204, request=httpx.Request("DELETE", path))

    def _repo_get(self, path: str, headers: dict[str, str]) -> httpx.Response:
        """`GET /repos/{owner}/{repo}` as GitHub answers a scoped token: 404
        for any repo the token was not issued for, exactly as if it did not
        exist."""
        token = headers.get("Authorization", "").removeprefix("token ")
        repo = path.rstrip("/").split("/")[-1]
        scope = self.scopes.get(token, [])
        status = 200 if token not in self.revoked and (scope is None or repo in scope) else 404
        return httpx.Response(status, request=httpx.Request("GET", path))


_Body = dict[str, dict[str, str] | list[str]]


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
async def test_the_scope_goes_on_the_wire_under_the_name_github_reads() -> None:
    """The one assertion that has to spell the JSON key out.

    Every other test here reads the request back through `TokenRequest`, so a
    field renamed or aliased on the model would round-trip green on both sides
    while GitHub received a key it does not recognise - and an unrecognised
    key means an unscoped token, which is the whole defect. This pins the
    serialized body `get_installation_token` actually posts, against what the
    endpoint documents.
    """
    fake = _FakeClient({"contents": "write", "pull_requests": "write"})

    await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    assert fake.http.token_request_bodies == [
        {"permissions": {"contents": "write", "pull_requests": "read"}}
    ]


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

    assert scoped.token != publishing.token
    assert _requested_permissions(fake) is not None
    assert fake.http.minted == 2


@pytest.mark.unit
async def test_an_agent_token_is_never_served_from_the_cache() -> None:
    """Every mint is a new token (#725).

    This used to be the opposite test: a scoped token was reused rather than
    reminted. It had to go once the workspace holding the token started
    renewing and revoking it. A renewal served from the cache is handed the
    token it is replacing, with the same expiry, and nothing is renewed; a
    revocation at one workspace's teardown kills the token a concurrent
    workspace on the same repo had been served.
    """
    fake = _FakeClient()

    first = await mint_agent_token(_as_client(fake), "42", can_open_pr=False)
    second = await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    assert first.token != second.token
    assert fake.http.minted == 2
    assert fake._cached_tokens == {}


@pytest.mark.unit
async def test_the_token_request_names_the_repos_under_work() -> None:
    """Repo-scoped minting (#725): the body carries repository NAMES.

    GitHub's endpoint takes names without the owner - the owner is the
    installation's - and spells the key `repositories`. Pinned as JSON for the
    same reason as the permissions key above.
    """
    fake = _FakeClient({"contents": "write", "pull_requests": "write"})

    await mint_agent_token(
        _as_client(fake),
        "42",
        can_open_pr=False,
        repositories=["acme/api", "acme/web"],
    )

    assert fake.http.token_request_bodies == [
        {
            "permissions": {"contents": "write", "pull_requests": "read"},
            "repositories": ["api", "web"],
        }
    ]


@pytest.mark.unit
async def test_the_publishing_token_is_repo_scoped_too() -> None:
    """Full permissions, but still only the named repos."""
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", can_open_pr=True, repositories=["acme/api"])

    assert fake.http.token_request_bodies == [{"repositories": ["api"]}]


@pytest.mark.unit
async def test_a_token_for_repo_a_cannot_reach_repo_b() -> None:
    """What repo scoping buys, asked of (a mock of) GitHub rather than the body."""
    fake = _FakeClient()

    token = await mint_agent_token(
        _as_client(fake), "42", can_open_pr=False, repositories=["acme/a"]
    )

    auth = {"Authorization": f"token {token.token}"}
    assert (await fake.http.get("/repos/acme/a", headers=auth)).status_code == 200
    assert (await fake.http.get("/repos/acme/b", headers=auth)).status_code == 404


@pytest.mark.unit
async def test_a_repo_less_token_names_no_repos() -> None:
    """A workflow with no repo still needs gh; its token is installation-wide."""
    fake = _FakeClient()

    await mint_agent_token(_as_client(fake), "42", can_open_pr=True)

    assert fake.http.token_request_bodies == [None]


@pytest.mark.unit
async def test_the_shared_cache_keys_on_the_repo_set() -> None:
    """(installation, repo set, permissions): a token for A is never served for B."""
    fake = _FakeClient()
    client = _as_client(fake)

    for_a = await get_installation_token(client, "42", repositories=["a"])
    for_b = await get_installation_token(client, "42", repositories=["b"])
    for_a_again = await get_installation_token(client, "42", repositories=["a"])

    assert for_a != for_b
    assert for_a_again == for_a
    assert fake.http.minted == 2


@pytest.mark.unit
async def test_revocation_authenticates_with_the_token_it_revokes() -> None:
    """`DELETE /installation/token` takes no id; the credential is the argument."""
    fake = _FakeClient()
    token = await mint_agent_token(_as_client(fake), "42", can_open_pr=False)

    await revoke_installation_token(_as_client(fake), token.token)

    assert fake.http.revoked == [token.token]


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
