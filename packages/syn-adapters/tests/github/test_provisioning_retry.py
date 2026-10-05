"""A transient GitHub failure during provisioning is retried, and named transient (#1593).

Driven through `SetupPhaseSecrets.create` with a real `GitHubAppClient` over a
fake network, because the defect was a provisioned workspace that never
happened: a retry that worked at the transport and was lost before the
workspace's credentials were written would pass a transport-only test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import failure_account
from syn_shared.upstream_failure import UpstreamFailureKind

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
        # An hour from now, as GitHub issues them: a fixed timestamp goes stale
        # and lets an already-expired credential pass for a provisioned one.
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={"token": "ghs_minted", "expires_at": expires_at.isoformat()},
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


def _assert_usable(secrets: SetupPhaseSecrets) -> None:
    """Provisioned means a credential the workspace can still use, not merely one present."""
    assert secrets.repo_tokens == {_REPO: "ghs_minted"}
    assert secrets.issued
    now = datetime.now(UTC)
    for token in secrets.issued:
        assert token.expires_at > now, f"issued an expired token: {token.expires_at}"


@pytest.mark.anyio
@pytest.mark.parametrize("path", [_LOOKUP, _MINT])
async def test_one_dropped_connection_still_provisions(network: _Network, path: str) -> None:
    network.failures[path] = [_DROPPED]

    secrets = await _provision()

    _assert_usable(secrets)
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

    _assert_usable(secrets)
    assert network.sent.count(_MINT) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("path", [_LOOKUP, _MINT])
async def test_three_drops_fail_as_transient_not_as_auth(
    network: _Network, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Before #1593 a dropped mint surfaced as GitHubAuthError: an operator problem."""
    network.failures[path] = [_DROPPED, _DROPPED, _DROPPED]

    with caplog.at_level(logging.WARNING), pytest.raises(GitHubUnavailableError) as raised:
        await _provision()

    assert not isinstance(raised.value, GitHubAuthError)
    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.UNAVAILABLE
    assert account.upstream.is_transient
    assert not account.upstream.needs_operator
    assert network.sent.count(path) == 3
    # Nothing an operator installs would have helped, so nothing says to.
    assert "settings/installations" not in caplog.text
    assert "not installed" not in caplog.text


@pytest.mark.anyio
async def test_a_401_on_the_mint_is_recorded_as_needing_an_operator(network: _Network) -> None:
    network.failures[_MINT] = [401]

    with pytest.raises(GitHubAuthError) as raised:
        await _provision()

    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.AUTH
    assert account.upstream.needs_operator
    assert not account.upstream.is_transient
    assert network.sent.count(_MINT) == 1


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
