"""Retrying transport for the GitHub App client (#1593).

One dropped keep-alive connection during provisioning used to fail a whole
execution: `SetupPhaseSecrets.create` looks up installations and mints tokens
through `GitHubAppClient`, and nothing between it and the socket tried twice.
Pooled HTTP/1.1 connections that GitHub closed while idle make that drop
routine rather than rare.

This sits under every request `GitHubAppClient` sends, so no call site decides
anything about retrying. What it decides:

- WHAT IS TRANSIENT: a connection that dropped, could not be made or timed
  out reading, and a 502, 503 or 504. Never a 4xx - those are GitHub's answer
  about the request, and asking again gets the same answer.
- WHAT MAY BE SENT AGAIN: an idempotent method after any transient failure.
  Any other request only after a failure that proves GitHub never received
  it - the connection could not be made. A dropped response, a read timeout
  or a 5xx may come AFTER GitHub acted: a second comment is a second comment,
  and a second token mint is a second live credential nobody holds and so
  nobody can revoke. No caller can opt out of that.
- WHAT A CALLER SEES WHEN IT GIVES UP: `GitHubUnavailableError`, whatever the
  transient failure was. Before this, a dropped connection during minting
  surfaced as `GitHubAuthError` - an operator problem - when resuming the run
  was all it needed.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_TRANSIENT_STATUSES = frozenset({502, 503, 504})
#: Failed before a byte of the request reached GitHub: safe to send anything again.
_UNSENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
#: Failed after the request may have reached GitHub: safe only for idempotent methods.
_AMBIGUOUS_ERRORS = (httpx.RemoteProtocolError, httpx.ReadTimeout)


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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._sleep = sleep

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from syn_adapters.github.client import GitHubUnavailableError

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
            except (*_UNSENT_ERRORS, *_AMBIGUOUS_ERRORS) as exc:
                failure = f"{type(exc).__name__}: {exc}"
                last_error = exc
                status_code = None
                unsent = isinstance(exc, _UNSENT_ERRORS)
            else:
                if response.status_code not in _TRANSIENT_STATUSES:
                    return response
                await response.aclose()
                failure = f"HTTP {response.status_code}"
                last_error = None
                status_code = response.status_code
                unsent = False
            if not (idempotent or unsent):
                break
        msg = (
            f"GitHub unavailable after {attempt} attempt(s) of {request.method} "
            f"{request.url.path}: {failure}. Transient; resuming the execution retries it."
        )
        raise GitHubUnavailableError(msg, status_code=status_code) from last_error

    async def aclose(self) -> None:
        await self._inner.aclose()
