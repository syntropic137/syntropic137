"""The PR commenter finds its own comment on any page, not only the first (#1547)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from syn_adapters.github.pull_request_commenter import GitHubPullRequestCommenter

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REPO = "acme/widget"
_MARKER = "<!-- syn-quarantine:exec-1:implement:acme/widget -->"


@dataclass
class _Client:
    """A PR with 100 unrelated comments, then the notice on page two."""

    comments: list[tuple[int, str]] = field(
        default_factory=lambda: (
            [(i, "unrelated") for i in range(1, 101)] + [(500, f"{_MARKER}\nold notice")]
        )
    )
    posts: int = 0
    patched: list[int] = field(default_factory=list)

    async def get_installation_for_repo(self, _repository: str) -> str:
        return "inst-1"

    async def api_get(self, path: str, _installation_id: str) -> object:
        page = int(path.rsplit("page=", 1)[1])
        chunk = self.comments[(page - 1) * 100 : page * 100]
        return [{"id": i, "body": b} for i, b in chunk]

    async def api_patch(self, path: str, _json: dict[str, str], _installation_id: str) -> object:
        self.patched.append(int(path.rsplit("/", 1)[1]))
        return {}

    async def api_post(self, _path: str, _json: dict[str, str], _installation_id: str) -> object:
        self.posts += 1
        return {"id": 999}


async def test_a_retry_edits_the_marked_comment_on_page_two() -> None:
    client = _Client()
    commenter = GitHubPullRequestCommenter(lambda: client)  # type: ignore[arg-type, return-value]
    comment_id = await commenter.upsert_comment(
        _REPO, 42, marker=_MARKER, body=f"{_MARKER}\nnew", comment_id=None
    )
    assert comment_id == 500
    assert client.posts == 0 and client.patched == [500]


async def test_with_no_marked_comment_it_posts_one() -> None:
    client = _Client(comments=[(1, "unrelated")])
    commenter = GitHubPullRequestCommenter(lambda: client)  # type: ignore[arg-type, return-value]
    assert (
        await commenter.upsert_comment(_REPO, 42, marker=_MARKER, body=_MARKER, comment_id=None)
        == 999
    )
    assert client.posts == 1
