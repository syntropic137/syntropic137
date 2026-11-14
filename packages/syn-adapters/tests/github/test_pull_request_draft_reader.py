"""The GitHub draft reader is total, as its port requires (#2058).

Every failure comes back ``UNKNOWN`` with its reason, which the trigger
evaluator reads as "do not fire". Raising instead would surface as a failed
webhook evaluation, and reading a failure as "ready" would fire blind.
"""

from __future__ import annotations

import pytest

from syn_adapters.github.client import GitHubAppError
from syn_adapters.github.pull_request_draft_reader import GitHubPullRequestDraftReader
from syn_domain.contexts.github.ports import PullRequestReadiness

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REPO = "acme/widgets"


class _Client:
    def __init__(self, answer: object | Exception) -> None:
        self._answer = answer
        self.calls: list[tuple[str, str | None]] = []

    async def get_installation_for_repo(self, repo_full_name: str) -> str:
        del repo_full_name
        return "inst-resolved"

    async def api_get(self, path: str, installation_id: str | None = None) -> object:
        self.calls.append((path, installation_id))
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _reader(client: _Client) -> GitHubPullRequestDraftReader:
    return GitHubPullRequestDraftReader(lambda: client)  # type: ignore[arg-type,return-value]


@pytest.mark.parametrize(
    ("draft", "readiness"),
    [(True, PullRequestReadiness.DRAFT), (False, PullRequestReadiness.READY)],
)
async def test_reads_the_draft_flag_of_the_pull(
    draft: bool, readiness: PullRequestReadiness
) -> None:
    client = _Client({"number": 42, "draft": draft})

    reading = await _reader(client).read_draft_state(_REPO, 42, "inst-1")

    assert reading.readiness is readiness
    assert client.calls == [(f"/repos/{_REPO}/pulls/42", "inst-1")]


async def test_an_empty_installation_is_resolved_from_the_repository() -> None:
    client = _Client({"draft": False})

    await _reader(client).read_draft_state(_REPO, 42, "")

    assert client.calls == [(f"/repos/{_REPO}/pulls/42", "inst-resolved")]


@pytest.mark.parametrize(
    "answer",
    [
        GitHubAppError("GitHub API error 502", status_code=502),
        {"number": 42},  # no draft flag: never guess one
        {"number": 42, "draft": "maybe"},
    ],
)
async def test_anything_but_a_draft_flag_is_unknown_with_the_reason(answer: object) -> None:
    reading = await _reader(_Client(answer)).read_draft_state(_REPO, 42, "inst-1")

    assert reading.readiness is PullRequestReadiness.UNKNOWN
    assert reading.detail


async def test_an_unconfigured_app_is_unknown_not_raised() -> None:
    def _no_app() -> object:
        raise GitHubAppError("GitHub App not configured")

    reader = GitHubPullRequestDraftReader(_no_app)  # type: ignore[arg-type]

    reading = await reader.read_draft_state(_REPO, 42, "inst-1")

    assert reading.readiness is PullRequestReadiness.UNKNOWN
    assert "not configured" in reading.detail
