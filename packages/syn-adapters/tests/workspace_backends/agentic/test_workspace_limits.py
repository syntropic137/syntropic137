"""Configured workspace limits reach `docker run` (#1606).

The limit used to be computed onto `IsolationConfig.security_policy` and then
dropped at `AgenticIsolationAdapter.create`, which built `WorkspaceConfig`
without `limits=`. The CPU limit must also reach the tools: `--cpus` sets only a
CFS quota, so `nproc` still reports every host core and `pytest -n auto`,
vitest, cargo and make oversubscribe it unless told the real count. Every object on either side of that hop looked right, so
these tests start at the operator's env var and end at the argv the real
`DockerProvider` would execute.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation import SecurityConfig, WorkspaceConfig
from agentic_isolation.providers.docker import WorkspaceDockerProvider

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.cpu_hints import cpu_concurrency_env
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
    return await _render_docker_run(isolation_config)


async def _render_docker_run(isolation_config: IsolationConfig) -> list[str]:
    """Create through the adapter against a double provider; render the real argv."""
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


_HINT_KEYS = (
    "PYTEST_XDIST_AUTO_NUM_WORKERS",
    "VITEST_MAX_WORKERS",
    "VITEST_MAX_THREADS",
    "VITEST_MAX_FORKS",
    "CARGO_BUILD_JOBS",
    "MAKEFLAGS",
    "UV_CONCURRENT_BUILDS",
    "OMP_NUM_THREADS",
    "RAYON_NUM_THREADS",
)


def _env_flags(argv: list[str]) -> dict[str, str]:
    """The `-e KEY=VALUE` pairs of a docker run argv."""
    pairs = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-e"]
    return dict(pair.split("=", 1) for pair in pairs)


@pytest.mark.asyncio
@pytest.mark.parametrize(("cpu_limit", "expected"), [("4", "4"), ("2.5", "3")])
async def test_cpu_limit_sizes_tools_in_docker_run(cpu_limit: str, expected: str) -> None:
    env = _env_flags(await _docker_run_argv("phase-7", cpu_limit=cpu_limit))

    assert {key: env.get(key) for key in _HINT_KEYS} == {
        "PYTEST_XDIST_AUTO_NUM_WORKERS": expected,
        "VITEST_MAX_WORKERS": expected,
        "VITEST_MAX_THREADS": expected,
        "VITEST_MAX_FORKS": expected,
        "CARGO_BUILD_JOBS": expected,
        "MAKEFLAGS": f"-j{expected}",
        "UV_CONCURRENT_BUILDS": expected,
        "OMP_NUM_THREADS": expected,
        "RAYON_NUM_THREADS": expected,
    }
    # NODE_OPTIONS carries unrelated flags and does not size workers.
    assert "NODE_OPTIONS" not in env


@pytest.mark.asyncio
async def test_explicit_phase_environment_wins() -> None:
    env = _env_flags(
        await _docker_run_argv(
            "phase-7",
            cpu_limit="4",
            phase_environment={"PYTEST_XDIST_AUTO_NUM_WORKERS": "1", "MAKEFLAGS": ""},
        )
    )

    assert env["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "1"
    assert env["MAKEFLAGS"] == ""
    assert env["CARGO_BUILD_JOBS"] == "4"


def test_fractional_limit_below_one_still_allows_one_worker() -> None:
    assert cpu_concurrency_env(0.25)["CARGO_BUILD_JOBS"] == "1"


@pytest.mark.parametrize("cpu_limit_cores", [None, 0.0])
def test_no_cpu_limit_injects_nothing(cpu_limit_cores: float | None) -> None:
    # Production cannot reach this today: SYN_WORKSPACE_CPU_LIMIT is gt=0 with
    # a default of 2.0. Docker reads 0 as "no limit", so this is what an
    # unlimited workspace would get.
    assert cpu_concurrency_env(cpu_limit_cores) == {}


@pytest.mark.asyncio
async def test_no_cpu_limit_puts_no_hints_on_docker_run() -> None:
    """The same, at the consumer: `--cpus=0` (unlimited) carries no `-e` hints."""
    argv = await _render_docker_run(
        IsolationConfig(
            execution_id="exec-1",
            workspace_id="ws-1",
            security_policy=SecurityPolicy(cpu_limit_cores=0),
        )
    )

    assert not set(_HINT_KEYS) & _env_flags(argv).keys()
