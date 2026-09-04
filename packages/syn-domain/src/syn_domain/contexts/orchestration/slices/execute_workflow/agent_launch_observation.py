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
a process created INSIDE the workspace announces itself before it becomes the
agent, and that line is the only thing counted here. A client that never
reached the container ran nothing that could print it, and an agent that dies
before its first output has already announced itself - which is the case a
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
"""Opens the line a process inside the workspace prints just before it execs the agent.

Part of the event stream contract: a transport that really creates a process
emits this line first, and nothing else in the stream means a launch.
``AgentLaunchEvidence`` consumes it, so it never reaches a stream processor. An
agent that echoed it would only be attesting its own existence, which is why
no escaping is needed for this half of the line.

The rest of the line is the wrapper's NAME, and that half does need to be
unguessable - see ``announce_as``. Use that to build the line rather than
concatenating here, so the two ends cannot drift.

What the line claims is exactly "a process here is about to become the agent",
which is all a wrapper can honestly say at the moment it speaks. Turning that
into "an agent existed" needs the exec to have happened, and only the exit
status can report that - so a transport owes this module a status as well as a
line, and no transport is asked to keep a promise about the future.
"""


def announce_as(name: str) -> str:
    """The line a wrapper calling itself ``name`` prints immediately before ``exec``.

    ``name`` is the wrapper's ``$0``, which is also what a POSIX shell puts in
    front of its own diagnostics - so announcing it here is what later lets
    ``AgentLaunchEvidence`` tell a line the wrapper wrote from a line the agent
    wrote. That only works while the agent cannot produce the name itself,
    which makes it the caller's job to mint one that is fresh and unguessable
    per exec rather than to name the wrapper something readable.

    Inverse of ``_announced_name``; they are kept adjacent because a transport
    that formats this line by hand is how the two halves silently drift apart.
    """
    return f"{AGENT_LAUNCH_MARKER} {name}"


def _announced_name(line: str) -> str | None:
    """The wrapper name this line announces, or None if it is not an announcement."""
    marker, sep, name = line.partition(" ")
    if marker != AGENT_LAUNCH_MARKER or not sep or not name:
        return None
    return name


#: The two statuses a shell reports when it could not execute the command:
#: 126 (found, not executable) and 127 (not found - including a script whose
#: shebang interpreter is missing, which the kernel also reports as ENOENT).
#:
#: Necessary for a retraction but deliberately not sufficient, because these
#: are ordinary statuses that a running agent is free to exit with too. What
#: separates the two readings is who was still there to speak: ``exec``
#: replaces the wrapper with the agent, so a wrapper that lived long enough to
#: report a failed exec never had anything else on the stream to say. See
#: ``AgentLaunchEvidence.settle``.
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

    __slots__ = ("_observer", "_ran_to_the_end", "_recorded", "_spoke_over", "_wrapper")

    def __init__(self, observer: AgentLaunchObserver | None) -> None:
        """Watch on behalf of ``observer``, or of nobody when there is none."""
        self._observer = observer
        self._wrapper: str | None = None
        self._spoke_over = False
        self._ran_to_the_end = False
        self._recorded = False

    async def observing(self, stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """Yield from ``stream``, keeping the agent's announcement for ``settle``.

        Transparent otherwise: every other line passes through untouched and
        every exception propagates unchanged, including the wrapper's own
        diagnostics, which an operator reading the phase log needs. Nothing is
        recorded here, so a caller that stops reading early has withheld the
        answer rather than answered no.
        """
        async for line in stream:
            name = _announced_name(line)
            if name is None:
                if not self._signed_by_the_wrapper(line):
                    self._spoke_over = True
                yield line
                continue
            self._wrapper = name
        self._ran_to_the_end = True

    def _signed_by_the_wrapper(self, line: str) -> bool:
        """Whether the wrapper that announced itself on this stream wrote this line.

        A POSIX shell prefixes its diagnostics with its own ``$0`` and a colon,
        and the wrapper announced that ``$0`` on the way past. The wording
        after the colon is not checked: dash says ``exec: X: not found`` where
        bash says ``line 1: X: No such file or directory``, and which of them
        is /bin/sh is a property of the workspace image rather than of this
        repo. The prefix is the part we set ourselves.
        """
        return self._wrapper is not None and line.startswith(f"{self._wrapper}:")

    async def settle(self, exit_code: int | None) -> None:
        """Record the launch this phase's stream attested, if it attested one.

        ``exit_code`` is what the process carrying the stream exited with. It
        is read only when the stream was drained to the end, which is the only
        state in which that status is known to describe this stream and not a
        previous one.

        126 and 127 are the statuses a shell returns for an exec it could not
        perform, but they are not reserved: an agent that really ran may exit
        with either, and reading the status alone retracted those launches too
        (#1065). What settles it is that ``exec`` replaces the wrapper - so if
        the agent ever existed, every line after the announcement is the
        agent's, and a wrapper still alive to report a failed exec left nothing
        on the stream but its own signed diagnostic. So a status that says "no
        exec" only retracts while nothing has spoken over the wrapper.

        The residue is one-sided by design. Transport noise arriving after a
        genuinely failed exec reads as the agent speaking and keeps a launch
        that did not happen, which is the direction this class already leans;
        the reverse would hand a false "never started" to a user whose agent
        ran, which is the bug.

        Idempotent, so a caller may settle from a ``finally`` without counting
        the launch twice.
        """
        if self._recorded or self._wrapper is None:
            return
        if self._ran_to_the_end and exit_code in _COULD_NOT_EXEC and not self._spoke_over:
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
