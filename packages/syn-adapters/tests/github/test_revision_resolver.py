"""The GitHub revision resolver pins a ref, and says why when it cannot (#967).

An eval's baseline is resolved through this before anything is recorded, and
the port forbids raising: each way GitHub cannot answer has to arrive as the
``UnresolvedReason`` that tells the person what to fix. The errors here are the
ones the real client raises - ``check_response`` with the status GitHub sent.
"""

from __future__ import annotations

import httpx
import pytest

from syn_adapters.github.client import (
    GitHubAppError,
    GitHubAuthError,
    GitHubRateLimitError,
)
from syn_adapters.github.client_api import check_response
from syn_adapters.github.revision_resolver import GitHubRevisionResolver
from syn_domain.contexts._shared.repository_ref import RepositoryRef
from syn_domain.contexts.orchestration.ports.RevisionResolverPort import (
    ResolvedRevision,
    UnresolvedReason,
    UnresolvedRevision,
)

pytestmark = pytest.mark.unit

_REPO = RepositoryRef.from_slug("acme/widgets")
_SHA = "7c0ffee7c0ffee7c0ffee7c0ffee7c0ffee7c0ff"


def _github_said(status: int, text: str = "{}") -> GitHubAppError:
    """The error the real client raises for this answer."""
    try:
        check_response(httpx.Response(status, text=text))
    except GitHubAppError as exc:
        return exc
    raise AssertionError(f"check_response accepted {status}")


class _Client:
    def __init__(
        self,
        *,
        body: object = None,
        fails_with: Exception | None = None,
        not_installed: bool = False,
    ) -> None:
        self._body = body
        self._fails_with = fails_with
        self._not_installed = not_installed
        self.paths: list[tuple[str, str | None]] = []

    async def get_installation_for_repo(self, repo_full_name: str) -> str:
        if self._not_installed:
            raise GitHubAuthError(f"GitHub App not installed on repository: {repo_full_name}")
        return "inst-1"

    async def api_get(self, path: str, installation_id: str | None = None) -> object:
        self.paths.append((path, installation_id))
        if self._fails_with is not None:
            raise self._fails_with
        return self._body


def _resolver(client: _Client) -> GitHubRevisionResolver:
    return GitHubRevisionResolver(lambda: client)  # type: ignore[arg-type,return-value]


async def _reason(client: _Client) -> UnresolvedReason:
    answer = await _resolver(client).resolve(_REPO, "main")
    assert isinstance(answer, UnresolvedRevision)
    return answer.reason


@pytest.mark.parametrize("ref", ["main", "v1.2.0", "7c0ffee", _SHA])
async def test_a_branch_tag_or_sha_resolves_through_the_installation(ref: str) -> None:
    client = _Client(body={"sha": _SHA, "commit": {"message": "ignored"}})

    assert await _resolver(client).resolve(_REPO, ref) == ResolvedRevision(_SHA)
    assert client.paths == [(f"/repos/acme/widgets/commits/{ref}", "inst-1")]


async def test_a_ref_with_a_slash_is_one_path_segment() -> None:
    client = _Client(body={"sha": _SHA})

    await _resolver(client).resolve(_REPO, "release/2026-10")

    assert client.paths == [("/repos/acme/widgets/commits/release%2F2026-10", "inst-1")]


async def test_an_uppercase_answer_is_pinned_in_its_one_spelling() -> None:
    answer = await _resolver(_Client(body={"sha": _SHA.upper()})).resolve(_REPO, "main")

    assert answer == ResolvedRevision(_SHA)


@pytest.mark.parametrize("status", [404, 422], ids=["no-such-ref", "no-such-sha"])
async def test_a_ref_the_repository_does_not_hold_is_not_found(status: int) -> None:
    assert await _reason(_Client(fails_with=_github_said(status))) is UnresolvedReason.NOT_FOUND


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_read_is_no_access(status: int) -> None:
    assert await _reason(_Client(fails_with=_github_said(status))) is UnresolvedReason.NO_ACCESS


async def test_a_repository_no_installation_covers_is_no_access() -> None:
    assert await _reason(_Client(not_installed=True)) is UnresolvedReason.NO_ACCESS


async def test_an_unconfigured_app_is_no_access() -> None:
    """`get_github_client` raises ValueError when the App is not configured."""

    def unconfigured() -> _Client:
        raise ValueError("GitHub App is not configured")

    answer = await GitHubRevisionResolver(unconfigured).resolve(_REPO, "main")  # type: ignore[arg-type]

    assert isinstance(answer, UnresolvedRevision)
    assert answer.reason is UnresolvedReason.NO_ACCESS


async def test_a_rate_limit_is_retryable_not_no_access() -> None:
    """GitHub sends a rate limit as a 403; it must not read as a permissions problem."""
    limited = _github_said(403, "API rate limit exceeded for installation")
    assert isinstance(limited, GitHubRateLimitError)

    assert await _reason(_Client(fails_with=limited)) is UnresolvedReason.UNAVAILABLE


@pytest.mark.parametrize(
    "failure",
    [_github_said(502), httpx.ConnectError("unreachable")],
    ids=["5xx", "network"],
)
async def test_a_forge_that_cannot_be_asked_is_unavailable(failure: Exception) -> None:
    assert await _reason(_Client(fails_with=failure)) is UnresolvedReason.UNAVAILABLE


@pytest.mark.parametrize(
    "body", [{}, {"sha": "7c0ffee"}, {"sha": 7}, []], ids=["absent", "short", "not-str", "list"]
)
async def test_an_answer_that_is_not_a_full_sha_is_never_pinned(body: object) -> None:
    assert await _reason(_Client(body=body)) is UnresolvedReason.UNAVAILABLE
