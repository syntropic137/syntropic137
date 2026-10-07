"""Retrying transport for the GitHub App client (#1593).

One dropped keep-alive connection during provisioning used to fail a whole
execution: `SetupPhaseSecrets.create` looks up installations and mints tokens
through `GitHubAppClient`, and nothing between it and the socket tried twice.
Pooled HTTP/1.1 connections that GitHub closed while idle make that drop
routine rather than rare.

This sits under every request `GitHubAppClient` sends, so no call site decides
anything about retrying. What it decides:

- WHAT IS TRANSIENT: a connection that dropped, could not be made, or failed
  or timed out reading or writing - the response body included - and a 502, 503 or 504. Never a 4xx - those are GitHub's answer
  about the request, and asking again gets the same answer.
- WHAT MAY BE SENT AGAIN: an idempotent method after any transient failure.
  Any other request only after a failure that proves GitHub never received
  it - the connection could not be made. A dropped response, a read or write
  error or timeout, or a 5xx may come AFTER GitHub acted: a second comment is
  a second comment. No caller can opt out of that.
- THE ONE EXCEPTION, THE TOKEN MINT (owner decision, 2026-10-07):
  ``POST /app/installations/{id}/access_tokens`` is also sent again after a
  dropped response, a 5xx or a 429, on a longer `TokenMintRetryPolicy`
  (5 attempts, ~5/10/20/40 s, Retry-After honoured), all inside a deadline of
  3/4 of the configured setup phase timeout that counts request time as well
  as waits. The cost is
  accepted knowingly: GitHub may have minted a token we never received - an
  orphan, scoped to the requested repos and permissions, live for about an
  hour, which the #725 ledger cannot revoke because it never saw it. The
  alternative was worse: GitHub's mint endpoint returned 500 in short bursts
  (2026-10-07: 6 phase failures, 111 of 116 mints succeeded) and resumes
  landed inside the same bursts. Every resend is logged at WARNING saying an
  orphan may exist.
- WHAT A CALLER SEES WHEN IT GIVES UP: `GitHubUnavailableError`, whatever the
  transient failure was. Before this, a dropped connection during minting
  surfaced as `GitHubAuthError` - an operator problem - when resuming the run
  was all it needed.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_TRANSIENT_STATUSES = frozenset({502, 503, 504})
#: Failed before a byte of the request reached GitHub: safe to send anything again.
#: No connection was made, or none was free in the pool to send it on.
_UNSENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
#: Failed after the request may have reached GitHub: safe only for idempotent methods.
#: Whole httpx families, not a list of members: every read or write error and
#: timeout, and a peer that broke the protocol, may come after GitHub acted. A
#: member missing from a hand list (#1611: ReadError) escaped as an auth fault.
#: `_UNSENT_ERRORS` is checked first, so its members never count as ambiguous.
_AMBIGUOUS_ERRORS = (httpx.NetworkError, httpx.TimeoutException, httpx.RemoteProtocolError)

#: The installation-token mint: the one non-idempotent request sent again
#: after GitHub may have acted (owner decision, 2026-10-07).
_TOKEN_MINT_PATH = re.compile(r"/app/installations/[^/]+/access_tokens")
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR_FIRST = 500
_HTTP_SERVER_ERROR_LAST = 599

#: Token-mint retry shape: 5 attempts waiting ~5, 10, 20, 40 s (75 s nominal),
#: each stretched by up to 10 % jitter (82.5 s at most), so all five fit the
#: default deadline below when GitHub answers promptly.
MINT_ATTEMPTS = 5
MINT_BASE_DELAY_SECONDS = 5.0
MINT_JITTER_FRACTION = 0.1
#: The whole mint - every request, every wait, Retry-After included - must end
#: within this share of the CONFIGURED setup phase timeout (90 s of the 120 s
#: default). The rest is the margin for everything else provisioning does.
MINT_DEADLINE_FRACTION_OF_SETUP_TIMEOUT = 0.75
#: An attempt is not started with less than this left before the deadline: it
#: could not get an answer in time, and would only mint another orphan.
MINT_MIN_ATTEMPT_SECONDS = 5.0


def is_token_mint(request: httpx.Request) -> bool:
    """Whether this is ``POST /app/installations/{id}/access_tokens``."""
    return request.method == "POST" and _TOKEN_MINT_PATH.fullmatch(request.url.path) is not None


def is_mint_retryable_status(status_code: int) -> bool:
    """A 429 or any 5xx: GitHub failed to answer the mint, rather than refused it."""
    return (
        status_code == _HTTP_TOO_MANY_REQUESTS
        or _HTTP_SERVER_ERROR_FIRST <= status_code <= _HTTP_SERVER_ERROR_LAST
    )


def retry_after_seconds(response: httpx.Response) -> float | None:
    """The wait GitHub asked for in ``Retry-After``, in seconds, or None when it asked none.

    Both forms RFC 9110 allows: delay-seconds and an HTTP-date.
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _now() -> float:
    """Monotonic seconds; the mint deadline's clock. A module function so tests can fake it."""
    return time.monotonic()


