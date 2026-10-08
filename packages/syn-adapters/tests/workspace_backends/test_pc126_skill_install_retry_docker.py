"""The skill-install timeout retry, proven at the Docker boundary (PC-126, B5).

The unit tests in `test_skill_install_survives_transport_segfault.py` feed
`install_skill` a hand-built `ExecutionResult(timed_out=True)`. That proves
the retry logic, not that a REAL hung `docker exec` ever produces that
result. This drives the real path end to end: `install_skill` ->
`ManagedWorkspace.execute` -> `AgenticIsolationAdapter.execute` ->
`WorkspaceDockerProvider` -> `docker exec` with its deadline, against a live
container whose `skills` binary hangs on demand.

What the hang looks like at the boundary: the deadline kills the `docker
exec` CLIENT, not the process inside the container, so the hung first
installer is still running when the retry starts. The real installer deletes
its destination before copying, so a first attempt that wakes up late would
delete what the retry installed. The fake does exactly that, after its hang,
and the first test waits past that moment: it passes only because the
timed-out installer is reaped before the retry.

Needs Docker; skipped when `docker info` does not answer within 10s.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import anyio
import pytest
from agentic_isolation import SecurityConfig

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    IsolationHandle,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    ProvisionStep,
    ProvisionStepTimeoutError,
    failure_account,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.skill_install import (
    install_skill,
)
from syn_shared.settings import reset_settings
from syn_shared.upstream_failure import UpstreamFailureKind

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService

#: Small, ubiquitous, and has /bin/sh, which is all the fake installer needs.
_IMAGE = "alpine:3"

#: The smallest deadline the setting allows (ge=10): a hang costs this per attempt.
_TIMEOUT_SECONDS = 10

#: How long a hung call sleeps before it wakes and deletes the install, as
#: the real installer's `rm -rf` of its destination would.
_HANG_SECONDS = 2 * _TIMEOUT_SECONDS + 3

#: Stands in for the real `skills` CLI. Records every call. The first
#: /workspace/.hang_calls calls hang past the deadline and then wipe the
#: install; every later call installs.
_FAKE_SKILLS = f"""#!/bin/sh
echo "$*" >> /workspace/.calls
calls=$(wc -l < /workspace/.calls)
if [ "$calls" -le "$(cat /workspace/.hang_calls)" ]; then
  sleep {_HANG_SECONDS}
  rm -rf /workspace/.installed
  exit 0
fi
mkdir -p /workspace/.installed
basename "$2" > "/workspace/.installed/$(basename "$2")"
"""


def _docker_answers() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.skipif(not _docker_answers(), reason="docker info did not answer within 10s"),
]


@dataclass(frozen=True)
class _Service:
    """The one attribute `ManagedWorkspace.execute` reads off its service."""

    _isolation: AgenticIsolationAdapter


@dataclass(frozen=True)
class _Live:
    workspace: ManagedWorkspace
    adapter: AgenticIsolationAdapter
    handle: IsolationHandle

    async def sh(self, script: str) -> str:
        result = await self.adapter.execute(self.handle, ["sh", "-c", script], timeout_seconds=30)
        assert result.exit_code == 0, result.stderr
        return result.stdout


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def skill_install_timeout(monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    monkeypatch.setenv("SKILL_INSTALL_TIMEOUT_SECONDS", str(_TIMEOUT_SECONDS))
    reset_settings()
    yield _TIMEOUT_SECONDS
    monkeypatch.delenv("SKILL_INSTALL_TIMEOUT_SECONDS")
    reset_settings()


@pytest.fixture
async def live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skill_install_timeout: int
) -> AsyncIterator[_Live]:
    # The default agent-net only exists inside a deployment.
    monkeypatch.setenv("SYN_AGENT_NETWORK", "bridge")
    adapter = AgenticIsolationAdapter(
        default_image=_IMAGE,
        security=SecurityConfig.development(),
        workspace_container_dir=str(tmp_path),
    )

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    # The supply-chain gate refuses an unpinned public image; it is not what
    # is under test here (tests/workspace_backends/test_image_verification.py).
    with patch(
        "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
        side_effect=_passthrough,
    ):
        handle = await adapter.create(
            IsolationConfig(execution_id="exec-pc126", workspace_id="ws-pc126", image=_IMAGE)
        )
    try:
        workspace = ManagedWorkspace(
            workspace_id="ws-pc126",
            execution_id="exec-pc126",
            aggregate=MagicMock(),
            isolation_handle=handle,
            sidecar_handle=None,
            _service=cast("WorkspaceService", _Service(adapter)),
        )
        result = _Live(workspace, adapter, handle)
        await result.sh(
            "mkdir -p /usr/local/bin && "
            f"printf %s {shlex.quote(_FAKE_SKILLS)} > /usr/local/bin/skills && "
            "chmod +x /usr/local/bin/skills && : > /workspace/.calls"
        )
        yield result
    finally:
        await adapter.destroy(handle)


async def test_a_hung_first_install_is_retried_once_and_succeeds(live: _Live) -> None:
    await live.sh("echo 1 > /workspace/.hang_calls")

    await install_skill(live.workspace, "review", "/workspace/.syn-skills/review", "claude-code")

    calls = (await live.sh("cat /workspace/.calls")).splitlines()
    assert calls == ["add /workspace/.syn-skills/review --agent claude-code -y"] * 2
    # Past the moment the hung first attempt would have woken and wiped the
    # install: it was reaped before the retry, so the install is intact.
    await anyio.sleep(_HANG_SECONDS - _TIMEOUT_SECONDS + 2)
    assert (await live.sh("cat /workspace/.installed/review")).strip() == "review"
    assert (await live.sh("ps -o args | grep -c '[s]kills add' || true")).strip() == "0"


async def test_a_second_hang_fails_naming_the_step_as_resumable(live: _Live) -> None:
    await live.sh("echo 2 > /workspace/.hang_calls")

    with pytest.raises(ProvisionStepTimeoutError, match=r"skill_install.*'review'.*10s") as raised:
        await install_skill(live.workspace, "review", "/workspace/.syn-skills/review", "codex")

    assert len((await live.sh("cat /workspace/.calls")).splitlines()) == 2
    assert raised.value.step is ProvisionStep.SKILL_INSTALL
    assert raised.value.attempts == 2
    assert raised.value.timeout_seconds == _TIMEOUT_SECONDS
    account = failure_account(raised.value)
    assert account.upstream is UpstreamFailureKind.UNAVAILABLE
    assert account.upstream.is_transient
    assert "the phase is resumable" in account.upstream.account()
