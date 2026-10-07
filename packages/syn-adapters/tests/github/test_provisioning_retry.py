"""A transient GitHub failure during provisioning is retried, and named transient (#1593).

The token mint is the one non-idempotent request resent after GitHub may have
acted: through 5xx, 429 and lost responses, accepting an orphan token (owner
decision, 2026-10-07). Every other POST keeps the no-resend rule.

Driven through `SetupPhaseSecrets.create` with a real `GitHubAppClient` over a
fake network, because the defect was a provisioned workspace that never
happened: a retry that worked at the transport and was lost before the
workspace's credentials were written would pass a transport-only test.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from syn_adapters.github import client_retry
from syn_adapters.github.client import (
    GitHubAppClient,
    GitHubAppError,
    GitHubAuthError,
    GitHubUnavailableError,
)
from syn_adapters.github.client_retry import (
    MINT_ATTEMPTS,
    MINT_BACKOFF_BUDGET_SECONDS,
    RetryPolicy,
)
from syn_adapters.workspace_backends.service import setup_phase_secrets
from syn_adapters.workspace_backends.service.issued_tokens import IssuanceLedger
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import failure_account
from syn_shared.settings.config import Settings
from syn_shared.upstream_failure import UpstreamFailureKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

_REPO = "https://github.com/org/repo-a"
_LOOKUP = "/repos/org/repo-a/installation"
_MINT = "/app/installations/7/access_tokens"
_DROPPED = httpx.RemoteProtocolError("Server disconnected without sending a response.")


@dataclass(frozen=True)
class _TruncatedBody:
    """GitHub answered with this status, then the connection broke mid-body.

    The headers arrive, so the transport returns; the failure comes only when
    httpx reads the body (#1611).
    """

    status: int


class _BreaksOffStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"tok'
        raise httpx.ReadError("body truncated")


type _Failure = Exception | int | _TruncatedBody | httpx.Response


@dataclass
class _Network:
    """GitHub behind a flaky network: each path fails as scripted, then answers."""

    failures: dict[str, list[_Failure]] = field(default_factory=dict)
    #: Failures that happen AFTER GitHub acted: the token is minted, then the
    #: response is lost on its way back.
    lost_responses: dict[str, list[_Failure]] = field(default_factory=dict)
    sent: list[str] = field(default_factory=list)
    #: Every token GitHub issued, whether or not its holder ever heard of it.
    minted: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.sent.append(path)
        scripted = self.failures.get(path)
        if scripted:
            return self._fail(scripted.pop(0))
        if path == _LOOKUP:
            return httpx.Response(200, json={"id": 7})
        assert path == _MINT
        self.minted.append("ghs_minted")
        lost = self.lost_responses.get(path)
        if lost:
            return self._fail(lost.pop(0))
        # An hour from now, as GitHub issues them: a fixed timestamp goes stale
        # and lets an already-expired credential pass for a provisioned one.
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={"token": "ghs_minted", "expires_at": expires_at.isoformat()},
        )

    @staticmethod
    def _fail(failure: _Failure) -> httpx.Response:
        if isinstance(failure, Exception):
            raise failure
        if isinstance(failure, _TruncatedBody):
            return httpx.Response(failure.status, stream=_BreaksOffStream())
        if isinstance(failure, httpx.Response):
            return failure
        return httpx.Response(failure, json={"message": "scripted"})


@dataclass(frozen=True)
class _Settings:
    is_configured: bool = True
    bot_name: str = "syn-bot"
    bot_email: str = "bot@example.com"


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every backoff the transport awaited, in order. Nothing really sleeps.

    Patched at ``asyncio.sleep`` itself: a backoff that bypassed it - a
    ``time.sleep`` that would block the API's event loop - waits for real and
    is missing here.
    """
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def record(seconds: float) -> None:
        delays.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(client_retry.asyncio, "sleep", record)
    return delays


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch, slept: list[float]) -> _Network:
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


