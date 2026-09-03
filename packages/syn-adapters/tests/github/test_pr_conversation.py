"""The GitHub side of publishing a review verdict (#1097).

A verdict that goes to the wrong endpoint is as lost as one that is never
posted, and the two failures look identical from the domain. These tests pin
the requests this adapter actually issues: pull request comments are ISSUE
comments on GitHub, and listing them is paginated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from syn_adapters.github import client_api
from syn_adapters.github.pr_conversation import GitHubPullRequestConversation

REPO = "syntropic137/syntropic137"
PR = 1042

#: What the GitHub endpoints under test send and receive.
type Body = dict[str, str]
type Payload = dict[str, object] | list[Body]


@dataclass
class _Request:
    method: str
    path: str
    params: dict[str, int]
    json: Body | None
    authorization: str


class _Response:
    """Enough of an httpx.Response for check_response and .json()."""

    def __init__(self, payload: Payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""
        self.headers: dict[str, str] = {}

    def json(self) -> Payload:
        return self._payload


@dataclass
class _FakeHttp:
    """Routes by path and records every request."""

    comment_pages: list[list[Body]] = field(default_factory=list)
    head: str = "9d5908a6c1f4e77b0a2d3915ee4c8b6721fd0e3a"
    requests: list[_Request] = field(default_factory=list)

    async def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, int] | None = None,
    ) -> _Response:
        self.requests.append(
            _Request("GET", path, params or {}, None, (headers or {}).get("Authorization", ""))
        )
        if path.endswith("/installation"):
            return _Response({"id": 4242})
        if "/pulls/" in path:
            return _Response({"head": {"sha": self.head}})
        if path.endswith("/comments"):
            page = int((params or {}).get("page", 1))
            pages = self.comment_pages or [[]]
            return _Response(pages[page - 1] if page <= len(pages) else [])
        raise AssertionError(f"unexpected GET {path}")

    async def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        json: Body | None = None,
    ) -> _Response:
        self.requests.append(
            _Request("POST", path, {}, json, (headers or {}).get("Authorization", ""))
        )
        return _Response({"id": 1})


class _FakeClient:
    """A GitHubAppClient whose transport is under the test's control."""

    def __init__(self, http: _FakeHttp) -> None:
        self._http = http
        self.jwt_calls = 0

    def _generate_jwt(self) -> str:
        self.jwt_calls += 1
        return "app-jwt"

    async def get_installation_token(
        self, installation_id: str | None = None, force_refresh: bool = False
    ) -> str:
        return f"token-for-{installation_id}"

    async def api_get(self, path: str, installation_id: str | None = None) -> Payload:
        return await client_api.api_get(self, path, installation_id)  # type: ignore[arg-type]

    async def api_post(
        self, path: str, json: Body | None = None, installation_id: str | None = None
    ) -> Payload:
        return await client_api.api_post(self, path, json, installation_id)  # type: ignore[arg-type]


def _conversation(http: _FakeHttp) -> tuple[GitHubPullRequestConversation, _FakeClient]:
    client = _FakeClient(http)
    return GitHubPullRequestConversation(client=client), client  # type: ignore[arg-type]


@pytest.mark.unit
class TestPostComment:
    async def test_posts_to_the_issue_comments_endpoint(self) -> None:
        """Pull request comments live under /issues/, not /pulls/."""
        http = _FakeHttp()
        conversation, _ = _conversation(http)

        await conversation.post_comment(REPO, PR, "the verdict")

        posts = [r for r in http.requests if r.method == "POST"]
        assert len(posts) == 1
        assert posts[0].path == f"/repos/{REPO}/issues/{PR}/comments"
        assert posts[0].json == {"body": "the verdict"}

    async def test_posts_as_the_installation_not_the_app(self) -> None:
        """An App JWT cannot comment; only an installation token can."""
        http = _FakeHttp()
        conversation, _ = _conversation(http)

        await conversation.post_comment(REPO, PR, "the verdict")

        post = next(r for r in http.requests if r.method == "POST")
        assert post.authorization == "Bearer token-for-4242"


@pytest.mark.unit
class TestReadingTheThread:
    async def test_head_sha_comes_from_the_pull_request(self) -> None:
        http = _FakeHttp(head="abcdef1234567890")
        conversation, _ = _conversation(http)

        assert await conversation.head_sha(REPO, PR) == "abcdef1234567890"
        assert any(r.path == f"/repos/{REPO}/pulls/{PR}" for r in http.requests)

    async def test_every_page_of_comments_is_read(self) -> None:
        """A short read would miss an existing marker and post a duplicate."""
        full_page = [{"body": f"comment {i}"} for i in range(100)]
        http = _FakeHttp(comment_pages=[full_page, [{"body": "the marker lives here"}]])
        conversation, _ = _conversation(http)

        bodies = await conversation.comment_bodies(REPO, PR)

        assert len(bodies) == 101
        assert bodies[-1] == "the marker lives here"
        pages = [r.params.get("page") for r in http.requests if r.path.endswith("/comments")]
        assert pages == [1, 2]

    async def test_a_short_page_ends_the_read(self) -> None:
        http = _FakeHttp(comment_pages=[[{"body": "only one"}]])
        conversation, _ = _conversation(http)

        assert await conversation.comment_bodies(REPO, PR) == ["only one"]
        assert len([r for r in http.requests if r.path.endswith("/comments")]) == 1


@pytest.mark.unit
class TestInstallationLookup:
    async def test_installation_is_resolved_once_per_repository(self) -> None:
        """Every verdict would otherwise cost an extra JWT-authenticated call."""
        http = _FakeHttp()
        conversation, client = _conversation(http)

        await conversation.head_sha(REPO, PR)
        await conversation.comment_bodies(REPO, PR)
        await conversation.post_comment(REPO, PR, "the verdict")

        lookups = [r for r in http.requests if r.path.endswith("/installation")]
        assert len(lookups) == 1
        assert client.jwt_calls == 1
