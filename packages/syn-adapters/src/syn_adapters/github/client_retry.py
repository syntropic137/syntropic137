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
- WHAT MAY BE SENT AGAIN: idempotent methods, plus any request its caller
  marked with `RETRY_SAFE`. A POST is not idempotent in general (a second
  comment is a second comment), so the transport cannot assume it is.
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

#: Request extension a caller sets when a non-idempotent request is still safe
#: to send twice: `extensions=RETRY_SAFE`.
RETRY_SAFE: dict[str, object] = {"syn_retry_safe": True}

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_TRANSIENT_STATUSES = frozenset({502, 503, 504})
_TRANSIENT_ERRORS = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout)


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

        safe = request.method in _IDEMPOTENT_METHODS or bool(
            request.extensions.pop("syn_retry_safe", False)
        )
        attempts = self._policy.attempts if safe else 1
        failure = ""
        last_error: Exception | None = None
        status_code: int | None = None
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
            except _TRANSIENT_ERRORS as exc:
                failure = f"{type(exc).__name__}: {exc}"
                last_error = exc
                status_code = None
                continue
            if response.status_code not in _TRANSIENT_STATUSES:
                return response
            await response.aclose()
            failure = f"HTTP {response.status_code}"
            last_error = None
            status_code = response.status_code
        msg = (
            f"GitHub unavailable after {attempts} attempt(s) of {request.method} "
            f"{request.url.path}: {failure}. Transient; resuming the execution retries it."
        )
        raise GitHubUnavailableError(msg, status_code=status_code) from last_error

    async def aclose(self) -> None:
        await self._inner.aclose()
