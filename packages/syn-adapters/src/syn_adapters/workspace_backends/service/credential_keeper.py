"""Keeping the agent's GitHub credential alive for as long as the agent runs (#725).

AN INSTALLATION TOKEN LIVES SIXTY MINUTES AND A PHASE MAY RUN LONGER. Renewal
used to happen only at the two ends of a phase - the quarantine rehearsal at
startup and the quarantine push at teardown (#1393) - so an agent that pushed
at minute seventy was pushing with a dead token, and lost the push.

So while the agent runs, the credential is renewed on a schedule: first at
``FIRST_RENEWAL`` (forty minutes, a third of the token's life to spare), then
every ``RENEWAL_INTERVAL`` after the last success. A renewal that fails is
retried every ``RETRY_INTERVAL`` until one succeeds or the installed token
expires. If it expires first, that is reported - a log warning naming the
phase and an observability event through ``on_lapse`` - because an agent
holding a dead credential and nobody knowing is precisely the failure this
exists to end. It then goes back to the normal cadence rather than giving up:
a later renewal that succeeds still rescues the rest of the phase.

PHASE-SCOPED AND IN-PROCESS, BY THE CRASH MODEL IN AGENTS.md. This is
infrastructure state tied to one live container, not domain state: after a
crash the container is gone and so is anything this would be renewing. It
is therefore an ``asyncio`` task owned by whoever runs the agent, started as
the agent starts and cancelled as it stops, and never a durable
ProcessManager.

THE CREDENTIAL IS REPLACED, NEVER REVOKED, HERE. A push in flight when a
renewal lands authenticated with the old token; revoking it would fail that
push for no gain, since it expires on its own. Revocation is teardown's job,
once nothing in the container can be using any of them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger(__name__)

#: A third of an installation token's hour left at first renewal, so that the
#: retries below have twenty minutes to succeed in before the credential dies.
FIRST_RENEWAL: Final[timedelta] = timedelta(minutes=40)
RENEWAL_INTERVAL: Final[timedelta] = timedelta(minutes=40)
#: Short enough for six attempts inside the margin above; long enough that a
#: GitHub outage is not met with a request every few seconds.
RETRY_INTERVAL: Final[timedelta] = timedelta(minutes=3)


@dataclass(frozen=True)
class CredentialLapse:
    """The agent's credential expired and no renewal succeeded in time."""

    expired_at: datetime | None
    """When the installed token expired, or None if the workspace never
    reported one - which, for a renewal that is failing, is itself a lapse."""
    attempts: int
    """Renewals attempted since the last success, all of which failed."""
    last_error: str


class RenewableWorkspace(Protocol):
    """What the keeper needs of a workspace: renew it, and say when it expires."""

    @property
    def workspace_id(self) -> str: ...

    @property
    def credential_expires_at(self) -> datetime | None: ...

    async def renew_git_credential(self) -> object: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _sleep(delay: timedelta) -> None:
    await asyncio.sleep(max(delay.total_seconds(), 0.0))


@contextlib.asynccontextmanager
async def keep_credential_fresh(
    workspace: RenewableWorkspace,
    *,
    on_lapse: Callable[[CredentialLapse], Awaitable[None]],
    now: Callable[[], datetime] = _utc_now,
    sleep: Callable[[timedelta], Awaitable[None]] = _sleep,
) -> AsyncIterator[None]:
    """Renew ``workspace``'s credential on schedule for the duration of the block.

    The schedule starts when the block is entered, which is when the agent
    starts; it is cancelled when the block exits, however it exits. ``now``
    and ``sleep`` are the clock, injectable so the schedule can be tested
    without waiting forty minutes.
    """
    task = asyncio.create_task(
        _renew_on_schedule(workspace, on_lapse=on_lapse, now=now, sleep=sleep),
        name=f"credential-keeper-{workspace.workspace_id}",
    )
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _renew_on_schedule(
    workspace: RenewableWorkspace,
    *,
    on_lapse: Callable[[CredentialLapse], Awaitable[None]],
    now: Callable[[], datetime],
    sleep: Callable[[timedelta], Awaitable[None]],
) -> None:
    """The schedule itself. Runs until cancelled; nothing but cancellation ends it.

    Every failure is caught and handled here, including one from ``on_lapse``:
    the task is not awaited until the phase ends, so an exception escaping it
    would sit unobserved for the rest of the phase while renewal silently
    stopped - the exact outcome this module exists to prevent.
    """
    await sleep(FIRST_RENEWAL)
    while True:
        await _renew_until_success_or_expiry(workspace, on_lapse=on_lapse, now=now, sleep=sleep)
        await sleep(RENEWAL_INTERVAL)


async def _renew_until_success_or_expiry(
    workspace: RenewableWorkspace,
    *,
    on_lapse: Callable[[CredentialLapse], Awaitable[None]],
    now: Callable[[], datetime],
    sleep: Callable[[timedelta], Awaitable[None]],
) -> None:
    """One renewal, retried every ``RETRY_INTERVAL`` while the installed token lives."""
    attempts = 0
    while True:
        attempts += 1
        try:
            await workspace.renew_git_credential()
            return
        except asyncio.CancelledError:
            raise
        except Exception as unrenewed:
            last_error = str(unrenewed) or type(unrenewed).__name__
        expires_at = workspace.credential_expires_at
        if expires_at is not None and now() + RETRY_INTERVAL < expires_at:
            logger.info(
                "Could not renew the git credential in workspace %s (attempt %d): %s. "
                "Retrying in %s; the installed token expires at %s.",
                workspace.workspace_id,
                attempts,
                last_error,
                RETRY_INTERVAL,
                expires_at.isoformat(),
            )
            await sleep(RETRY_INTERVAL)
            continue
        if expires_at is not None:
            await sleep(expires_at - now())
        await _report_lapse(
            workspace,
            CredentialLapse(expired_at=expires_at, attempts=attempts, last_error=last_error),
            on_lapse,
        )
        return


async def _report_lapse(
    workspace: RenewableWorkspace,
    lapse: CredentialLapse,
    on_lapse: Callable[[CredentialLapse], Awaitable[None]],
) -> None:
    """Say, loudly and in two places, that the agent's credential is dead."""
    logger.warning(
        "The git credential in workspace %s EXPIRED at %s and could not be renewed "
        "after %d attempt(s): %s. The agent's git and gh calls will fail until a "
        "renewal succeeds (#725).",
        workspace.workspace_id,
        lapse.expired_at.isoformat() if lapse.expired_at is not None else "an unknown time",
        lapse.attempts,
        lapse.last_error,
    )
    try:
        await on_lapse(lapse)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Could not record the credential lapse in workspace %s; the warning above "
            "is the only record of it.",
            workspace.workspace_id,
        )
