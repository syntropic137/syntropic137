"""A phase's ``resources.pids_limit`` reaches agentic-workspace's ``--pids-limit`` (okrs-51p.30).

The workspace's process limit was agentic-workspace's hardcoded
``SecurityConfig.pids_limit=256``, and threads count against it: cargo,
libtest, ``node --test`` and lavapipe suites fork-fail with EAGAIN under it.
syn137 now owns the default (``SYN_WORKSPACE_PIDS_LIMIT``) and a phase may
raise it. The limit travels ``WorkspaceService`` -> ``SecurityPolicy`` ->
``AgenticIsolationAdapter.create`` -> ``WorkspaceConfig.security``, the
per-workspace override the Docker provider prefers to its own policy. These
tests start at the service config and end at the ``docker run`` argv the
REAL provider builds, so the provider's choice of policy is exercised too.

The override is a ``dataclasses.replace`` of the adapter's policy, so the
image-derived hardening (runtime, AppArmor, seccomp) must survive it.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from agentic_isolation import SecurityConfig
from agentic_isolation.config import WorkspaceRuntime
from agentic_isolation.providers.docker import WorkspaceDockerProvider

from syn_adapters.workspace_backends.agentic.adapter import (
    AgenticIsolationAdapter,
    WorkspaceProvisionError,
)
from syn_adapters.workspace_backends.service.workspace_lifecycle import build_isolation_config
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_shared.settings.session_store import SessionStoreSettings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: A policy no default produces, so a replace that rebuilt it from defaults
#: instead of copying it would be caught.
_PINNED = dataclasses.replace(
    SecurityConfig.production(),
    apparmor_profile="syn-test-profile",
    tmpfs_home=False,
    runtime=WorkspaceRuntime.RUNC,
)


class _ArgvCaptured(Exception):
    """Raised in place of ``docker run`` once its argv is captured."""


def _docker_info(template: str) -> str:
    """The Docker host as these tests pin it: runc only, AppArmor on. No daemon is asked."""
    return '{"runc": {"path": "runc"}}' if "Runtimes" in template else '["name=apparmor"]'


async def _docker_run_argv(pids_limit: int | None, tmp_path: Path) -> list[str]:
    """Create through the adapter and the REAL Docker provider; return the ``docker run`` argv.

    Only the daemon is replaced: image inspection, the network and the
    ``docker run`` subprocess itself. So which policy the provider picks
    (``config.security`` over its own) is exercised, not restated.
    """
    isolation_config = build_isolation_config(
        config=WorkspaceServiceConfig(pids_limit=256, pids_max=4096),
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id="build",
        extra_environment=None,
        pids_limit=pids_limit,
    )
    # The provider's own policy says 256, so only config.security can say 2048.
    provider = WorkspaceDockerProvider(security=_PINNED, workspace_base_dir=tmp_path)
    # Pinned off: left to get_settings(), a store configured by the
    # environment or another test adds a credential binding this provider
    # (built with no resolver) refuses before docker run.
    adapter = AgenticIsolationAdapter(
        security=_PINNED, session_store=SessionStoreSettings(url=None, _env_file=None)
    )
    captured: list[str] = []

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    async def _run(*argv: str, **_: object) -> None:
        # After the failed run the provider cleans up (stop, rm): refused the same way.
        if argv[:2] == ("docker", "run"):
            captured.extend(argv)
        raise _ArgvCaptured

    with (
        patch.object(adapter, "_provider", provider),
        patch.object(provider, "_inspect_image", AsyncMock(return_value=("sha256:img", {}))),
        patch.object(provider, "_ensure_network", AsyncMock()),
        patch.object(SecurityConfig, "_docker_info", staticmethod(_docker_info)),
        # The host's kernel is not asked either: a Linux runner with securityfs
        # would report the pinned profile as not loaded and refuse the run.
        patch("agentic_isolation.config.apparmor_profile_loaded", return_value=True),
        patch(
            "agentic_isolation.providers.docker.asyncio.create_subprocess_exec",
            side_effect=_run,
        ),
        patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            side_effect=_passthrough,
        ),
        pytest.raises(WorkspaceProvisionError) as refused,
    ):
        await adapter.create(isolation_config)

    # Anything but the stubbed docker run is the real reason, so say it.
    assert isinstance(refused.value.__cause__, _ArgvCaptured), refused.value
    assert captured, "docker run was never reached"
    return captured


def _security_args(argv: list[str]) -> list[str]:
    return [a for a in argv if a.startswith(("--pids-limit", "--security-opt", "--tmpfs"))]


@pytest.mark.asyncio
async def test_a_phase_pids_request_is_the_workspace_pids_limit(tmp_path: Path) -> None:
    argv = await _docker_run_argv(2048, tmp_path)

    assert "--pids-limit=2048" in argv
    assert "--pids-limit=256" not in argv


@pytest.mark.asyncio
async def test_no_request_is_the_default_of_256_as_before(tmp_path: Path) -> None:
    argv = await _docker_run_argv(None, tmp_path)

    assert "--pids-limit=256" in argv


@pytest.mark.asyncio
async def test_the_override_keeps_every_other_security_field(tmp_path: Path) -> None:
    raised = _security_args(await _docker_run_argv(2048, tmp_path))
    default = _security_args(await _docker_run_argv(None, tmp_path))

    assert [a for a in raised if not a.startswith("--pids-limit")] == [
        a for a in default if not a.startswith("--pids-limit")
    ]
    assert "--security-opt=apparmor=syn-test-profile" in raised
    assert _PINNED.pids_limit == 256, "the adapter's own policy must not be mutated"
