"""How a subprocess ended, said in a way that survives into the record (#1158).

A failure record built from a subprocess's stderr answers the wrong question.
Git writes its progress to stderr, so a phase whose container was SIGKILLed
mid-clone persisted this as its error::

    Setup phase failed: Cloning into '/workspace/repos/syntropic137'...

Nothing there is an error. Git had not failed; it was still cloning when the
process was killed under it. The one fact that said so - the exit status - was
used only as a fallback for when stderr happened to be empty, so in practice it
was never recorded at all, and "the command failed" became indistinguishable
from "something killed the container" in the only durable record we keep. That
cost a wrong diagnosis on #1153 and, as `exit -11`, weeks on #1046.

So the exit status leads and the output follows, labelled as output.
"""

from __future__ import annotations

import signal

__all__ = ["describe_exit_status", "describe_process_failure"]

#: A shell reports a killed child as 128 + signum, so SIGKILL arrives as 137.
_SIGNAL_EXIT_BASE = 128


def _killing_signal(exit_code: int) -> signal.Signals | None:
    """The signal that killed the process, or None if it chose its own status.

    Two conventions for saying "killed by a signal" reach this code and they
    mean the same thing. A shell - and so `docker exec`, and so every command
    run inside a workspace - reports it as 128 + signum: SIGKILL is 137.
    Python's `subprocess` reports it as -signum: the same death is -9, and a
    SIGSEGV is the `exit -11` of #1046. Neither spelling is more correct and no
    caller should have to know which one its provider happens to use.

    A number above 128 that names no signal is left alone: `exit 255` is a
    status a program chose, not a death.
    """
    signum = -exit_code if exit_code < 0 else exit_code - _SIGNAL_EXIT_BASE
    if signum <= 0:
        return None
    try:
        return signal.Signals(signum)
    except ValueError:
        return None


def describe_exit_status(exit_code: int) -> str:
    """How the process ended, naming the signal when a signal is what ended it.

    A fragment, so it can be the middle of a longer sentence: "the command
    'git status' was killed by SIGKILL (exit 137)".
    """
    killed_by = _killing_signal(exit_code)
    if killed_by is None:
        return f"exited {exit_code}"
    return f"was killed by {killed_by.name} (exit {exit_code})"


def describe_process_failure(what: str, *, exit_code: int, output: str) -> str:
    """The durable record of `what` not succeeding, safe to persist and read.

    `what` names the subject and begins the sentence - "Setup phase", "The
    quarantine push". `output` is whatever the process printed, stderr or
    stdout; this decides how much weight to give it, which is the whole point
    of routing both call sites through here rather than each formatting its own
    string and each forgetting the exit status separately.

    A process that was killed did not report anything about why, so its output
    is demoted to what it happens to be - the last thing it managed to print -
    and the message says so before quoting it. A process that chose a non-zero
    status did fail, and then its output is the closest thing to a reason we
    have.
    """
    printed = output.strip()
    ending = describe_exit_status(exit_code)
    if not printed:
        return f"{what} {ending} and printed nothing."
    if _killing_signal(exit_code) is not None:
        return (
            f"{what} {ending}. It was killed rather than failing, so what "
            f"follows is not an error message, only the last output before it "
            f"died: {printed}"
        )
    return f"{what} {ending}: {printed}"
