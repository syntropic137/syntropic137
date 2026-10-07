"""An exec that comes back with no exit status and no output must say why.

THE SHAPE. ``exit_code == -1``, ``timed_out`` False, nothing on stdout or
stderr. Operators read it as "Secret-injection setup ... failed without
reporting an exit status (-1) and printed nothing", and the staged-credential
guard as ``attempts=4 [#1 exit=-1 (no exit status) ...]`` - a fatal record
that names no cause at all.

WHAT PRODUCES IT. agentic_isolation's ``WorkspaceDockerProvider._run_exec``
wraps ``docker exec`` in ``asyncio.wait_for``. When the deadline expires it
calls ``proc.kill()``; if the process has ALREADY exited, the subprocess
transport raises ``ProcessLookupError()`` - an exception with an empty message
- which the provider's catch-all turns into exit -1 with ``stderr=""``.

A deadline that expires on a process that has already finished is not a slow
command. It is an event loop that did not run for longer than the timeout: the
process exits, its pipes close, and nothing reads them until the loop comes
back, by which time the timeout callback is ready too and wins. On the selfhost
(2026-10-07) the API loop froze for 60-190s at a time, once per phase end,
inside ``copy_from``'s blocking glob and rmtree; exec-27fed66a653d's setup
started 06:21:54, the loop froze 06:21:56-06:24:15, and the setup "returned"
at 06:24:15 - 141s against a 120s timeout - as exit -1 with no output.

THIS MODULE turns the shape into a sentence: the container's state from
``docker inspect``, and how long the exec took against its timeout, which is
what separates "the loop was blocked past the deadline" from "the docker client
failed before it could report". The diagnosis is written into ``stderr`` with a
fixed prefix so callers can tell a lost status apart from every other -1.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final, Protocol

logger = logging.getLogger(__name__)

#: The provider's code for "no status was collected" (see `syn_shared.process_exit`).
NO_EXIT_STATUS: Final = -1

#: Starts every diagnosis this module writes. `is_status_lost` keys on it, so a
#: caller can retry exactly this case and nothing else that happens to be -1.
STATUS_LOST_PREFIX: Final = "exec returned no exit status and no output"

#: `docker inspect` is one daemon round trip; past this the daemon is the
#: problem, and that is itself the answer.
_INSPECT_TIMEOUT_SECONDS: Final = 5.0

#: What `docker inspect` is asked for. State and restarts answer "was the
#: container stopping, restarting, or OOM-killed under this exec".
_STATE_FORMAT: Final = (
    "{{.State.Status}} oom_killed={{.State.OOMKilled}} "
    "restarts={{.RestartCount}} exit_code={{.State.ExitCode}}"
)


class ExecOutcome(Protocol):
    """The fields of a provider result this module reads."""

    @property
    def exit_code(self) -> int: ...
    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...
    @property
    def timed_out(self) -> bool: ...


def status_was_lost(result: ExecOutcome) -> bool:
    """The raw provider shape: -1, not a timeout, and nothing printed at all."""
    return (
        result.exit_code == NO_EXIT_STATUS
        and not result.timed_out
        and not (result.stdout or "").strip()
        and not (result.stderr or "").strip()
    )


def is_status_lost(result: ExecOutcome) -> bool:
    """Whether a backend result is a lost status this module already diagnosed."""
    return result.exit_code == NO_EXIT_STATUS and (result.stderr or "").startswith(
        STATUS_LOST_PREFIX
    )


def workspace_container_name(isolation_id: str) -> str:
    """The docker container behind an isolation id (``ws-1a2b3c4d`` -> ``agentic-ws-1a2b3c4d``)."""
    return f"agentic-ws-{isolation_id.split('-')[1]}"


async def container_state(container_name: str) -> str:
    """The container's state as `docker inspect` reports it, or why it could not be read.

    Never raises: this runs while explaining a failure, and must not replace
    that failure with one of its own.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "--format",
            _STATE_FORMAT,
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), _INSPECT_TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            return f"unknown (docker inspect did not answer in {_INSPECT_TIMEOUT_SECONDS:.0f}s)"
    except Exception as e:  # a diagnosis must not raise
        return f"unknown (docker inspect could not run: {type(e).__name__}: {e})"
    if proc.returncode != 0:
        reason = err.decode(errors="replace").strip() or f"exit {proc.returncode}"
        return f"unknown (docker inspect failed: {reason})"
    return out.decode(errors="replace").strip() or "unknown (docker inspect printed nothing)"


def _explain_timing(duration_ms: float, timeout_seconds: float | None) -> str:
    elapsed = duration_ms / 1000
    if timeout_seconds is None:
        return f"returned after {elapsed:.1f}s"
    if elapsed >= timeout_seconds:
        return (
            f"returned after {elapsed:.1f}s against a {timeout_seconds:g}s timeout: the "
            f"deadline expired on a process that had already exited, so the kill found "
            f"nothing and its real status was discarded. That happens when the API "
            f"event loop is blocked past the deadline - look in the API log for a gap "
            f"just before this line"
        )
    return (
        f"returned after {elapsed:.1f}s, inside its {timeout_seconds:g}s timeout: the "
        f"docker exec client failed before it reported a status"
    )


async def diagnose_lost_status(
    container_name: str,
    *,
    duration_ms: float,
    timeout_seconds: float | None,
) -> str:
    """The sentence that replaces an empty stderr. Starts with `STATUS_LOST_PREFIX`."""
    state = await container_state(container_name)
    return (
        f"{STATUS_LOST_PREFIX} (container {container_name}: {state}); "
        f"{_explain_timing(duration_ms, timeout_seconds)}"
    )
