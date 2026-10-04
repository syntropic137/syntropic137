"""Liveness is not readiness: how the API starts without failing its health check (#1575).

Startup used to be awaited whole inside the FastAPI lifespan, and uvicorn
serves nothing - not even ``/health`` - until the lifespan yields. So a long
one-time migration (the #1558 usage-rollup backfill took ~2 minutes on
production data) looked exactly like a dead process: the compose health check
failed, the gateway's ``depends_on: service_healthy`` never started it, and the
pit stop aborted with the platform half up.

The gate separates the two questions the health check was being asked:

* LIVENESS - is the process alive and making progress? ``/health`` and
  ``/version`` are always served, and ``/health`` reports ``status: starting``
  while startup runs. This is what the container health check reads.
* READINESS - may it serve the API? Every other route is refused with 503 until
  startup has finished. Nothing reads a half-migrated store, so the guarantees
  each migration makes about its own completion (#1558's completion mark)
  are untouched: they still finish before a single read is served.

A startup that finishes inside the grace window behaves exactly as before,
including the fail-fast: a failure raises out of the lifespan and uvicorn
refuses to serve. Only a startup that outlives the window continues in the
background, and if THAT fails the process terminates itself so the restart
policy runs it again - a slow start is waited for, a failed one is not hidden.

Before the lifespan has run at all (an ASGI transport in a test, for one) the
gate is not in the way: it refuses only while a startup is actually in flight.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING, Literal

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

StartupPhase = Literal["not_started", "starting", "ready", "failed"]

#: How long the lifespan waits for startup before it begins serving liveness.
#: Well inside the compose ``start_period``, so a normal start never shows
#: ``starting`` at all, and a failure in it still aborts before serving.
DEFAULT_GRACE_SECONDS = 5.0

#: Answered in every phase: they read no state that startup builds.
ALWAYS_SERVED = frozenset({"/health", "/version"})


def _terminate_process() -> None:
    signal.raise_signal(signal.SIGTERM)


class StartupGate:
    """Runs startup, and answers whether the API may serve a given path yet."""

    def __init__(
        self,
        *,
        grace_seconds: float | None = None,
        on_late_failure: Callable[[], None] = _terminate_process,
    ) -> None:
        # Read at construction, not bound at definition, so a test can shorten
        # the window of the gate create_app() builds.
        self._grace_seconds = DEFAULT_GRACE_SECONDS if grace_seconds is None else grace_seconds
        self._on_late_failure = on_late_failure
        self._phase: StartupPhase = "not_started"
        self._error: BaseException | None = None
        self._backgrounded = False
        self._task: asyncio.Task[None] | None = None

    @property
    def phase(self) -> StartupPhase:
        return self._phase

    def refuses(self, path: str) -> bool:
        """Whether a request for ``path`` must be turned away right now."""
        return self._phase in ("starting", "failed") and path not in ALWAYS_SERVED

    async def open(self, start: Callable[[], Awaitable[None]]) -> None:
        """Run ``start``, which raises on failure.

        Returns once startup has finished or the grace window has passed,
        whichever is first. Raises if startup failed inside the window.
        """
        self._phase = "starting"
        self._task = asyncio.create_task(self._run(start))
        await asyncio.wait({self._task}, timeout=self._grace_seconds)
        if self._error is not None:
            raise self._error
        if self._phase == "starting":
            # Synchronously after the wait, so _run cannot fail in between and
            # miss this flag.
            self._backgrounded = True
            logger.warning(
                "Startup still running after %.0fs (a long migration?); serving /health "
                "as 'starting' and refusing every other route until it finishes",
                self._grace_seconds,
            )

    async def close(self) -> None:
        """Stop a startup still in flight. A migration it interrupts resumes
        on the next start; each one is responsible for being rerunnable."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, start: Callable[[], Awaitable[None]]) -> None:
        try:
            await start()
        except Exception as exc:
            self._phase = "failed"
            self._error = exc
            if self._backgrounded:
                logger.error("Startup failed after serving began - terminating: %s", exc)
                self._on_late_failure()
            return
        self._phase = "ready"
        if self._backgrounded:
            logger.info("Startup finished; serving every route")


class StartupGateMiddleware:
    """Refuses every route the gate refuses with 503 and a Retry-After."""

    def __init__(self, app: ASGIApp, gate: StartupGate) -> None:
        self.app = app
        self._gate = gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._gate.refuses(scope["path"]):
            response = JSONResponse(
                {"status": self._gate.phase, "detail": "The API is starting; retry shortly."},
                status_code=503,
                headers={"Retry-After": "15"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
