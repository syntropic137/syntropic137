"""A transient GitHub failure during provisioning is retried, and named transient (#1593).

Driven through `SetupPhaseSecrets.create` with a real `GitHubAppClient` over a
fake network, because the defect was a provisioned workspace that never
happened: a retry that worked at the transport and was lost before the
workspace's credentials were written would pass a transport-only test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import pytest

from syn_adapters.github.client import (
    GitHubAppClient,
    GitHubAppError,
    GitHubAuthError,
    GitHubUnavailableError,
)
from syn_adapters.github.client_retry import RetryPolicy
from syn_adapters.workspace_backends.service import setup_phase_secrets
from syn_adapters.workspace_backends.service.issued_tokens import IssuanceLedger
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets

pytestmark = pytest.mark.unit

_REPO = "https://github.com/org/repo-a"
_LOOKUP = "/repos/org/repo-a/installation"
_MINT = "/app/installations/7/access_tokens"
_DROPPED = httpx.RemoteProtocolError("Server disconnected without sending a response.")


@dataclass
class _Network:
    """GitHub behind a flaky network: each path fails as scripted, then answers."""

    failures: dict[str, list[Exception | int]] = field(default_factory=dict)
    sent: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.sent.append(path)
        scripted = self.failures.get(path)
        if scripted:
            failure = scripted.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return httpx.Response(failure, json={"message": "scripted"})
        if path == _LOOKUP:
            return httpx.Response(200, json={"id": 7})
        assert path == _MINT
        return httpx.Response(
            201,
            json={"token": "ghs_minted", "expires_at": "2026-10-05T08:00:00Z"},
        )


@dataclass(frozen=True)
class _Settings:
    is_configured: bool = True
    bot_name: str = "syn-bot"
    bot_email: str = "bot@example.com"


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> _Network:
    net = _Network()
    transport = httpx.MockTransport(net.handle)
    monkeypatch.setattr(
        "syn_adapters.github.GitHubAppClient",
        lambda settings: GitHubAppClient(settings, transport=transport),
    )
    monkeypatch.setattr(GitHubAppClient, "_generate_jwt", lambda _self: "jwt")
    monkeypatch.setattr("syn_shared.settings.github.GitHubAppSettings", lambda: _Settings())
    monkeypatch.setattr(setup_phase_secrets, "_resolve_claude_credentials", lambda: (None, None))
    monkeypatch.setattr(RetryPolicy, "delay_after", lambda _self, _attempt: 0.0)
    return net


async def _provision() -> SetupPhaseSecrets:
    return await SetupPhaseSecrets.create(
        repositories=[_REPO], require_github=True, ledger=IssuanceLedger()
    )


@pytest.mark.anyio
@pytest.mark.parametrize("path", [_LOOKUP, _MINT])
async def test_one_dropped_connection_still_provisions(network: _Network, path: str) -> None:
    network.failures[path] = [_DROPPED]

    secrets = await _provision()

    assert secrets.repo_tokens == {_REPO: "ghs_minted"}
    assert network.sent.count(path) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure", [_DROPPED, httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), 502, 503, 504]
)
async def test_a_transient_failure_on_the_mint_is_retried(
    network: _Network, failure: Exception | int
) -> None:
    network.failures[_MINT] = [failure, failure]

    secrets = await _provision()

    assert secrets.repo_tokens == {_REPO: "ghs_minted"}
    assert network.sent.count(_MINT) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("path", [_LOOKUP, _MINT])
async def test_three_drops_fail_as_transient_not_as_auth(network: _Network, path: str) -> None:
    """Before #1593 a dropped mint surfaced as GitHubAuthError: an operator problem."""
    network.failures[path] = [_DROPPED, _DROPPED, _DROPPED]

    with pytest.raises(GitHubUnavailableError) as raised:
        await _provision()

    assert not isinstance(raised.value, GitHubAuthError)
    assert "Transient" in str(raised.value)
    assert network.sent.count(path) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403, 404, 422])
async def test_a_4xx_is_never_retried(network: _Network, status: int) -> None:
    network.failures[_MINT] = [status]

    with pytest.raises(GitHubAppError) as raised:
        await _provision()

    assert not isinstance(raised.value, GitHubUnavailableError)
    assert network.sent.count(_MINT) == 1


@pytest.mark.anyio
async def test_an_unmarked_post_is_sent_once(network: _Network) -> None:
    """Only a caller can say a POST is safe to repeat; the transport must not assume it."""
    network.failures["/repos/org/repo-a/issues"] = [_DROPPED]
    client = GitHubAppClient(_Settings(), transport=httpx.MockTransport(network.handle))  # type: ignore[arg-type]

    with pytest.raises(GitHubUnavailableError):
        await client._http.post("/repos/org/repo-a/issues", json={"title": "x"})

    assert network.sent == ["/repos/org/repo-a/issues"]
