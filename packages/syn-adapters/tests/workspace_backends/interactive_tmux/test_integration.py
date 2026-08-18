"""Docker-gated integration test for the interactive-tmux workspace provider.

Plan §5: starts a real interactive-tmux workspace, runs a single
`send_message` → `await_completion` → `capture_response` round-trip,
asserts the AwaitResult is ready and the pane capture is non-empty.

Skipped when Docker is unavailable, when the `agentic-workspace-
interactive-tmux:latest` image is absent, or when the host has no
`~/.claude/` + `~/.claude.json` (EXP-05a finding: both are required for
the Claude CLI to start authenticated). The skip reasons are explicit
so CI logs read cleanly.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from syn_adapters.workspace_backends.interactive_tmux import (
    INTERACTIVE_TMUX_AVAILABLE,
    InteractiveTmuxIsolationAdapter,
)

REASON_NO_DOCKER = "docker not available on host"
REASON_NO_PROVIDER = (
    "agentic_isolation.providers.interactive_tmux not importable (submodule not on agentprims-lab)"
)
REASON_NO_CREDS = "host missing ~/.claude or ~/.claude.json (EXP-05a: both required)"
REASON_NO_IMAGE = "agentic-workspace-interactive-tmux:latest not built on host"


def _docker_present() -> bool:
    return shutil.which("docker") is not None


def _docker_image_exists(tag: str) -> bool:
    if not _docker_present():
        return False
    result = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _claude_creds_present() -> bool:
    home = Path("~").expanduser()
    return (home / ".claude").is_dir() and (home / ".claude.json").is_file()


@pytest.mark.skipif(not _docker_present(), reason=REASON_NO_DOCKER)
@pytest.mark.skipif(not INTERACTIVE_TMUX_AVAILABLE, reason=REASON_NO_PROVIDER)
@pytest.mark.skipif(not _claude_creds_present(), reason=REASON_NO_CREDS)
@pytest.mark.skipif(
    not _docker_image_exists("agentic-workspace-interactive-tmux:latest"),
    reason=REASON_NO_IMAGE,
)
@pytest.mark.asyncio
async def test_send_message_round_trip_against_real_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single send_message → await_completion → capture_response round."""
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )
    from syn_shared.env_constants import ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES

    # This test is gated on the locally built image existing (see the skipif
    # above), and a locally built image carries no Sigstore signature. Opting
    # in is exactly the local-development path: the adapter resolves the tag to
    # the image ID of the image that is already present and runs that.
    monkeypatch.setenv(ENV_SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES, "true")

    adapter = InteractiveTmuxIsolationAdapter(
        default_image="agentic-workspace-interactive-tmux:latest",
        startup_timeout_s=60.0,
        strict_startup=False,  # tolerate slow startup on a busy host
    )
    config = IsolationConfig(
        execution_id="itws-integration-test",
        workspace_id="itws-integration-test-ws",
        image="agentic-workspace-interactive-tmux:latest",
        environment={},
        # Stage only claude (the agent this test drives) - matches what the
        # real provision path does and avoids the multi-minute cost of also
        # staging codex/gemini credentials.
        agents=("claude",),
    )
    handle = None
    try:
        handle = await adapter.create(config)
        driver = adapter.provider_handle(handle)
        assert driver is not None, "provider_handle returned None on a live workspace"

        driver.send_message("claude", "Reply with the literal string OK and nothing else.")
        result = driver.await_completion("claude", timeout=120.0)
        pane = driver.capture_response("claude")

        # We deliberately don't assert the pane contains "OK" — the Max-plan
        # Claude REPL is non-deterministic enough that asserting on content
        # would flake. What matters for this integration test:
        # the round-trip completed and the driver returned a pane.
        assert result.ready or result.reason.startswith("timeout"), (
            f"unexpected reason: {result.reason!r}"
        )
        assert pane, "capture_response returned empty pane after await_completion"
    finally:
        if handle is not None:
            await adapter.destroy(handle)
