"""A failed sidecar start must keep the status that decided it had failed (#1247).

`run_sidecar_container` reads `proc.returncode` to decide the command failed,
and then used to build its message out of stderr alone. When `docker run`
exits non-zero with empty stderr - which it does - the operator got exactly:

    Failed to start sidecar: Unknown error

That message cannot tell "image missing" from "out of disk" from "daemon
unreachable", which is the whole cost of the defect.

These tests drive the real `run_sidecar_container` with a stand-in subprocess,
rather than re-deriving the message from a copy of the branch's logic - a copy
would stay green if production stopped including the status.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import (
    run_sidecar_container,
)

pytestmark = pytest.mark.unit

_CMD = ["docker", "run", "-d", "syn-sidecar:test"]


class _FinishedProc:
    """A `docker run` that has already exited, with the output it produced."""

    def __init__(self, returncode: int | None, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


async def _failure_message(returncode: int | None, stdout: bytes = b"", stderr: bytes = b"") -> str:
    """Run the real helper against that subprocess and return what it raised."""
    proc = _FinishedProc(returncode, stdout, stderr)

    async def _spawn(*_args: object, **_kwargs: object) -> _FinishedProc:
        return proc

    with patch("asyncio.create_subprocess_exec", new=_spawn), pytest.raises(RuntimeError) as raised:
        await run_sidecar_container(_CMD)
    return str(raised.value)


@pytest.mark.asyncio
async def test_empty_stderr_still_reports_the_exit_status() -> None:
    """The case that cost a run: the status is the only evidence left."""
    message = await _failure_message(125)

    assert "125" in message, "the status that decided this was a failure was discarded"
    assert "Unknown error" not in message


@pytest.mark.asyncio
async def test_the_status_is_reported_alongside_stderr() -> None:
    """Keeping stderr was never the problem; dropping the status was."""
    message = await _failure_message(
        125, stderr=b"docker: Error response from daemon: no such image"
    )

    assert "no such image" in message
    assert "125" in message


@pytest.mark.asyncio
async def test_a_reason_on_stdout_is_not_thrown_away() -> None:
    """docker does not reliably put the reason on stderr."""
    message = await _failure_message(1, stdout=b"cannot connect to the Docker daemon")

    assert "cannot connect to the Docker daemon" in message
    assert "1" in message


@pytest.mark.asyncio
async def test_silence_is_reported_as_silence() -> None:
    """No output is a fact about the failure, not a reason to invent one."""
    message = await _failure_message(137)

    assert "wrote nothing to stdout or stderr" in message
    assert "137" in message


@pytest.mark.asyncio
async def test_an_absent_status_is_not_reported_as_success() -> None:
    """A missing status must say so; 0 would read as the command having worked (#1341)."""
    message = await _failure_message(None)

    assert "no exit status" in message
    assert "exited 0" not in message
    assert "exited None" not in message


@pytest.mark.asyncio
async def test_a_signal_death_is_attributed_to_the_local_client() -> None:
    """-11 and 139 are the same event with opposite signs (#1295).

    Which one you are looking at depends entirely on WHICH process the number
    describes: CPython reports a signal death of its own child as negative,
    while a process killed inside the container returns a positive 128+N. The
    message has to name the process or the number cannot be read.
    """
    message = await _failure_message(-11)

    assert "-11" in message
    assert "local" in message and "docker run" in message
    assert "139" not in message, "an in-container 128+N status is not what this number is"
