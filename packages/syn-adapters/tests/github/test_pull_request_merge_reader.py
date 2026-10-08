"""The merged-PR reader asks GitHub through the App client's mint retry (#1728).

Driven with a real `GitHubAppClient` over a fake network: a merge state read
through a token whose mint failed once must still arrive, and a GitHub that
cannot answer must come back unreadable, never as "not merged".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from syn_adapters.github.client import GitHubAppClient
from syn_adapters.github.client_retry import RetryPolicy
from syn_adapters.github.pull_request_merge_reader import GitHubPullRequestMergeReader

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_REPO = "acme/widget"
_LOOKUP = f"/repos/{_REPO}/installation"
_MINT = "/app/installations/7/access_tokens"
_PULL = f"/repos/{_REPO}/pulls/7"
_MERGED_AT = "2026-10-07T11:00:00Z"


@dataclass(frozen=True)
class _Settings:
    is_configured: bool = True
    bot_name: str = "syn-bot"
    bot_email: str = "bot@example.com"


@dataclass
class _Network:
    failures: dict[str, list[int]] = field(default_factory=dict)
    pull: dict[str, object] = field(
        default_factory=lambda: {"state": "closed", "merged_at": _MERGED_AT}
    )
    sent: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.sent.append(path)
        scripted = self.failures.get(path)
        if scripted:
            return httpx.Response(scripted.pop(0), json={"message": "scripted"})
        if path == _LOOKUP:
            return httpx.Response(200, json={"id": 7})
        if path == _MINT:
            expires_at = datetime.now(UTC) + timedelta(hours=1)
            return httpx.Response(
                201, json={"token": "ghs_minted", "expires_at": expires_at.isoformat()}
            )
        assert path == _PULL
        assert request.headers["authorization"].endswith("ghs_minted")
        return httpx.Response(200, json=self.pull)


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> _Network:
    monkeypatch.setattr(GitHubAppClient, "_generate_jwt", lambda _self: "jwt")
    monkeypatch.setattr(RetryPolicy, "delay_after", lambda _self, _attempt: 0.0)
    return _Network()


def _reader(network: _Network) -> GitHubPullRequestMergeReader:
    client = GitHubAppClient(_Settings(), transport=httpx.MockTransport(network.handle))  # type: ignore[arg-type]
    return GitHubPullRequestMergeReader(lambda: client)


async def test_a_mint_that_failed_once_is_retried_and_the_merge_is_read(
    network: _Network,
) -> None:
    network.failures[_MINT] = [503]

    state = await _reader(network).read_merge(_REPO, 7)

    assert network.sent.count(_MINT) == 2
    assert state.readable
    assert state.merged_at == datetime(2026, 10, 7, 11, tzinfo=UTC)


async def test_a_closed_unmerged_pr_is_closed_and_not_merged(network: _Network) -> None:
    network.pull = {"state": "closed", "merged_at": None}

    state = await _reader(network).read_merge(_REPO, 7)

    assert (state.readable, state.merged_at, state.closed) == (True, None, True)


async def test_github_that_cannot_answer_is_unreadable_not_unmerged(network: _Network) -> None:
    network.failures[_PULL] = [500] * 10

    state = await _reader(network).read_merge(_REPO, 7)

    assert not state.readable
