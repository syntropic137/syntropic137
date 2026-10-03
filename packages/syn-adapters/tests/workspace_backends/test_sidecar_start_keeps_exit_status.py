"""A failed sidecar start keeps the local Docker client's evidence (#1247)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import (
    run_sidecar_container,
)

pytestmark = pytest.mark.unit

_CMD = ["docker", "run", "-d", "syn-sidecar:test"]


class _FinishedProc:
    def __init__(self, returncode: int | None, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


async def _failure_message(
    returncode: int | None,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> str:
    proc = _FinishedProc(returncode, stdout, stderr)

    async def _spawn(*_args: object, **_kwargs: object) -> _FinishedProc:
        return proc

    with patch("asyncio.create_subprocess_exec", new=_spawn), pytest.raises(RuntimeError) as raised:
        await run_sidecar_container(_CMD)
    return str(raised.value)


@pytest.mark.asyncio
async def test_empty_output_still_reports_the_exit_status() -> None:
    message = await _failure_message(125)

    assert "exited 125" in message
    assert "printed nothing" in message
    assert "Unknown error" not in message


@pytest.mark.asyncio
async def test_the_status_is_reported_alongside_stderr() -> None:
    message = await _failure_message(
        125,
        stderr=b"docker: Error response from daemon: no such image",
    )

    assert "exited 125" in message
    assert "no such image" in message


@pytest.mark.asyncio
async def test_a_reason_on_stdout_is_not_thrown_away() -> None:
    message = await _failure_message(1, stdout=b"cannot connect to the Docker daemon")

    assert "exited 1" in message
    assert "cannot connect to the Docker daemon" in message


@pytest.mark.asyncio
async def test_an_absent_status_is_not_reported_as_success() -> None:
    message = await _failure_message(None)

    assert "no exit status" in message
    assert "exited 0" not in message
    assert "exited None" not in message


@pytest.mark.asyncio
async def test_a_signal_death_is_attributed_to_the_local_client() -> None:
    message = await _failure_message(-11)

    assert "SIGSEGV" in message
    assert "local" in message and "docker run" in message
    assert "139" not in message
