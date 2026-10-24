"""The session-store start verdict, read through agentic-workspace's reader (#1516).

The fake executor here answers the way a real container does: the hostname on
the first line, then the entrypoint's ``capability_status`` rows. What these pin
is the seam syn137 owns - the argv round trip from the AW reader's shell string
to our argv executor, the translation into ``StartCapability``, and the
fail-open rule that an unreadable verdict is unknown, never an exception.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from syn_adapters.workspace_backends.agentic.capability_start import (
    SESSION_STORE_CAPABILITY,
    AgenticCapabilityStatusReader,
    StartCapability,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

pytestmark = pytest.mark.unit

_HOST = "ws-7f3a"


def _row(status: str, *, failed_checks: list[str], doctor_exit: int, host: str = _HOST) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "record": "capability_status",
            "capability": "session-store",
            "provider": "apss",
            "status": status,
            "policy": "degrade",
            "required": False,
            "doctor_exit": doctor_exit,
            "failed_checks": failed_checks,
            "host": host,
            "at": "2026-10-24T04:00:00Z",
        },
        separators=(",", ":"),
    )


class _Container:
    def __init__(self, stdout: str, exit_code: int = 0, *, raises: BaseException | None = None):
        self.stdout = stdout
        self.exit_code = exit_code
        self.raises = raises
        self.argv: list[str] | None = None

    async def __call__(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        if self.raises is not None:
            raise self.raises
        self.argv = command
        return ExecutionResult(
            exit_code=self.exit_code,
            success=self.exit_code == 0,
            duration_ms=1.0,
            stdout=self.stdout,
        )


async def _read(container: _Container) -> StartCapability | None:
    return await AgenticCapabilityStatusReader().read(container, SESSION_STORE_CAPABILITY)


async def test_a_degraded_start_is_read_with_its_failed_checks() -> None:
    container = _Container(
        f"{_HOST}\n{_row('degraded', failed_checks=['store_reachable'], doctor_exit=3)}\n"
    )

    start = await _read(container)

    assert start == StartCapability(
        capability="session-store",
        status="degraded",
        failed_checks=("store_reachable",),
        doctor_exit=3,
    )
    assert start.degraded
    # The AW reader's shell string came back to our executor as the exact argv
    # it quoted: `sh -c <script> <name> <audit dir> <capability>`.
    assert container.argv is not None
    assert container.argv[:2] == ["sh", "-c"]
    assert container.argv[-2:] == ["/var/agentic/session-store-doctor", "session-store"]


async def test_a_ready_start_is_not_degraded() -> None:
    start = await _read(_Container(f"{_HOST}\n{_row('ready', failed_checks=[], doctor_exit=0)}\n"))

    assert start is not None
    assert start.status == "ready"
    assert not start.degraded


async def test_no_row_is_unknown() -> None:
    assert await _read(_Container(f"{_HOST}\n")) is None


async def test_another_containers_row_is_not_this_workspaces_verdict() -> None:
    other = _row("degraded", failed_checks=["store_reachable"], doctor_exit=3, host="other")
    assert await _read(_Container(f"{_HOST}\n{other}\n")) is None


@pytest.mark.parametrize(
    "container",
    [
        _Container("", exit_code=2),
        _Container(f'{_HOST}\n{{"record":"capability_status","capability":"session-store","host":"{_HOST}"}}\n'),
        _Container("", raises=RuntimeError("docker exec failed")),
    ],
    ids=["read-exits-non-zero", "malformed-row", "exec-raises"],
)
async def test_an_unreadable_verdict_is_unknown_never_a_failure(container: _Container) -> None:
    assert await _read(container) is None


async def test_cancellation_propagates() -> None:
    with pytest.raises(asyncio.CancelledError):
        await _read(_Container("", raises=asyncio.CancelledError()))
