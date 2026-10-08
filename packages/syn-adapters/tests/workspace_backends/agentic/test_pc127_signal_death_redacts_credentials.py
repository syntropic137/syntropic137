"""A signal-death diagnostic never carries the launch's credentials (PC-127, ADR-072).

The agent's platform token rides the ``docker exec -e`` argv. When the agent
dies on a signal, that argv is retained in ``SignalDeath`` and logged at ERROR,
so this drives the real stream adapter to a signal exit and reads both.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from syn_adapters.diagnostics.signal_capture import REDACTED, redact_environment
from syn_adapters.platform_access import WorkspacePlatformGrant
from syn_adapters.workspace_backends.agentic import stream_adapter
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationBackendType,
    IsolationHandle,
)

pytestmark = pytest.mark.unit

_MARKER = "synpt_SYNTHETIC_MARKER_NOT_A_CREDENTIAL"


@pytest.mark.asyncio
async def test_signal_death_keeps_the_command_and_drops_the_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    grant = WorkspacePlatformGrant("http://envoy-proxy:8081/syn-platform", _MARKER)

    async def one_line(*_args: object) -> object:
        yield "{}"

    monkeypatch.setattr(stream_adapter, "read_lines", one_line)
    monkeypatch.setattr(stream_adapter, "_cleanup_process", AsyncMock(return_value=139))
    monkeypatch.setattr(stream_adapter.asyncio, "create_subprocess_exec", AsyncMock())
    adapter = stream_adapter.AgenticEventStreamAdapter()
    adapter.set_provider(object())
    handle = IsolationHandle(
        isolation_id="ws-pc127",
        isolation_type=IsolationBackendType.DOCKER_HARDENED,
        workspace_path="/workspace",
    )

    with caplog.at_level(logging.ERROR):
        async for _ in adapter.stream(handle, ["claude"], environment=grant.env):
            pass

    death = adapter.last_signal_death
    assert death is not None
    assert _MARKER not in " ".join(death.command)
    assert _MARKER not in caplog.text
    # Still a useful diagnostic: the signal, the variable's name, the command.
    assert "SIGSEGV" in caplog.text
    assert f"SYN_API_TOKEN={REDACTED}" in death.command
    assert "claude" in death.command


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["-e", "K=secret"], ["-e", f"K={REDACTED}"]),
        (["--env", "K=secret"], ["--env", f"K={REDACTED}"]),
        (["-eK=secret"], [f"-eK={REDACTED}"]),
        (["--env=K=secret"], [f"--env=K={REDACTED}"]),
        (["-i", "-w", "/workspace", "ctr"], ["-i", "-w", "/workspace", "ctr"]),
    ],
)
def test_every_docker_env_spelling_is_redacted(argv: list[str], expected: list[str]) -> None:
    assert list(redact_environment(["docker", "exec", *argv])) == ["docker", "exec", *expected]