_UNSENT = [
    httpx.ConnectError("refused"),
    httpx.ConnectTimeout("no route"),
    httpx.PoolTimeout("no free connection"),
]
_AMBIGUOUS = [
    _DROPPED,
    httpx.ReadError("connection reset by peer"),
    httpx.ReadTimeout("slow"),
    httpx.WriteError("broken pipe"),
    httpx.WriteTimeout("slow upload"),
    502,
    503,
    504,
    _TruncatedBody(200),
    _TruncatedBody(201),
]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", _UNSENT + _AMBIGUOUS)
async def test_a_transient_failure_on_the_lookup_is_retried(
    network: _Network, failure: _Failure
) -> None:
    network.failures[_LOOKUP] = [failure, failure]

    secrets = await _provision()

    _assert_usable(secrets)
    assert network.sent.count(_LOOKUP) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("failure", _UNSENT)
async def test_a_mint_that_never_reached_github_is_retried(
    network: _Network, failure: Exception
) -> None:
    network.failures[_MINT] = [failure, failure]

    secrets = await _provision()

    _assert_usable(secrets)
    assert network.sent.count(_MINT) == 3
    # Never reached GitHub, so no orphan: one token, the one we hold.
    assert network.minted == ["ghs_minted"]


@pytest.mark.anyio
@pytest.mark.parametrize("lost", _AMBIGUOUS)
async def test_github_minted_but_the_response_dropped_is_minted_again(
    network: _Network, lost: _Failure, caplog: pytest.LogCaptureFixture
) -> None:
    """Owner decision, 2026-10-07: retry the mint, accept the orphan token.

    GitHub issued a token nobody received - live for an hour, unrevocable by
    the ledger that never saw it. Before the decision this failed the phase
    instead; GitHub's 500 bursts made that the worse cost. The resend says so
    at WARNING, and never prints a token.
    """
    network.lost_responses[_MINT] = [lost]

    with caplog.at_level(logging.WARNING):
        secrets = await _provision()

    _assert_usable(secrets)
    assert network.minted == ["ghs_minted", "ghs_minted"]
    assert network.sent.count(_MINT) == 2
    (retry,) = [r for r in caplog.records if "token mint" in r.getMessage()]
    assert retry.levelno == logging.WARNING
    assert "orphan" in retry.getMessage()
    assert "attempt 1/5" in retry.getMessage()
    assert "ghs_minted" not in caplog.text


@pytest.mark.anyio
async def test_a_mint_answered_500_twice_then_201_succeeds(
    network: _Network, slept: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    network.failures[_MINT] = [500, 500]

    with caplog.at_level(logging.WARNING):
        secrets = await _provision()

    _assert_usable(secrets)
    assert network.sent.count(_MINT) == 3
    assert len(slept) == 2
    # Exponential: ~5 s then ~10 s, each stretched by at most the jitter.
    assert 5.0 <= slept[0] <= 6.0
    assert 10.0 <= slept[1] <= 12.0
    assert "status=500" in caplog.text


@pytest.mark.anyio
async def test_a_mint_whose_response_dropped_then_201_succeeds(network: _Network) -> None:
    network.failures[_MINT] = [_DROPPED]

    secrets = await _provision()

    _assert_usable(secrets)
    assert network.sent.count(_MINT) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 503])
async def test_a_mint_honours_retry_after(
    network: _Network, slept: list[float], status: int
) -> None:
    network.failures[_MINT] = [
        httpx.Response(status, headers={"Retry-After": "7"}, json={"message": "slow down"})
    ]

    secrets = await _provision()

    _assert_usable(secrets)
    assert slept == [7.0]
    assert network.sent.count(_MINT) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
async def test_a_mint_that_stays_unavailable_fails_resumable_naming_its_attempts(
    network: _Network, status: int
) -> None:
    """The run that found 500/429 recorded as AUTH: it is UNAVAILABLE, and resumable."""
    network.failures[_MINT] = [status] * MINT_ATTEMPTS

    with pytest.raises(GitHubUnavailableError) as raised:
        await _provision()

    assert not isinstance(raised.value, GitHubAuthError)
    assert network.sent.count(_MINT) == MINT_ATTEMPTS
    assert f"after {MINT_ATTEMPTS} attempt(s)" in str(raised.value)
    assert raised.value.status_code == status
    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.UNAVAILABLE
    assert account.upstream.is_transient
    assert not account.upstream.needs_operator


