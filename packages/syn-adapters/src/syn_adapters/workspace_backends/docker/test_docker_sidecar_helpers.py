"""What a failed sidecar start records about the failure (#1158).

`run_sidecar_container` shells out to `docker run` and raised with nothing but
that process's stderr, dropping `returncode` entirely. That is the same discard
as the setup phase's, and it produces the same ambiguity: "docker refused" and
"docker was killed" arrive as the same sentence.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from syn_adapters.workspace_backends.docker.docker_sidecar_helpers import run_sidecar_container

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@contextmanager
def _docker_exiting(returncode: int, *, stderr: bytes) -> Iterator[None]:
    """Stand in for the `docker run` subprocess with a chosen ending."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    proc.returncode = returncode
    with patch(
        "syn_adapters.workspace_backends.docker.docker_sidecar_helpers"
        ".asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        yield


async def test_a_docker_run_that_refused_reports_what_docker_said() -> None:
    """An exit status the process chose: its stderr IS the reason, so quote it."""
    with (
        _docker_exiting(125, stderr=b"docker: network syn-agents not found.\n"),
        pytest.raises(RuntimeError) as raised,
    ):
        await run_sidecar_container(["docker", "run", "-d", "img"])

    message = str(raised.value)
    assert "exited 125" in message, message
    assert "network syn-agents not found" in message, message


async def test_a_docker_run_that_was_killed_is_not_reported_as_docker_refusing() -> None:
    """A signal death: the status is the fact, and stderr is not an error.

    `docker run` pulling an image writes progress to stderr, so promoting it -
    which is what this code did, having thrown the status away - produced a
    RuntimeError whose text described a download going normally.
    """
    progress = b"latest: Pulling from syntropic137/sidecar\n"
    with _docker_exiting(-9, stderr=progress), pytest.raises(RuntimeError) as raised:
        await run_sidecar_container(["docker", "run", "-d", "img"])

    message = str(raised.value)
    assert "SIGKILL" in message, message
    assert "-9" in message, message
    assert message.index("SIGKILL") < message.index("Pulling from"), message
