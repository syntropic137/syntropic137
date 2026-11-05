"""A phase's pids request reaches its container, is recorded, and is held to the ceiling (okrs-51p.30).

Unlike memory, pids are not a pooled host budget: no ledger is involved, so
only the limit, the record and the refusal are measured here.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from syn_adapters.workspace_backends.memory.memory_adapter import MemoryIsolationAdapter
from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_domain.contexts.orchestration import WorkspacePidsOverCapError, WorkspaceResourceRequest
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _test_environment():
    with patch.dict(os.environ, {"APP_ENVIRONMENT": "test"}):
        yield


def _service(*, limit: int = 256, max_pids: int = 4096) -> WorkspaceService:
    return WorkspaceService.create(
        backend=WorkspaceBackend.MEMORY,
        config=WorkspaceServiceConfig(pids_limit=limit, pids_max=max_pids),
    )


def _container_pids(service: WorkspaceService, isolation_id: str) -> int:
    isolation = service._isolation
    assert isinstance(isolation, MemoryIsolationAdapter)
    return isolation._instances[isolation_id].config.security_policy.pids_limit


def _recorded_pids(workspace: object) -> int:
    events = list(workspace.aggregate._uncommitted_events)  # type: ignore[attr-defined]
    created = next(e.event for e in events if e.event.event_type == "WorkspaceCreated")
    return created.security_settings["pids_limit"]


async def test_the_request_is_the_container_pids_limit_and_is_recorded() -> None:
    service = _service()

    async with service.create_workspace(
        execution_id="exec-1",
        phase_id="build",
        with_sidecar=False,
        resources=WorkspaceResourceRequest(pids_limit=2048),
    ) as workspace:
        assert _container_pids(service, workspace.isolation_handle.isolation_id) == 2048
        assert _recorded_pids(workspace) == 2048


async def test_no_request_is_the_configured_default() -> None:
    service = _service(limit=512, max_pids=512)

    async with service.create_workspace(execution_id="exec-1", with_sidecar=False) as workspace:
        assert _container_pids(service, workspace.isolation_handle.isolation_id) == 512
        assert _recorded_pids(workspace) == 512


async def test_a_memory_only_request_keeps_the_default_pids_limit() -> None:
    service = _service()

    async with service.create_workspace(
        execution_id="exec-1",
        with_sidecar=False,
        resources=WorkspaceResourceRequest(memory_mb=2048),
    ) as workspace:
        assert _container_pids(service, workspace.isolation_handle.isolation_id) == 256


async def test_a_pids_request_above_the_ceiling_is_refused_before_any_container() -> None:
    service = _service(max_pids=1024)
    isolation = service._isolation
    assert isinstance(isolation, MemoryIsolationAdapter)

    with pytest.raises(WorkspacePidsOverCapError, match="build"):
        async with service.create_workspace(
            execution_id="exec-1",
            phase_id="build",
            with_sidecar=False,
            resources=WorkspaceResourceRequest(pids_limit=2048),
        ):
            pytest.fail("a refused workspace must never be entered")

    assert isolation._instances == {}


def test_the_pids_ceiling_comes_from_settings_and_unset_means_the_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        unset = WorkspaceServiceConfig.from_settings(WorkspaceSettings(_env_file=None))
        assert unset.pids_max == unset.pids_limit == 256
    env = {"SYN_WORKSPACE_PIDS_LIMIT": "512", "SYN_WORKSPACE_PIDS_MAX": "4096"}
    with patch.dict(os.environ, env, clear=True):
        raised = WorkspaceServiceConfig.from_settings(WorkspaceSettings(_env_file=None))
        assert (raised.pids_limit, raised.pids_max) == (512, 4096)


@pytest.mark.parametrize(
    "env",
    [
        {"SYN_WORKSPACE_PIDS_LIMIT": "1024", "SYN_WORKSPACE_PIDS_MAX": "512"},
        {"SYN_WORKSPACE_PIDS_LIMIT": "32"},
    ],
    ids=["ceiling-below-default", "default-below-floor"],
)
def test_a_bad_pids_setting_is_refused_at_startup(env: dict[str, str]) -> None:
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError):
        WorkspaceSettings(_env_file=None)
