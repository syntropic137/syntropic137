"""How a subprocess ended, said in a way that survives into the record (#1158).

A failure record built from a subprocess's stderr answers the wrong question.
Git writes its progress to stderr, so a phase whose container was SIGKILLed
mid-clone persisted this as its error::

    Setup phase failed: Cloning into '/workspace/repos/syntropic137'...

Nothing there is an error. Git had not failed; it was still cloning when the
process was killed under it. The one fact that said so - the exit status - was
used only as a fallback for when stderr happened to be empty, so in practice it
was never recorded at all, and "the command failed" became indistinguishable
from "something killed it" in the only durable record we keep. That cost a
wrong diagnosis on #1153 and, as `exit -11`, weeks on #1046.

So the status leads and the output follows, demoted to what it actually is
whenever the process never chose the status it ended with.
"""

from __future__ import annotations

import signal

__all__ = ["describe_exit_status", "describe_process_failure"]

#: A shell reports a killed child as 128 + signum, so SIGKILL arrives as 137.
#: `docker exec` is a shell for this purpose, so this is the form nearly every
#: in-workspace command produces.
_SIGNAL_EXIT_BASE = 128

#: The isolation providers return -1 for three different ways of never running
#: at all - no container, the exec itself raised, a timeout - so -1 is the one
#: negative status that is NOT a signal number. Decoding it as SIGHUP would
#: invent a signal death for every unreachable container, which is the same
#: fabrication this module exists to stop, pointing the other way.
_NO_EXIT_STATUS = -1


def _killing_signal(exit_code: int) -> signal.Signals | None:
    """The signal that killed the process, or None if it chose its own status.

    Two conventions for saying "killed by a signal" reach this code and they
    mean the same thing. A shell - and so `docker exec`, and so nearly every
    command run inside a workspace - reports it as 128 + signum: SIGKILL is
    137, SIGSEGV 139. Python's `subprocess` reports the same deaths as -9 and
    -11, and -11 is what #1046 spent weeks reading as a clone problem. Neither
    spelling is more correct and no caller should have to know which one its
    provider happens to use.

    A number above 128 that names no signal is left alone: `exit 255` is a
    status a program chose, not a death.
    """
    if exit_code == _NO_EXIT_STATUS:
        return None
    signum = -exit_code if exit_code < 0 else exit_code - _SIGNAL_EXIT_BASE
    if signum <= 0:
        return None
    try:
        return signal.Signals(signum)
    except ValueError:
        return None


def describe_exit_status(exit_code: int, *, timed_out: bool = False) -> str:
    """How the process ended, naming the signal when a signal is what ended it.

    A fragment, so it can be the middle of a longer sentence: "the command
    'git status' was killed by SIGKILL (exit 137)".
    """
    if timed_out:
        return "timed out, so it did not finish"
    killed_by = _killing_signal(exit_code)
    if killed_by is not None:
        return f"was killed by {killed_by.name} (exit {exit_code})"
    if exit_code == _NO_EXIT_STATUS:
        return "failed without reporting an exit status (-1)"
    return f"exited {exit_code}"


def describe_process_failure(
    what: str,
    *,
    exit_code: int,
    output: str,
    timed_out: bool = False,
) -> str:
    """The durable record of `what` not succeeding, safe to persist and to read.

    `what` names the subject and begins the sentence - "Setup phase", "The
    quarantine push". `output` is whatever the process printed, stderr or
    stdout; this decides how much weight to give it, which is the whole point
    of routing every call site through here rather than each formatting its own
    string and each forgetting the status separately.

    A process that was killed, or that ran out of time, never reported why, so
    its output is demoted to what it actually is - the last thing it managed to
    print - and the message says so before quoting it. A process that chose a
    non-zero status did fail, and then its output is the closest thing to a
    reason there is.
    """
    printed = output.strip()
    ending = describe_exit_status(exit_code, timed_out=timed_out)
    if not printed:
        return f"{what} {ending} and printed nothing."
    if timed_out or _killing_signal(exit_code) is not None:
        return (
            f"{what} {ending}. What follows is not an error message - the "
            f"process never reported one - it is only the last thing it "
            f"printed before it stopped: {printed}"
        )
    return f"{what} {ending}: {printed}"
