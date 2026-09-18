"""Read the kernel's account of a signal death, while there is still one to read.

WHY THIS IS URGENT RATHER THAN NICE. The workspace reap REMOVES the container
and the orchestrator's process table entry goes with the coroutine that was
waiting on it, so every fact about a crash has a lifetime measured in
milliseconds after it happens. Polling for it later gets nothing - which is
precisely how the platform arrived at one hand-gathered kernel trace for its
most expensive failure class and no way to obtain a second. #1319 states the
same requirement for exit codes; this is that requirement for the crash.

THE ONE THING THIS MUST NEVER DO is fail. It runs on a path where a phase has
already been lost, and a diagnostic that raises while handling a crash turns
one lost phase into an unreadable one. Every failure mode below - no device
node, no capability, a truncated record, a kernel that logged nothing, a read
that takes too long - resolves to a SignalDeath carrying the REASON there is
no trace, never to an exception and never to silence.

WHOSE KERNEL THIS IS. There is one ring buffer per kernel and containers share
the host's, so a trace written when a process in any container faults is
visible from any container that is permitted to look. Permission is the whole
difficulty: `/dev/kmsg` is usually not present in a container at all, and
reading it needs CAP_SYSLOG wherever `kernel.dmesg_restrict` is 1 (the default
on Ubuntu). Both cases produce a diagnostic saying so and naming the fix,
because "no trace because nobody may look" and "no trace because the kernel
logged nothing" are opposite findings and only one of them is about the bug.

A host-level `docker events --filter event=die` collector would see
container-level deaths this cannot reach, and belongs at the host rather than
in this process; it is not implemented here.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import re
from typing import TYPE_CHECKING, Final

from syn_shared.diagnostics import SignalDeath, signal_number_of

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

_KMSG: Final[str] = "/dev/kmsg"

#: Kernel messages that name a faulting address and, on x86, the mapped object
#: the instruction pointer was in - which is the single fact this whole feature
#: is for. `segfault at 1f ip ... in cygrpc.cpython-312-x86_64-linux-gnu.so` is
#: the #1138 line verbatim. The others are the same event reported by a
#: different kernel path, and are included so a fault that is NOT a SIGSEGV is
#: not silently dropped into "no trace found".
_FAULT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"segfault at |general protection fault|traps: |Code: |unhandled signal ",
)

#: How far back a kernel record may be and still be read as being about THIS
#: death. The capture runs in the same coroutine that reaped the process, so
#: the real distance is under a second; the slack is for a loaded host. An
#: unbounded window would eventually attribute a segfault from yesterday's run
#: to today's command, which is the "wrong label costs more than no label" rule
#: from cc58c8fe applied to a timestamp instead of an exit code.
_RECENT_SECONDS: Final[float] = 120.0

#: Enough of a fault report to be useful - the fault line, and the register and
#: `Code:` dumps that sometimes follow it. Bounded because this string is
#: logged and carried into an operator-facing message.
_MAX_LINES: Final[int] = 8

#: Records to walk before giving up. The buffer holds a few thousand at most
#: and every record is one read(), so this is a guard against a pathological
#: kernel rather than an expected limit.
_MAX_RECORDS: Final[int] = 8192

#: Total wall-clock budget. This runs with a teardown queued behind it on a
#: path that is already failing, so it takes a bounded slice of the container's
#: remaining life or it takes none.
_BUDGET_SECONDS: Final[float] = 2.0


async def capture_signal_death(
    command: Sequence[str],
    exit_code: int | None,
) -> SignalDeath | None:
    """The diagnostic for a process that died on a signal, or None if it did not.

    THE ENTIRE INTERFACE. A caller hands over what it already has - the argv it
    ran and the status it got back - and receives either nothing, because this
    was an ordinary exit, or a complete diagnostic it can log and carry
    outward. It needs to know nothing about which exit-status convention its
    backend uses, which signal numbers exist, where the kernel keeps its ring
    buffer, or what a fault line looks like.

    Cannot raise. See the module docstring: raising here would convert a lost
    phase into an unreadable one.

    Returns:
        A :class:`SignalDeath` whenever ``exit_code`` names a signal under
        either convention, always carrying the signal name and the command, and
        carrying either the kernel lines or the reason there are none. None
        when the process was not killed by a signal, which is the common case
        and costs one integer comparison.
    """
    number = signal_number_of(exit_code)
    if number is None or exit_code is None:
        return None
    lines, unreadable = await _kernel_fault_lines()
    return SignalDeath(
        exit_code=exit_code,
        signal_number=number,
        command=tuple(command),
        kernel_lines=lines,
        unreadable_because=unreadable,
    )


async def _kernel_fault_lines() -> tuple[tuple[str, ...], str | None]:
    """Recent fault records, or the reason there are none. Never both, never raises."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_read_kmsg), _BUDGET_SECONDS)
    except TimeoutError:
        return (), (
            f"reading {_KMSG} did not finish within {_BUDGET_SECONDS:g}s and was "
            f"abandoned so it would not delay this workspace's teardown"
        )
    except Exception as unexpected:  # noqa: BLE001 - see module docstring
        logger.debug("Kernel ring buffer capture failed", exc_info=True)
        return (), (
            f"reading {_KMSG} failed unexpectedly with "
            f"{type(unexpected).__name__}: {unexpected}"
        )


