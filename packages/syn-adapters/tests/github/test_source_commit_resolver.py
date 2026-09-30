"""The GitHub source commit resolver is total, as its port requires (#1457).

An execution records a commit per repository as it starts, so this runs on
the start path of every execution. Anything it lets escape stops a run that
would otherwise have started; everything GitHub cannot answer must come back
as None, recorded as "commit unknown".
"""

from __future__ import annotations

import httpx
import pytest

from syn_adapters.github.client import GitHubAppError
from syn_adapters.github.source_commit_resolver import GitHubSourceCommitResolver
from syn_domain.contexts._shared.repository_ref import RepositoryRef

pytestmark = pytest.mark.unit

_REPO = RepositoryRef.from_slug("acme/widgets")
_SHA = "7c0ffee7c0ffee7c0ffee7c0ffee7c0ffee7c0ff"


class _Client:
    def __init__(self, *, body: object = None, fails_with: Exception | None = None) -> None:
        self._body = body
        self._fails_with = fails_with
        self.paths: list[tuple[str, str | None]] = []

    async def get_installation_for_repo(self, repo_full_name: str) -> str:
        del repo_full_name
        return "inst-1"

    async def api_get(self, path: str, installation_id: str | None = None) -> object:
        self.paths.append((path, installation_id))
        if self._fails_with is not None:
            raise self._fails_with
        return self._body


def _resolver(client: _Client) -> GitHubSourceCommitResolver:
    return GitHubSourceCommitResolver(lambda: client)  # type: ignore[arg-type,return-value]


async def test_reads_the_head_sha_through_the_repositorys_installation() -> None:
    client = _Client(body={"sha": _SHA})

    assert await _resolver(client).head_sha(_REPO) == _SHA
    assert client.paths == [("/repos/acme/widgets/commits/HEAD", "inst-1")]


@pytest.mark.parametrize(
    "failure",
    [
        GitHubAppError("no installation covers acme/widgets"),
        httpx.ConnectError("unreachable"),
        ValueError("malformed installation response"),
    ],
    ids=["no-installation", "network", "malformed"],
)
async def test_what_github_cannot_answer_is_unknown(failure: Exception) -> None:
    assert await _resolver(_Client(fails_with=failure)).head_sha(_REPO) is None


async def test_an_unconfigured_app_does_not_stop_the_start() -> None:
    """`get_github_client` raises ValueError when the App is not configured."""

    def unconfigured() -> _Client:
        raise ValueError("GitHub App is not configured")

    resolver = GitHubSourceCommitResolver(unconfigured)  # type: ignore[arg-type]

    assert await resolver.head_sha(_REPO) is None


@pytest.mark.parametrize("body", [{}, {"sha": ""}, {"sha": 7}], ids=["absent", "empty", "not-str"])
async def test_a_body_without_a_sha_is_unknown(body: object) -> None:
    assert await _resolver(_Client(body=body)).head_sha(_REPO) is None