def _setup_phase_timeout_seconds() -> float:
    """The configured setup phase timeout (``SETUP_PHASE_TIMEOUT_SECONDS``)."""
    from syn_shared.settings import get_settings

    return float(get_settings().setup_phase_timeout_seconds)


async def _sleep(seconds: float) -> None:
    """Back off without blocking the API's event loop. Never `time.sleep`."""
    await asyncio.sleep(seconds)


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to ask, and how long to wait between asking.

    The wait before attempt n+1 is drawn uniformly from
    ``[0, min(max_delay, base_delay * 2**(n-1))]`` ("full jitter"), so many
    workspaces provisioning at once do not reconnect in lockstep.
    """

    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 4.0

    def delay_after(self, attempt: int) -> float:
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * 2 ** (attempt - 1))
        return random.uniform(0, ceiling)


@dataclass(frozen=True)
class TokenMintRetryPolicy:
    """How long to keep minting an installation token through a GitHub 5xx burst.

    The wait before attempt n+1 is ``base_delay * 2**(n-1)`` stretched by up to
    ``jitter_fraction``, or the server's Retry-After when it sent one. All of it
    - requests and waits - runs against one monotonic deadline: ``deadline_seconds``
    when set, else `MINT_DEADLINE_FRACTION_OF_SETUP_TIMEOUT` of the configured
    setup phase timeout. The mint gives up rather than outlive the setup phase
    that is waiting on it.
    """

    attempts: int = MINT_ATTEMPTS
    base_delay_seconds: float = MINT_BASE_DELAY_SECONDS
    jitter_fraction: float = MINT_JITTER_FRACTION
    deadline_seconds: float | None = None
    min_attempt_seconds: float = MINT_MIN_ATTEMPT_SECONDS

    def deadline(self) -> float:
        """Seconds the whole mint may take, read when the mint starts."""
        if self.deadline_seconds is not None:
            return self.deadline_seconds
        return _setup_phase_timeout_seconds() * MINT_DEADLINE_FRACTION_OF_SETUP_TIMEOUT

    def delay_after(self, attempt: int, retry_after: float | None) -> float:
        """Seconds to wait before attempt ``attempt + 1``."""
        if retry_after is not None:
            return retry_after
        nominal = self.base_delay_seconds * 2 ** (attempt - 1)
        return nominal * (1 + random.uniform(0, self.jitter_fraction))


class RetryingTransport(httpx.AsyncBaseTransport):
    """Sends each request up to `policy.attempts` times while GitHub is transiently unavailable.

    Raises:
        GitHubUnavailableError: GitHub stayed unavailable for every attempt the
            request was allowed. Any other answer, 4xx included, is returned
            unchanged after the first attempt that produced it.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        policy: RetryPolicy | None = None,
        *,
        mint_policy: TokenMintRetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._mint_policy = mint_policy or TokenMintRetryPolicy()
        self._sleep = sleep or _sleep

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if is_token_mint(request):
            return await self._mint(request)
        return await self._send(request)

    async def _send(self, request: httpx.Request) -> httpx.Response:
        idempotent = request.method in _IDEMPOTENT_METHODS
        attempts = self._policy.attempts
        failure = ""
        last_error: Exception | None = None
        status_code: int | None = None
        attempt = 0
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                logger.warning(
                    "GitHub %s %s attempt %d/%d failed (%s); retrying",
                    request.method,
                    request.url.path,
                    attempt - 1,
                    attempts,
                    failure,
                )
                await self._sleep(self._policy.delay_after(attempt - 1))
            try:
                response = await self._inner.handle_async_request(request)
                if response.status_code not in _TRANSIENT_STATUSES:
                    return await _buffered(response)
            except (*_UNSENT_ERRORS, *_AMBIGUOUS_ERRORS) as exc:
                failure = f"{type(exc).__name__}: {exc}"
                last_error = exc
                status_code = None
                unsent = isinstance(exc, _UNSENT_ERRORS)
            else:
                await response.aclose()
                failure = f"HTTP {response.status_code}"
                last_error = None
                status_code = response.status_code
                unsent = False
            if not (idempotent or unsent):
                break
        raise _unavailable(request, attempt, failure, status_code) from last_error

    async def _mint(self, request: httpx.Request) -> httpx.Response:
        """Mint a token, resending through 5xx, 429 and lost responses (owner decision, 2026-10-07).

        A 4xx other than 429 is GitHub's answer about the App and is returned
        at once for the caller to classify. No token value is ever logged: a
        response is only read here when it is not retried.

        Every attempt is capped to the time left before the deadline, and none
        is started - nor any wait begun - unless it can finish before it. The
        error then names the attempts actually made.
        """
        policy = self._mint_policy
        deadline = _now() + policy.deadline()
        failure = ""
        last_error: Exception | None = None
        status_code: int | None = None
        retry_after: float | None = None
        made = 0
        for attempt in range(1, policy.attempts + 1):
            if attempt == 1:
                # The first attempt always runs, given at least the minimum.
                remaining = max(deadline - _now(), policy.min_attempt_seconds)
            else:
                outcome = _Outcome(made, failure, status_code)
                waited = await self._wait_to_retry(request, deadline, outcome, retry_after)
                if waited is None:
                    break
                remaining = waited
            _cap_timeouts(request, remaining)
            made = attempt
            try:
                async with asyncio.timeout(remaining):
                    response = await self._inner.handle_async_request(request)
                    if not is_mint_retryable_status(response.status_code):
                        return await _buffered(response)
                    retry_after = retry_after_seconds(response)
                    await response.aclose()
            except (*_UNSENT_ERRORS, *_AMBIGUOUS_ERRORS, TimeoutError) as exc:
                failure = f"{type(exc).__name__}: {exc}"
                last_error = exc
                status_code = None
                retry_after = None
            else:
                failure = f"HTTP {response.status_code}"
                last_error = None
                status_code = response.status_code
        raise _unavailable(request, made, failure, status_code) from last_error

    async def _wait_to_retry(
        self,
        request: httpx.Request,
        deadline: float,
        last: _Outcome,
        retry_after: float | None,
    ) -> float | None:
        """Back off before the next mint attempt; the seconds left for it, or None to stop.

        Checked twice: before the wait, whether the wait leaves time for an
        attempt; after it, whether it still does - a loaded event loop can
        wake late, and a retry must never run past the deadline.
        """
        policy = self._mint_policy
        delay = policy.delay_after(last.attempts, retry_after)
        if deadline - (_now() + delay) < policy.min_attempt_seconds:
            _log_mint_stop(request, policy, last, f"waiting {delay:.1f}s would leave too little")
            return None
        logger.warning(
            "GitHub token mint %s attempt %d/%d failed (status=%s, %s); retrying in "
            "%.1fs. GitHub may already have minted a token we never received: an "
            "orphan, live for up to an hour, that the issuance ledger cannot revoke "
            "(accepted trade-off, owner decision 2026-10-07)",
            request.url.path,
            last.attempts,
            policy.attempts,
            _status_text(last.status_code),
            last.failure,
            delay,
        )
        await self._sleep(delay)
        remaining = deadline - _now()
        if remaining < policy.min_attempt_seconds:
            _log_mint_stop(
                request, policy, last, f"the wait overran, {max(remaining, 0.0):.1f}s left"
            )
            return None
        return remaining

    async def aclose(self) -> None:
        await self._inner.aclose()


