"""Evidence that an agent process existed, taken from that process.

The fact "an agent ran" licenses one specific statement to a user - that a
session never started, so its missing log is not lost data (#1047, #1065). A
claim that strong may only rest on evidence nothing but the process itself can
produce.

Deciding to start a process is not that evidence, and neither is the transport
that was asked to. `docker exec` merges its own stderr into the agent's stdout,
so a client-side "No such container" arrives as an ordinary line; a refused
exec ends the stream at once. From outside, both are indistinguishable from an
agent that ran and said nothing, so a signal taken from the stream advancing
proves only that a docker exec client started - the one thing never in doubt.

So the process speaks for itself. The transport wraps the phase command so that
a process created INSIDE the workspace prints ``AGENT_LAUNCH_MARKER`` before it
becomes the agent, and that line is the only thing counted here. A client that
never reached the container ran nothing that could print it, and an agent that
dies before its first output has already announced itself - which is the case a
signal counted from agent output would get wrong.

A transport that creates no process - a replayed recording, an in-memory double
- emits no marker and leaves the session UNKNOWN. That is right rather than a
gap: it has no standing to attest a launch, and UNKNOWN is the state that
exists for having no evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


AGENT_LAUNCH_MARKER = "__syn_agent_launched__"
"""Printed by a process inside the workspace, immediately before it execs the agent.

Part of the event stream contract: a transport that really creates a process
emits this line first, and nothing else in the stream means a launch.
``observing_launch`` consumes it, so it never reaches a stream processor. An
agent that echoed it would only be attesting its own existence, which is why
no escaping or nonce is needed.
"""


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
    """Yield from ``stream``, notifying ``observer`` when the agent announces itself.

    Transparent otherwise: every other line passes through untouched and every
    exception propagates unchanged. A stream that ends without the marker
    reports nothing at all, which is what keeps a failed exec distinguishable
    from a silent agent.
    """
    launched = False
    async for line in stream:
        if line != AGENT_LAUNCH_MARKER:
            yield line
            continue
        if not launched:
            launched = True
            if observer is not None:
                await observer()


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