@pytest.mark.anyio
@pytest.mark.parametrize("retry_after", [None, "3600"])
async def test_the_whole_mint_backoff_ends_inside_the_setup_phase_timeout(
    network: _Network,
    slept: list[float],
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str | None,
) -> None:
    """Worst case - every jitter at its ceiling, or GitHub asking for an hour - stays bounded."""
    monkeypatch.setattr(random, "uniform", lambda _low, high: high)
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    network.failures[_MINT] = [
        httpx.Response(500, headers=headers, json={"message": "scripted"})
        for _ in range(MINT_ATTEMPTS)
    ]

    with pytest.raises(GitHubUnavailableError):
        await _provision()

    setup_timeout = Settings().setup_phase_timeout_seconds
    assert sum(slept) <= MINT_BACKOFF_BUDGET_SECONDS < setup_timeout
    # Spans most of the budget, so a burst of ~1 min is ridden out.
    assert sum(slept) >= 75.0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "failure", "sends"),
    [
        (_LOOKUP, _DROPPED, 3),
        (_LOOKUP, _TruncatedBody(200), 3),
        (_MINT, httpx.ConnectError("refused"), MINT_ATTEMPTS),
        (_MINT, _DROPPED, MINT_ATTEMPTS),
    ],
)
async def test_an_exhausted_retry_fails_as_transient_not_as_auth(
    network: _Network,
    path: str,
    failure: _Failure,
    sends: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Before #1593 a dropped mint surfaced as GitHubAuthError: an operator problem."""
    network.failures[path] = [failure] * sends

    with caplog.at_level(logging.WARNING), pytest.raises(GitHubUnavailableError) as raised:
        await _provision()

    assert not isinstance(raised.value, GitHubAuthError)
    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.UNAVAILABLE
    assert account.upstream.is_transient
    assert not account.upstream.needs_operator
    assert network.sent.count(path) == sends
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
async def test_a_post_whose_response_dropped_is_sent_once(network: _Network) -> None:
    """GitHub may already have acted on it: a second comment is a second comment."""
    network.failures["/repos/org/repo-a/issues"] = [_DROPPED]
    client = GitHubAppClient(_Settings(), transport=httpx.MockTransport(network.handle))  # type: ignore[arg-type]

    with pytest.raises(GitHubUnavailableError):
        await client._http.post("/repos/org/repo-a/issues", json={"title": "x"})

    assert network.sent == ["/repos/org/repo-a/issues"]


@pytest.mark.anyio
async def test_a_post_whose_body_broke_off_is_sent_once(network: _Network) -> None:
    """The headers came back, so GitHub acted: the read error must not resend it."""
    network.failures["/repos/org/repo-a/issues"] = [_TruncatedBody(201)]
    client = GitHubAppClient(_Settings(), transport=httpx.MockTransport(network.handle))  # type: ignore[arg-type]

    with pytest.raises(GitHubUnavailableError):
        await client._http.post("/repos/org/repo-a/issues", json={"title": "x"})

    assert network.sent == ["/repos/org/repo-a/issues"]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [500, 502, 429, _DROPPED])
async def test_any_other_post_is_never_resent_after_github_may_have_acted(
    network: _Network, failure: _Failure
) -> None:
    """The mint exception does not leak: a second comment is still a second comment."""
    path = "/repos/org/repo-a/issues"
    network.failures[path] = [failure]
    client = GitHubAppClient(_Settings(), transport=httpx.MockTransport(network.handle))  # type: ignore[arg-type]

    with contextlib.suppress(GitHubUnavailableError):
        await client._http.post(path, json={"title": "x"})

    assert network.sent == [path]


@pytest.mark.anyio
async def test_a_post_to_a_lookalike_path_gets_no_mint_retries(network: _Network) -> None:
    path = "/app/installations/7/access_tokens/extra"
    network.failures[path] = [500]
    client = GitHubAppClient(_Settings(), transport=httpx.MockTransport(network.handle))  # type: ignore[arg-type]

    response = await client._http.post(path, json={})

    assert response.status_code == 500
    assert network.sent == [path]
