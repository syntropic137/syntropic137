"""Configured workspace limits reach `docker run` (#1606).

The limit used to be computed onto `IsolationConfig.security_policy` and then
dropped at `AgenticIsolationAdapter.create`, which built `WorkspaceConfig`
without `limits=`. Every object on either side of that hop looked right, so
these tests start at the operator's env var and end at the argv the real
`DockerProvider` would execute.

The CPU hints (#1607 follow-up) are asserted the same way: a value computed
correctly and dropped before `-e` would pass every test of the helper alone.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation import SecurityConfig, WorkspaceConfig
from agentic_isolation.providers.docker import WorkspaceDockerProvider

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.cpu_hints import cpu_hint_env
from syn_adapters.workspace_backends.service.workspace_lifecycle import build_isolation_config
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
    SecurityPolicy,
)
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


async def _docker_run_argv(
    phase_id: str | None,
    *,
    cpu_limit: str = "1.5",
    phase_environment: dict[str, str] | None = None,
) -> list[str]:
    """Provision through the adapter and render what Docker would be asked to run."""
    with patch.dict(
        os.environ,
        {"SYN_WORKSPACE_MEMORY_LIMIT_MB": "1536", "SYN_WORKSPACE_CPU_LIMIT": cpu_limit},
        clear=True,
    ):
        settings = WorkspaceSettings(_env_file=None)  # type: ignore[call-arg]

    isolation_config = build_isolation_config(
        config=WorkspaceServiceConfig.from_settings(settings),
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id="wf-1",
        phase_id=phase_id,
        extra_environment=phase_environment,
    )
    return await _render(isolation_config)


async def _render(isolation_config: IsolationConfig) -> list[str]:

    workspace = MagicMock()
    workspace.id = "ws-1"
    workspace.metadata = {"workspace_dir": "/tmp/ws-1"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)

    adapter = AgenticIsolationAdapter()

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
            side_effect=_passthrough,
        ),
    ):
        await adapter.create(isolation_config)

    ws_config: WorkspaceConfig = provider.create.call_args.args[0]
    return WorkspaceDockerProvider()._build_run_command(
        container_name="c-1",
        workspace_id="ws-1",
        workspace_dir=Path("/tmp/ws-1"),
        image=ws_config.image,
        config=ws_config,
        security=SecurityConfig.production(),
    )


@pytest.mark.asyncio
async def test_configured_limits_reach_docker_run() -> None:
    argv = await _docker_run_argv(phase_id="phase-7")

    assert "--memory=1536m" in argv
    assert "--cpus=1.5" in argv


@pytest.mark.asyncio
async def test_container_is_labelled_with_its_phase() -> None:
    argv = await _docker_run_argv(phase_id="phase-7")

    assert "--label=syn.phase_id=phase-7" in argv
    assert "--label=syn.execution_id=exec-1" in argv
    assert "--label=syn.workspace_id=ws-1" in argv


@pytest.mark.asyncio
async def test_workspace_without_a_phase_has_no_phase_label() -> None:
    argv = await _docker_run_argv(phase_id=None)

    assert not [arg for arg in argv if arg.startswith("--label=syn.phase_id")]


def _env_args(argv: list[str]) -> dict[str, str]:
    """The `-e KEY=VALUE` pairs of a docker argv, as a mapping."""
    pairs = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-e"]
    return dict(pair.split("=", 1) for pair in pairs)


_EXPECTED_HINT_KEYS = {
    "PYTEST_XDIST_AUTO_NUM_WORKERS",
    "CARGO_BUILD_JOBS",
    "MAKEFLAGS",
    "VITEST_MAX_WORKERS",
    "VITEST_MAX_THREADS",
    "VITEST_MAX_FORKS",
    "UV_CONCURRENT_BUILDS",
    "OMP_NUM_THREADS",
    "RAYON_NUM_THREADS",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("cpu_limit", "workers"), [("4", "4"), ("2.5", "3"), ("0.5", "1")])
async def test_cpu_limit_reaches_the_container_as_worker_hints(
    cpu_limit: str, workers: str
) -> None:
    """From SYN_WORKSPACE_CPU_LIMIT to `-e` on docker run, rounded up, at least 1."""
    argv = await _docker_run_argv(phase_id="phase-7", cpu_limit=cpu_limit)
    env = _env_args(argv)

    assert f"--cpus={cpu_limit}" in argv
    for key in _EXPECTED_HINT_KEYS - {"MAKEFLAGS"}:
        assert env.get(key) == workers, key
    assert env.get("MAKEFLAGS") == f"-j{workers}"
    assert "NODE_OPTIONS" not in env


@pytest.mark.asyncio
async def test_an_explicit_phase_value_wins_over_the_hint() -> None:
    argv = await _docker_run_argv(
        phase_id="phase-7",
        cpu_limit="4",
        phase_environment={"PYTEST_XDIST_AUTO_NUM_WORKERS": "1", "MAKEFLAGS": "-j1 -k"},
    )
    env = _env_args(argv)

    assert env["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "1"
    assert env["MAKEFLAGS"] == "-j1 -k"
    assert env["CARGO_BUILD_JOBS"] == "4"  # the others are still hinted


@pytest.mark.asyncio
async def test_no_cpu_limit_injects_no_hints() -> None:
    """Unreachable from settings today (cpu_limit is gt=0, default 2.0).

    Docker reads `--cpus=0` as unlimited, so the tools' own detection is right
    and nothing should second-guess it.
    """
    argv = await _render(
        IsolationConfig(
            execution_id="exec-1",
            workspace_id="ws-1",
            security_policy=SecurityPolicy(cpu_limit_cores=0),
        )
    )

    assert not _EXPECTED_HINT_KEYS & _env_args(argv).keys()


def test_the_helper_and_the_test_agree_on_the_variables() -> None:
    """A variable added to the helper without a test here is a silent hop."""
    assert cpu_hint_env(4).keys() == _EXPECTED_HINT_KEYS
    assert cpu_hint_env(None) == {}
