"""The GitHub remote branch reader is total, as its port requires (#1513).

A 404 on the branch is the one answer read as "gone". Anything else GitHub
cannot answer must come back unreadable, so a resume never mistakes an outage
for a deleted branch, and never continues a branch nobody verified.
"""

from __future__ import annotations

import httpx
import pytest

from syn_adapters.github.client import GitHubAppError
from syn_adapters.github.remote_branch_reader import GitHubRemoteBranchReader

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REPO = "acme/widgets"
_BRANCH = "feat/1513-x"
_SHA = "b1513b1513b1513b1513b1513b1513b1513b1513"


class _Client:
    def __init__(self, answers: dict[str, object | Exception]) -> None:
        self._answers = answers
        self.paths: list[str] = []

    async def get_installation_for_repo(self, repo_full_name: str) -> str:
        del repo_full_name
        return "inst-1"

    async def api_get(self, path: str, installation_id: str | None = None) -> object:
        del installation_id
        self.paths.append(path)
        answer = next(a for prefix, a in self._answers.items() if path.startswith(prefix))
        if isinstance(answer, Exception):
            raise answer
        return answer


_BRANCH_PATH = f"/repos/{_REPO}/branches/"
_PULLS_PATH = f"/repos/{_REPO}/pulls"


def _reader(client: _Client) -> GitHubRemoteBranchReader:
    return GitHubRemoteBranchReader(lambda: client)  # type: ignore[arg-type,return-value]


async def test_reads_the_head_and_the_open_pr() -> None:
    client = _Client(
        {
            _BRANCH_PATH: {"commit": {"sha": _SHA}},
            _PULLS_PATH: [{"number": 7, "state": "closed"}, {"number": 9, "state": "open"}],
        }
    )

    reading = await _reader(client).read_branch(_REPO, _BRANCH)

    assert reading.readable
    assert reading.head_sha == _SHA
    assert reading.open_pull_request == 9
    assert reading.closed_pull_request == 7
    assert client.paths[0] == f"/repos/{_REPO}/branches/feat%2F1513-x"
    assert "head=acme:feat%2F1513-x" in client.paths[1]


async def test_a_404_is_a_branch_that_is_gone() -> None:
    client = _Client({_BRANCH_PATH: GitHubAppError("GitHub API error 404: Branch not found")})

    reading = await _reader(client).read_branch(_REPO, _BRANCH)

    assert reading.readable
    assert reading.head_sha is None


@pytest.mark.parametrize(
    "failure",
    [
        GitHubAppError("GitHub API error 500: boom"),
        httpx.ConnectError("unreachable"),
        ValueError("malformed installation response"),
    ],
    ids=["server-error", "network", "malformed"],
)
async def test_anything_else_is_unreadable_never_gone(failure: Exception) -> None:
    client = _Client({_BRANCH_PATH: failure})

    reading = await _reader(client).read_branch(_REPO, _BRANCH)

    assert not reading.readable


async def test_an_unconfigured_app_is_unreadable() -> None:
    def unconfigured() -> object:
        raise GitHubAppError("GitHub App is not configured")

    reading = await GitHubRemoteBranchReader(unconfigured).read_branch(  # type: ignore[arg-type]
        _REPO, _BRANCH
    )

    assert not reading.readable