def _read_kmsg() -> tuple[tuple[str, ...], str | None]:
    """Blocking half of the capture. Runs in a worker thread."""
    try:
        fd = os.open(_KMSG, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return (), (
            f"{_KMSG} does not exist in this container, so the kernel's own "
            f"account of the fault is not reachable from here. Bind-mount it "
            f"read-only into the service that runs workspaces to make it so."
        )
    except PermissionError:
        return (), _DENIED
    except OSError as err:
        return (), f"{_KMSG} could not be opened: {err.strerror or err}"

    try:
        uptime = _uptime_seconds()
        records = _fault_records(fd, uptime)
    except PermissionError:
        # Ubuntu's default kernel.dmesg_restrict=1 permits the open and denies
        # the read, so this is the ORDINARY denial, not the one above.
        return (), _DENIED
    except OSError as err:
        return (), f"{_KMSG} stopped being readable partway: {err.strerror or err}"
    finally:
        os.close(fd)

    if records:
        return records, None
    return (), (
        f"the kernel ring buffer was readable and held no fault report from "
        f"the last {_RECENT_SECONDS:g}s. The fault was therefore not one the "
        f"kernel logs - a process killed by another process rather than by a "
        f"memory fault looks like this."
    )


#: Said for both the denied open and the denied read, because an operator needs
#: the same one-line fix either way and two wordings for one cause is two
#: things to recognise in a log.
_DENIED: Final[str] = (
    f"reading {_KMSG} was denied. The service that runs workspaces needs "
    f"CAP_SYSLOG, or the host needs kernel.dmesg_restrict=0, before the "
    f"faulting library can be named from here."
)


def _uptime_seconds() -> float | None:
    """Seconds since boot, which is what kernel record timestamps count from.

    None when unreadable, and every caller then keeps the record rather than
    discarding it: not knowing how old a fault report is makes it weaker
    evidence, not absent evidence.
    """
    try:
        with open("/proc/uptime", encoding="ascii") as handle:  # noqa: PTH123
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _fault_records(fd: int, uptime: float | None) -> tuple[str, ...]:
    """Walk the ring buffer, keeping recent fault reports.

    Records are ``priority,sequence,microseconds,flags;message`` and newline
    terminated. ``/dev/kmsg`` hands back exactly one per read(), but that is a
    property of the device and not of file descriptors, so the walk splits on
    the terminator instead of relying on it - which is also what lets this be
    tested against a descriptor holding real records. The walk ends at EAGAIN,
    which is how a non-blocking read says it has reached the present.
    """
    kept: list[str] = []
    pending = ""
    for _ in range(_MAX_RECORDS):
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            break
        except OSError as err:
            # A record that was overwritten while being read; the kernel says
            # so and the next read continues. Anything else is real.
            if err.errno != errno.EPIPE:
                raise
            continue
        if not chunk:
            break
        pending += chunk.decode("utf-8", "replace")
        records = pending.split("\n")
        pending = records.pop()
        kept.extend(_faults_among(records, uptime))
        if len(kept) > _MAX_LINES:
            del kept[:-_MAX_LINES]
    kept.extend(_faults_among([pending], uptime))
    return tuple(kept[-_MAX_LINES:])


def _faults_among(records: list[str], uptime: float | None) -> list[str]:
    """The messages in ``records`` that report a fault and are recent enough."""
    kept: list[str] = []
    for record in records:
        message, age = _parse_record(record)
        if message is None or not _FAULT_PATTERN.search(message):
            continue
        if uptime is not None and age is not None and uptime - age > _RECENT_SECONDS:
            continue
        kept.append(message)
    return kept


def _parse_record(record: str) -> tuple[str | None, float | None]:
    """The message and its seconds-since-boot, from one ``/dev/kmsg`` record.

    Returns ``(None, None)`` for anything that does not have the documented
    shape, rather than guessing at it: a malformed record is one this capture
    has nothing to say about, and inventing a timestamp for it would put it
    inside or outside the recency window at random.
    """
    header, _, message = record.partition(";")
    fields = header.split(",")
    if not message or len(fields) < 3:
        return None, None
    try:
        return message.strip(), int(fields[2]) / 1_000_000
    except ValueError:
        return message.strip(), None
