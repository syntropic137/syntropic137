"""What an exit status means when a process was killed rather than finished.

WHY THIS EXISTS. ``exit -11`` is the most expensive failure class on the
platform: it has taken a `git rev-parse` inside the unpushed-work gate, a
`find` over the repo list, the secret-injection setup before any agent ran,
and whole agent phases. Every one of those reached an operator as the four
characters ``-11``, which name neither what happened (a SIGSEGV) nor what
faulted. One kernel trace exists, gathered by hand, off-platform; it names
``cygrpc`` and it cannot be obtained again on demand. Two open issues (#1138,
#1295) disagree about whether these are one bug or several, and the
disagreement is unresolvable because the evidence is destroyed with the
workspace before anyone can look.

So this module, plus its capture half in ``syn_adapters.diagnostics``, exists
to turn ``-11`` into a sentence an operator can act on and a fact the next
investigation can cite.

THE DECISION THIS HIDES is "what does this integer mean", and it is genuinely
not obvious - there are three conventions in play at once and this codebase
uses all three:

* **Negative, CPython's convention.** ``asyncio``/``subprocess`` report the
  status of the IMMEDIATE child as ``-N`` when a signal killed it. In this
  codebase that child is the local ``docker`` client process, not anything
  inside a container, so ``-11`` is the orchestrator's own subprocess dying.
* **128+N, the shell and `docker exec` convention.** A process killed INSIDE
  the container comes back through Docker as a POSITIVE ``128+N`` - 139 for
  SIGSEGV. Same event, different number, opposite sign.
* **-1, this repository's "no real status" sentinel.** Used repo-wide for a
  missing container, a timeout, and a caught exception.

That third one is why this module refuses to name ``-1``, and the refusal is
load-bearing rather than fussy. A previous attempt at exactly this feature was
reverted (``cc58c8fe``) because it labelled all three of those ``-1`` call
sites "killed by SIGHUP" - SIGHUP being signal 1. The revert's own words:
**a wrong label on a failure costs more than no label.** Everything here is
built to that rule: where the convention is unambiguous it states a fact,
where the convention is merely conventional it says so, and where it does not
know it says nothing.

Pure by design - no I/O, no clock, no container. The half that reads the
kernel ring buffer lives in ``syn_adapters.diagnostics.signal_capture``,
because reading a device node is infrastructure and this package is imported
by the domain.
"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import Final

#: Offset a shell, and therefore ``docker exec``, adds to a signal number to
#: report "the process was killed by this signal" through an unsigned status.
_SHELL_SIGNAL_OFFSET: Final[int] = 128

#: The sentinel this repository uses for "there is no real status": a missing
#: container, a timeout, a caught exception. It collides with SIGHUP under the
#: negative convention, which is exactly the collision that got the previous
#: version of this feature reverted (``cc58c8fe``). Never named as a signal.
_NO_STATUS_SENTINEL: Final[int] = -1


def signal_number_of(exit_code: int | None) -> int | None:
    """The signal that killed a process, or None if it was not killed by one.

    Recognises both conventions described in the module docstring, so callers
    never have to know which of the two shapes their backend produced. Returns
    None for a normal exit, for ``None`` (nothing has been reaped yet), and for
    the ``-1`` sentinel.

    The positive range is deliberately narrow: only ``128+N`` for a signal
    number the running platform actually defines. A process is free to exit
    139 of its own accord and nothing can distinguish that from a SIGSEGV
    reported by a shell, which is why :func:`name_exit_status` hedges the
    wording for this shape rather than asserting it.
    """
    if exit_code is None or exit_code == 0 or exit_code == _NO_STATUS_SENTINEL:
        return None
    candidate = -exit_code if exit_code < 0 else exit_code - _SHELL_SIGNAL_OFFSET
    if candidate <= 0:
        return None
    return candidate if candidate in _VALID_SIGNAL_NUMBERS else None


def _signal_name(number: int) -> str:
    """``SIGSEGV`` for 11. The number itself if this platform has no name."""
    try:
        return signal.Signals(number).name
    except ValueError:  # pragma: no cover - guarded by _VALID_SIGNAL_NUMBERS
        return f"signal {number}"


#: Signal numbers this platform defines. Computed once: the set is what keeps
#: an ordinary exit status of 130 from being read as a signal on a kernel that
#: has no signal 2... and, more usefully, keeps 200 from being read as one.
_VALID_SIGNAL_NUMBERS: Final[frozenset[int]] = frozenset(s.value for s in signal.Signals)


def name_exit_status(exit_code: int | None) -> str:
    """One clause naming what an exit status says, for a human reading it.

    THE ONE PLACE an exit code becomes English, so that "exited -11" cannot
    reappear in a message somewhere this module never reached. Reads as a verb
    phrase - callers put it after the thing that exited:

    >>> name_exit_status(-11)
    'was killed by SIGSEGV (exit -11)'
    >>> name_exit_status(139)
    'exited 139 (128+11, how a shell and `docker exec` report a SIGSEGV)'
    >>> name_exit_status(-1)
    'exited -1 (no real status: a missing container, a timeout, or a caught exception)'
    >>> name_exit_status(None)
    'has no exit status yet'
    >>> name_exit_status(2)
    'exited 2'

    The two signal forms are worded differently on purpose. A negative status
    is CPython telling us a signal killed the child, which is a fact. A
    positive ``128+N`` is a convention a shell follows, and a program that
    exits 139 deliberately produces exactly the same number - so that line
    names the convention instead of claiming the fact.
    """
    if exit_code is None:
        return "has no exit status yet"
    if exit_code == _NO_STATUS_SENTINEL:
        return (
            f"exited {_NO_STATUS_SENTINEL} (no real status: a missing "
            f"container, a timeout, or a caught exception)"
        )
    number = signal_number_of(exit_code)
    if number is None:
        return f"exited {exit_code}"
    if exit_code < 0:
        return f"was killed by {_signal_name(number)} (exit {exit_code})"
    return (
        f"exited {exit_code} ({_SHELL_SIGNAL_OFFSET}+{number}, how a shell "
        f"and `docker exec` report a {_signal_name(number)})"
    )


@dataclass(frozen=True)
class SignalDeath:
    """Everything knowable about one signal death, captured while it was knowable.

    Constructed by ``syn_adapters.diagnostics.signal_capture`` at the moment a
    process is reaped and carried outward on ``ExecutionResult`` - because the
    workspace reap REMOVES the container, and so does the orchestrator's own
    process table entry. Anything not read here is not readable later (#1319 is
    the same requirement for exit codes).

    ``kernel_lines`` and ``unreadable_because`` are the two answers to "what
    faulted", and exactly one of them is ever populated. That distinction is
    the point of carrying the second field at all: an empty trace because the
    API container has no ``CAP_SYSLOG`` is a CONFIGURATION problem an operator
    can fix in one line, and an empty trace because the kernel logged nothing
    is EVIDENCE about the bug. Collapsing both to "no trace" is how this
    failure class stayed unexplained for as long as it has.
    """

    exit_code: int
    signal_number: int
    command: tuple[str, ...]
    kernel_lines: tuple[str, ...] = ()
    unreadable_because: str | None = None

    @property
    def signal_name(self) -> str:
        """``SIGSEGV``, and the reason this class exists."""
        return _signal_name(self.signal_number)

    def describe(self) -> str:
        """The diagnostic as an operator should read it, ready to be logged.

        Multi-line. Always names the signal and the command, then either the
        kernel lines or why there are none - never silence in place of either.
        """
        lines = [
            f"{self.signal_name}: the command "
            f"{' '.join(self.command)!r} {name_exit_status(self.exit_code)}."
        ]
        if self.kernel_lines:
            lines.append(
                "  Kernel ring buffer, around the moment it died - the library "
                "named here is the one that faulted:"
            )
            lines.extend(f"    {line}" for line in self.kernel_lines)
        else:
            lines.append(
                f"  No kernel trace was captured, and that is not evidence that "
                f"the kernel logged none: {self.unreadable_because}"
            )
        return "\n".join(lines)
