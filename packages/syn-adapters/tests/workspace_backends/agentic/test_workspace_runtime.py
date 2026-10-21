"""SYN_WORKSPACE_RUNTIME reaches the provider, and the provider's answer comes back.

Two hops, each tested at the thing that consumes it, not the object edited:

- out: the operator's env var -> settings -> `WorkspaceServiceConfig` -> the
  `SecurityConfig` the docker service builds -> the `WorkspaceConfig` handed to
  agentic-workspace's provider, whose resolver is what reads `.runtime`.
- back: what that provider's resolver recorded in `Workspace.metadata` -> the
  `IsolationHandle` -> the Lane 2 "Workspace runtime" log line.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation import SecurityConfig, WorkspaceConfig
from agentic_isolation import WorkspaceRuntime as AwRuntime
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.workspace_backends.agentic.runtime_mapping import (
    isolation_runtime_from_metadata,
    resolve_host_runtime,
    to_aw_runtime,
)
from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    build_isolation_config,
    provision_workspace,
)
from syn_adapters.workspace_backends.service.workspace_service import (
    WorkspaceBackend,
    WorkspaceService,
    WorkspaceServiceConfig,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationHandle,
    IsolationRuntime,
)
from syn_shared.doctor import EffectiveRuntime
from syn_shared.settings.workspace import WorkspaceRuntime, WorkspaceSettings

pytestmark = pytest.mark.unit

_PAIRS = [
    (WorkspaceRuntime.RUNC, AwRuntime.RUNC),
    (WorkspaceRuntime.GVISOR, AwRuntime.GVISOR),
    (WorkspaceRuntime.KATA, AwRuntime.KATA),
    (WorkspaceRuntime.SYSBOX, AwRuntime.SYSBOX),
]


@pytest.mark.parametrize(("ours", "theirs"), _PAIRS)
def test_each_setting_maps_to_its_aw_runtime(ours: WorkspaceRuntime, theirs: AwRuntime) -> None:
    assert to_aw_runtime(ours) is theirs


def test_unset_stays_auto() -> None:
    assert to_aw_runtime(None) is None


def test_every_aw_runtime_has_a_setting() -> None:
    """A runtime AW adds without one here would be unselectable; this names it."""
    assert {theirs for _, theirs in _PAIRS} == set(AwRuntime)
    assert {ours for ours, _ in _PAIRS} == set(WorkspaceRuntime)


async def _security_runtime_reaching_provider(env_value: str | None) -> AwRuntime | None:
    """Build the production docker service from the env var; return what the provider gets."""
    env = {} if env_value is None else {"SYN_WORKSPACE_RUNTIME": env_value}
    with patch.dict(os.environ, env, clear=True):
        settings = WorkspaceSettings(_env_file=None)  # type: ignore[call-arg]
    config = WorkspaceServiceConfig.from_settings(settings)
    service = WorkspaceService.create(
        backend=WorkspaceBackend.DOCKER, config=config, token_service=MagicMock()
    )

    workspace = MagicMock()
    workspace.id = "ws-1"
    workspace.metadata = {"workspace_dir": "/tmp/ws-1"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)
    provider.execute = AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr=""))

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    adapter = service._isolation
    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            side_effect=_passthrough,
        ),
    ):
        await adapter.create(
            build_isolation_config(
                config=config,
                workspace_id="ws-1",
                execution_id="exec-1",
                workflow_id=None,
                phase_id=None,
                extra_environment=None,
            )
        )
    ws_config: WorkspaceConfig = provider.create.call_args.args[0]
    assert ws_config.security is not None
    return ws_config.security.runtime


@pytest.mark.asyncio
@pytest.mark.parametrize(("ours", "theirs"), _PAIRS)
async def test_setting_reaches_the_provider(ours: WorkspaceRuntime, theirs: AwRuntime) -> None:
    assert await _security_runtime_reaching_provider(ours.value) is theirs


@pytest.mark.asyncio
async def test_unset_setting_reaches_the_provider_as_auto() -> None:
    assert await _security_runtime_reaching_provider(None) is None


@pytest.mark.parametrize(("ours", "theirs"), _PAIRS)
def test_recorded_effective_runtime_is_read_back(ours: WorkspaceRuntime, theirs: AwRuntime) -> None:
    # The keys and spellings are the ones AW's DockerProvider writes from its
    # ResolvedRuntime: str(requested or "auto"), str(effective).
    recorded = {"runtime_requested": "auto", "runtime_effective": str(theirs)}
    assert isolation_runtime_from_metadata(recorded) == IsolationRuntime(
        requested=None, effective=ours
    )


def test_explicit_request_is_read_back() -> None:
    recorded = {"runtime_requested": "kata", "runtime_effective": "kata"}
    assert isolation_runtime_from_metadata(recorded) == IsolationRuntime(
        requested=WorkspaceRuntime.KATA, effective=WorkspaceRuntime.KATA
    )


def test_provider_that_recorded_nothing_records_nothing() -> None:
    assert isolation_runtime_from_metadata({"workspace_dir": "/tmp/ws"}) is None


def test_unknown_recorded_runtime_is_not_guessed(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = isolation_runtime_from_metadata({"runtime_effective": "youki"})
    assert result is None
    assert "youki" in caplog.text


@pytest.mark.asyncio
async def test_adapter_handle_carries_what_the_provider_resolved() -> None:
    """Auto mode on a gVisor host: the handle says gvisor, not what was asked."""
    from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter

    workspace = MagicMock()
    workspace.id = "ws-1"
    workspace.metadata = {
        "workspace_dir": "/tmp/ws-1",
        "runtime_requested": "auto",
        "runtime_effective": "gvisor",
        "runtime_alias": "runsc",
    }
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)
    provider.execute = AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr=""))

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    adapter = AgenticIsolationAdapter()
    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            side_effect=_passthrough,
        ),
    ):
        handle = await adapter.create(
            build_isolation_config(
                config=WorkspaceServiceConfig(),
                workspace_id="ws-1",
                execution_id="exec-1",
                workflow_id=None,
                phase_id=None,
                extra_environment=None,
            )
        )

    assert handle.runtime == IsolationRuntime(requested=None, effective=WorkspaceRuntime.GVISOR)


@pytest.mark.asyncio
async def test_provisioning_logs_the_effective_runtime(caplog: pytest.LogCaptureFixture) -> None:
    """The Lane 2 record: one structured line per workspace, from the handle."""
    service = MagicMock()
    service._isolation.create = AsyncMock(
        return_value=IsolationHandle(
            isolation_id="iso-1",
            isolation_type="docker",
            # Auto that resolved to gVisor: the two fields differ, so a log
            # that wrote one from the other's source fails here.
            runtime=IsolationRuntime(requested=None, effective=WorkspaceRuntime.GVISOR),
        )
    )
    service._isolation.execute = AsyncMock(side_effect=RuntimeError("no manifest"))
    aggregate = MagicMock()
    config = build_isolation_config(
        config=WorkspaceServiceConfig(),
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id=None,
        phase_id="phase-2",
        extra_environment=None,
    )

    with caplog.at_level(logging.INFO):
        await provision_workspace(service, config, aggregate, "ws-1", with_sidecar=False)

    (record,) = [r for r in caplog.records if r.getMessage().startswith("Workspace runtime")]
    assert record.__dict__["runtime_requested"] == "auto"
    assert record.__dict__["runtime_effective"] == "gvisor"
    assert record.__dict__["workspace_id"] == "ws-1"
    assert record.__dict__["phase_id"] == "phase-2"


# The doctor's probe runs agentic-workspace's own resolver; only Docker's
# runtime registry is synthetic. Each host shape below is one `docker info`.
_RUNC_ONLY = {"runc": "runc"}
_GVISOR_HOST = {"runc": "runc", "runsc": "/usr/local/bin/runsc"}


type DockerHost = Callable[[dict[str, str]], None]


@pytest.fixture
def docker_host(monkeypatch: pytest.MonkeyPatch) -> DockerHost:
    def use(registry: dict[str, str]) -> None:
        monkeypatch.setattr(SecurityConfig, "_docker_runtimes", registry)
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/docker")

    return use


@pytest.mark.parametrize(
    ("registry", "effective", "alias"),
    [(_RUNC_ONLY, WorkspaceRuntime.RUNC, "runc"), (_GVISOR_HOST, WorkspaceRuntime.GVISOR, "runsc")],
)
def test_doctor_probe_reports_what_auto_resolves_to(
    docker_host: DockerHost, registry: dict[str, str], effective: WorkspaceRuntime, alias: str
) -> None:
    docker_host(registry)

    assert resolve_host_runtime(None) == EffectiveRuntime(
        effective=effective, alias=alias, error=None
    )


def test_doctor_probe_reports_an_explicit_runtime(docker_host: DockerHost) -> None:
    docker_host({**_GVISOR_HOST, "kata": "/opt/kata/bin/containerd-shim-kata-v2"})

    assert resolve_host_runtime(WorkspaceRuntime.KATA) == EffectiveRuntime(
        effective=WorkspaceRuntime.KATA, alias="kata", error=None
    )


def test_doctor_probe_reports_the_resolvers_refusal(docker_host: DockerHost) -> None:
    docker_host(_RUNC_ONLY)

    result = resolve_host_runtime(WorkspaceRuntime.KATA)

    assert result.effective is None
    assert result.error is not None
    assert "runtime kata was requested" in result.error
