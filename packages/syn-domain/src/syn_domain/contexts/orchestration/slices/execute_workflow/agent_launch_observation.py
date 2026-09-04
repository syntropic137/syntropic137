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

The marker is announced BEFORE the exec that makes the announcer into the
agent, so on its own it attests an intention rather than a fact: the exec can
still fail, and then a shell has claimed a launch that never happened (#1065).
Nothing the wrapper can ask before ``exec`` closes that gap - every such check
is a prediction of what the kernel is about to do, and a script whose shebang
interpreter is missing satisfies resolution, regular-file and executable-bit
checks alike and then fails ``exec`` anyway. So the marker is held PROVISIONAL
instead of tested, and the outcome settles it afterwards. See
``AgentLaunchEvidence``.

A transport that creates no process - a replayed recording, an in-memory double
- emits no marker and leaves the session UNKNOWN. That is right rather than a
gap: it has no standing to attest a launch, and UNKNOWN is the state that
exists for having no evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


AGENT_LAUNCH_MARKER = "__syn_agent_launched__"
"""Printed by a process inside the workspace, immediately before it execs the agent.

Part of the event stream contract: a transport that really creates a process
emits this line first, and nothing else in the stream means a launch.
``AgentLaunchEvidence`` consumes it, so it never reaches a stream processor. An
agent that echoed it would only be attesting its own existence, which is why
no escaping or nonce is needed.

What the line claims is exactly "a process here is about to become the agent",
which is all a wrapper can honestly say at the moment it speaks. Turning that
into "an agent existed" needs the exec to have happened, and only the exit
status can report that - so a transport owes this module a status as well as a
line, and no transport is asked to keep a promise about the future.
"""

#: The two statuses a shell reports when it could not execute the command:
#: 126 (found, not executable) and 127 (not found - including a script whose
#: shebang interpreter is missing, which the kernel also reports as ENOENT).
#:
#: They are the whole retraction rule, and what makes them sufficient is WHO is
#: left to report them. ``exec`` replaces the wrapper with the agent, so once
#: the agent is running the wrapper no longer exists and every status that
#: comes back is the agent's own. These two are the only ones the wrapper can
#: still return, because returning at all means it never got replaced. So this
#: is not a guess about what the command was going to do - it is the shell's
#: own account, after the fact, of an exec that did not happen.
#:
#: The residue runs the other way and is deliberate: an agent that really ran
#: and then chose to exit 126 or 127 itself is read as never launched. That
#: costs a NEVER_STARTED label on a session whose log is ALSO missing - the
#: only path that consults this fact - where the reverse residue would hand
#: that label to every failed exec, which is the bug (#1065).
_COULD_NOT_EXEC: Final = frozenset({126, 127})


class AgentLaunchObserver(Protocol):
    """Notified once, when an agent process is known to have existed.

    Called at most once per stream and never on the failure path. Must not
    raise: the launch record is not worth failing a phase over.
    """

    async def __call__(self) -> None: ...


class AgentLaunchEvidence:
    """What one phase's stream showed about whether an agent process existed.

    Used in two steps, because the answer is not available in one. ``observing``
    wraps the phase's stream and watches it go by; ``settle`` is given what the
    process finally exited with and records the launch, or does not.

    Holding the marker provisional between those two steps is the point. A
    wrapper announces immediately before ``exec``, so at the moment the line
    arrives "an agent exists" is a claim about the next instruction rather than
    an observation - and the one case that matters, an exec that fails, looks
    identical until the status comes back. Waiting costs nothing: nobody reads
    the launch fact while the phase is still running.

    Settling is biased towards LAUNCHED, and every uncertain path takes that
    side. A stream the caller abandoned mid-way (the cancellation path breaks
    out of the loop) never let the process report, so its status belongs to
    some other stream or to nothing at all, and it is not allowed to retract:
    silence is not a denial. The cost of being wrong that way is a session
    reported as launched when it was not; the cost of being wrong the other way
    is telling a user their session never started when it did, and that is the
    statement this whole module exists to keep honest.
    """

    __slots__ = ("_announced", "_observer", "_ran_to_the_end", "_recorded")

    def __init__(self, observer: AgentLaunchObserver | None) -> None:
        """Watch on behalf of ``observer``, or of nobody when there is none."""
        self._observer = observer
        self._announced = False
        self._ran_to_the_end = False
        self._recorded = False

    async def observing(self, stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """Yield from ``stream``, keeping the agent's announcement for ``settle``.

        Transparent otherwise: every other line passes through untouched and
        every exception propagates unchanged. Nothing is recorded here, so a
        caller that stops reading early has withheld the answer rather than
        answered no.
        """
        async for line in stream:
            if line != AGENT_LAUNCH_MARKER:
                yield line
                continue
            self._announced = True
        self._ran_to_the_end = True

    async def settle(self, exit_code: int | None) -> None:
        """Record the launch this phase's stream attested, if it attested one.

        ``exit_code`` is what the process carrying the stream exited with. It
        is read only when the stream was drained to the end, which is the only
        state in which that status is known to describe this stream and not a
        previous one.

        Idempotent, so a caller may settle from a ``finally`` without counting
        the launch twice.
        """
        if self._recorded or not self._announced:
            return
        if self._ran_to_the_end and exit_code in _COULD_NOT_EXEC:
            return
        self._recorded = True
        if self._observer is not None:
            await self._observer()


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