@dataclass(frozen=True)
class _Outcome:
    """How the mint's attempts so far ended: how many, and how the last failed."""

    attempts: int
    failure: str
    status_code: int | None


def _log_mint_stop(
    request: httpx.Request, policy: TokenMintRetryPolicy, last: _Outcome, why: str
) -> None:
    logger.warning(
        "GitHub token mint %s: not retrying after attempt %d/%d (status=%s, %s); %s "
        "before the deadline",
        request.url.path,
        last.attempts,
        policy.attempts,
        _status_text(last.status_code),
        last.failure,
        why,
    )


def _status_text(status_code: int | None) -> str:
    return "none" if status_code is None else str(status_code)


def _cap_timeouts(request: httpx.Request, seconds: float) -> None:
    """Shrink every httpx timeout on this request to at most ``seconds``."""
    current = request.extensions.get("timeout")
    capped: dict[str, float] = {}
    for phase in ("connect", "read", "write", "pool"):
        value = current.get(phase) if isinstance(current, dict) else None
        capped[phase] = seconds if not isinstance(value, int | float) else min(value, seconds)
    request.extensions["timeout"] = capped


def _unavailable(
    request: httpx.Request,
    attempts: int,
    failure: str,
    status_code: int | None,
) -> Exception:
    from syn_adapters.github.client import GitHubUnavailableError

    msg = (
        f"GitHub unavailable after {attempts} attempt(s) of {request.method} "
        f"{request.url.path}: {failure}. Transient; resuming the execution retries it."
    )
    return GitHubUnavailableError(msg, status_code=status_code)


async def _buffered(response: httpx.Response) -> httpx.Response:
    """Read the whole body here, so a body that breaks off fails inside the retry boundary.

    The inner transport returns once the headers arrive; httpx reads the body
    later, outside `handle_async_request`. A connection that drops mid-body
    would otherwise escape as a raw `ReadError` after one attempt (#1611).
    httpx serves a response whose body is already read from what it read.
    """
    try:
        await response.aread()
    finally:
        await response.aclose()
    return response
