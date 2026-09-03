"""Evidence that an agent process existed, taken from the stream itself.

The fact "an agent ran" is only worth recording if it cannot be wrong, because
the whole point of it is to license a claim to a user - that a session never
started - which is otherwise indistinguishable from a log we simply cannot
read (#1047, #1065).

Deciding to start a process is not evidence that one started. Everything
between the decision and the process can still fail: the container is gone,
the image has no such binary, the exec is refused. So the signal is taken from
the one place that can only happen after creation succeeded - the stream
advancing.

An advance that returns, whether it carries a line or ends the stream, means
the subprocess was created and its output pipe was read to completion. An
advance that raises means it was not. An agent that starts and dies before
printing anything therefore still counts as launched, which is exactly the
case a line-counting signal would get wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class AgentLaunchObserver(Protocol):
    """Notified once, when an agent process is known to have existed.

    Called at most once per stream and never on the failure path. Must not
    raise: it runs inside the agent's own output loop, and the launch record
    is not worth failing a live agent over.
    """

    async def __call__(self) -> None: ...


async def observing_launch(
    stream: AsyncIterator[str],
    observer: AgentLaunchObserver | None,
) -> AsyncIterator[str]:
    """Yield from ``stream``, notifying ``observer`` once it first advances.

    Transparent otherwise: lines pass through untouched and every exception
    propagates unchanged, including one raised by the first advance - which is
    precisely the case where nothing is reported, because nothing started.
    """
    iterator = stream.__aiter__()
    launched = False
    while True:
        try:
            line: str | None = await iterator.__anext__()
        except StopAsyncIteration:
            # The stream ended without producing anything, which is still an
            # advance that returned: the process ran and printed nothing.
            line = None

        if not launched:
            launched = True
            if observer is not None:
                await observer()

        if line is None:
            return
        yield line


class SupportsMarkLaunched(Protocol):
    """Anything that can record a launch for one session."""

    async def mark_launched(self) -> None: ...


def observer_for(manager: SupportsMarkLaunched | None) -> AgentLaunchObserver | None:
    """The observer to notify for a phase, or None when there is nobody to tell.

    A phase with no session manager has no session to record anything against,
    and that absence is the caller's normal case rather than an error - so it
    is decided here, once, instead of at each call site.
    """
    return None if manager is None else manager.mark_launched
