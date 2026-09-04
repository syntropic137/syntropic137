"""Stream helper functions for AgenticEventStreamAdapter.

Extracted from stream_adapter.py to reduce module cognitive complexity.
Handles process management for docker exec streaming.
Line-reading is in stream_reader.py.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

from syn_domain.contexts.orchestration import announce_as

logger = logging.getLogger(__name__)

#: Announce the launch from inside the container, then become the agent.
#:
#: Reaching this script at all requires the daemon to have accepted the exec,
#: so a client that failed short of that - no such container, exec refused -
#: cannot produce the marker however it fails. That is load-bearing because
#: `docker exec` merges its own diagnostics into this same stdout pipe, so
#: nothing else arriving on it tells the two apart.
#:
#: What the marker cannot say is that the agent itself started: it is printed
#: before ``exec``, and ``exec`` can still fail. Nothing asked here would fix
#: that. Every pre-exec predicate is a prediction of what the kernel is about
#: to do, and the kernel checks more than a shell can - a script that resolves,
#: is a regular file and carries the executable bit still fails ``exec`` with
#: 127 when its shebang interpreter is missing. So the script makes no
#: prediction and the claim is settled afterwards instead, from what this shell
#: leaves behind: ``exec`` replaces it on success, so a 126 or 127 coming back
#: with nothing on the stream but this shell's own signed diagnostic is the
#: shell still being here to report that the agent never replaced it (see
#: ``AgentLaunchEvidence``, #1065).
#:
#: ``exec`` then replaces the shell, so the agent inherits the pid the timeout
#: path signals and the argv it was given. The announcement is passed as an
#: argument rather than interpolated, which keeps this script a constant.
_ANNOUNCE_THEN_EXEC = 'printf "%s\\n" "$1"; shift; exec "$@"'

#: Prefixes the name this wrapper runs under, for an operator reading a phase
#: log; the rest of the name is what makes it evidence.
_WRAPPER = "syn-launch"


def _wrapper_name() -> str:
    """A name for one wrapper, which no other process on its stream can produce.

    This becomes the shell's ``$0``, and a POSIX shell puts ``$0`` in front of
    its own diagnostics - so it is the signature that lets ``AgentLaunchEvidence``
    read "the exec failed" off a stream that also carries agent output, instead
    of reading it off the exit status alone and retracting agents that really
    ran and really exited 126 or 127 (#1065).

    Fresh per exec, because a constant name would be a signature the agent
    could forge: agent stdout and this shell's stderr are the same stream by
    design (ADR-043), so a guessable name lets a line the agent chooses to
    print decide whether that agent is reported as having existed. This one is
    never inside the container - it is an argument to the `docker exec` CLIENT,
    on the host, and ``exec`` overwrites the argv holding it before the agent
    exists to look.

    The published marker needs no such protection and says so: an agent that
    echoes it only attests its own existence. This name is the opposite - a
    forged copy denies the agent's existence - so it is the half that is minted.
    """
    return f"{_WRAPPER}-{secrets.token_hex(8)}"


def _build_exec_command(
    container_name: str,
    command: list[str],
    working_directory: str | None,
    environment: dict[str, str] | None,
) -> list[str]:
    """Build the docker exec command list, wrapped so a startable agent announces itself."""
    exec_cmd = ["docker", "exec", "-i", "-w", working_directory or "/workspace"]
    if environment:
        for key, value in environment.items():
            exec_cmd.extend(["-e", f"{key}={value}"])
    exec_cmd.append(container_name)
    wrapper = _wrapper_name()
    exec_cmd.extend(["sh", "-c", _ANNOUNCE_THEN_EXEC, wrapper, announce_as(wrapper), *command])
    return exec_cmd


#: How long a process whose output has already ended is given to be reaped on
#: its own before it is signalled. Generous: the stream reaching EOF means the
#: process has closed stdout, so its status is normally in hand within a
#: millisecond, and nothing waits on this but the phase that just finished.
_SELF_EXIT_GRACE_SECONDS = 0.5


async def _cleanup_process(proc: asyncio.subprocess.Process) -> int | None:
    """Wait for the process to finish, signalling it only if it will not.

    Waiting FIRST is what makes the status trustworthy, and the old order
    corrupted it. ``proc.returncode`` is filled in by asyncio's child watcher
    thread, so it is still None for the moment between a process exiting and
    that thread being scheduled - the exact moment this runs, because the
    stream ended when the process did. Terminating on that reading sends
    ``Popen.send_signal`` down a path that calls ``poll()`` first, which reaps
    the child itself; the watcher's own ``waitpid`` then fails and asyncio
    substitutes 255. A failed exec is the fastest exit there is, so the status
    that says so was the one most likely to be replaced by a fiction - and it
    is now the status that decides whether an agent ever launched (#1065).

    A process that is genuinely still running is unaffected: it does not exit
    within the grace window, `poll()` finds it alive, and the terminate/kill
    escalation proceeds as before.
    """
    try:
        return await asyncio.wait_for(proc.wait(), timeout=_SELF_EXIT_GRACE_SECONDS)
    except TimeoutError:
        pass
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except (TimeoutError, ProcessLookupError):
        proc.kill()
    if proc.returncode is None:
        await proc.wait()
    return proc.returncode


def _is_stream_timed_out(
    stream_timeout: float | None,
    start_time: float,
) -> bool:
    """Return True and log if the stream timeout has been reached."""
    if stream_timeout is None:
        return False
    elapsed = time.monotonic() - start_time
    if elapsed >= stream_timeout:
        logger.warning("Stream timed out after %.1fs", elapsed)
        return True
    return False
