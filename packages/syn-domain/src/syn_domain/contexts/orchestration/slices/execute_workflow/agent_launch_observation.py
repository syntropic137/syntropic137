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

The name in that marker is a CHALLENGE, issued before the stream exists and
never learned from it. ``AgentLaunchEvidence`` mints one per exec and the
transport is told to answer under it; only a process the transport created
inside the workspace could have been told, so only such a process can answer.
Reading the name off the stream instead would put the answer in charge of the
question: an agent could announce a name of its own, sign a diagnostic with it
and retract its own launch, which is the false NOT_LAUNCHED this module exists
to prevent (#1065). A secret learned from the stream is not a secret, and no
amount of randomness fixes that - it is an ordering property, not an entropy
one, so the ordering is removed rather than defended.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


AGENT_LAUNCH_MARKER = "__syn_agent_launched__"
"""Opens the line a process inside the workspace prints just before it execs the agent.

Part of the event stream contract: a transport that really creates a process
emits this line first, and nothing else in the stream means a launch.
``AgentLaunchEvidence`` consumes the one line it was expecting, so that line
never reaches a stream processor. An agent that echoed this marker would only
be attesting its own existence, which is why no escaping is needed for this
half of the line - and its copy is forwarded like any other agent output,
because it is agent output.

The rest of the line is the wrapper's NAME, and that half does need to be
unguessable - see ``mint_wrapper_name``. Build the line with ``announce_as``
rather than concatenating here, so the two ends cannot drift.

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
    wrote. That only works while the agent cannot produce the name itself, so
    take ``name`` from ``mint_wrapper_name`` rather than calling the wrapper
    something readable.

    Kept beside ``mint_wrapper_name`` and ``AgentLaunchEvidence`` because a
    transport that formats this line by hand is how the two halves silently
    drift apart.
    """
    return f"{AGENT_LAUNCH_MARKER} {name}"


#: Prefixes every wrapper name, for an operator reading a phase log. The rest
#: is what makes the name evidence.
_WRAPPER_PREFIX: Final = "syn-launch"


def mint_wrapper_name() -> str:
    """A name for one wrapper, which no other process on its stream can produce.

    This becomes the wrapper shell's ``$0``, and a POSIX shell puts ``$0`` in
    front of its own diagnostics - so it is the signature that lets
    ``AgentLaunchEvidence`` read "the exec failed" off a stream that also
    carries agent output, instead of reading it off the exit status alone and
    retracting agents that really ran and really exited 126 or 127 (#1065).

    Fresh per exec, because a constant name would be a signature the agent
    could forge: agent stdout and the wrapper's stderr are the same stream by
    design (ADR-043), so a guessable name lets a line the agent chooses to
    print decide whether that agent is reported as having existed. Nothing
    inside the container is ever told this name except through the wrapper's
    own argv, which ``exec`` overwrites before the agent exists to look.

    The published marker needs no such protection and says so: an agent that
    echoes it only attests its own existence. This name is the opposite - a
    forged copy denies the agent's existence - so it is the half that is
    minted.
    """
    return f"{_WRAPPER_PREFIX}-{secrets.token_hex(8)}"


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

    Used in three steps, because the answer is not available in one.
    ``wrapper_name`` is the challenge, handed to the transport before the
    stream exists; ``observing`` wraps the phase's stream and watches it go by;
    ``settle`` is given what the process finally exited with and records the
    launch, or does not.

    Holding the marker provisional between announcement and status is the
    point. A
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

    __slots__ = (
        "_announced",
        "_announcement",
        "_observer",
        "_ran_to_the_end",
        "_recorded",
        "_spoke_over",
        "_wrapper",
    )

    def __init__(self, observer: AgentLaunchObserver | None) -> None:
        """Watch on behalf of ``observer``, or of nobody when there is none.

        Mints the name it will listen for here, before there is a stream to
        listen to, so nothing on the stream can choose it.
        """
        self._observer = observer
        self._wrapper = mint_wrapper_name()
        self._announcement = announce_as(self._wrapper)
        self._announced = False
        self._spoke_over = False
        self._ran_to_the_end = False
        self._recorded = False

    @property
    def wrapper_name(self) -> str:
        """The ``$0`` the transport must run this phase's wrapper under.

        The only name this evidence will accept an announcement under, and the
        only place a caller can get one - so the name the transport announces
        and the name the observer listens for cannot be different names.
        """
        return self._wrapper

    async def observing(self, stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """Yield from ``stream``, keeping the agent's announcement for ``settle``.

        Only the exact announcement of the name minted for this phase is taken
        - and taken as a fact about the transport, not as an instruction, so
        the stream never gets to say which name counts. A line that merely
        looks like an announcement is an agent that typed one, and is treated
        as what it is: agent output, forwarded, and evidence that something
        spoke over the wrapper.

        Transparent otherwise: every other line passes through untouched and
        every exception propagates unchanged, including the wrapper's own
        diagnostics, which an operator reading the phase log needs. Nothing is
        recorded here, so a caller that stops reading early has withheld the
        answer rather than answered no.
        """
        async for line in stream:
            if line == self._announcement:
                self._announced = True
                continue
            if not self._signed_by_the_wrapper(line):
                self._spoke_over = True
            yield line
        self._ran_to_the_end = True

    def _signed_by_the_wrapper(self, line: str) -> bool:
        """Whether the wrapper this phase's transport was told to run under wrote this line.

        A POSIX shell prefixes its diagnostics with its own ``$0`` and a colon,
        and that ``$0`` was minted here. The wording after the colon is not
        checked: dash says ``exec: X: not found`` where bash says ``line 1: X:
        No such file or directory``, and which of them is /bin/sh is a property
        of the workspace image rather than of this repo. The prefix is the part
        we set ourselves.
        """
        return line.startswith(f"{self._wrapper}:")

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
        if self._recorded or not self._announced:
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
