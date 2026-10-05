"""A workspace's CPU weight travels from settings to the isolation adapter (#1600).

The control plane carries CONTROL_PLANE_CPU_SHARES; each workspace must carry a
LOWER weight, so that when workspaces oversubscribe the host's cores the api
and database still get scheduled. Syn owns the hops from
``SYN_WORKSPACE_CPU_SHARES`` to the ``IsolationConfig`` handed to the adapter;
emitting ``--cpu-shares`` is the Docker provider's job in agentic-workspace and
is tested there once it lands.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.service.workspace_lifecycle import (
    build_isolation_config,
)
from syn_adapters.workspace_backends.service.workspace_service import (
    WorkspaceServiceConfig,
)
from syn_shared.settings.infra import InfraSettings
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


def test_workspace_weight_is_below_the_control_plane() -> None:
    workspace = WorkspaceSettings().cpu_shares
    control_plane = InfraSettings().control_plane_cpu_shares

    assert workspace < control_plane
    assert WorkspaceServiceConfig().cpu_shares == workspace


def test_workspace_weight_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYN_WORKSPACE_CPU_SHARES", "256")

    assert WorkspaceSettings().cpu_shares == 256


def test_isolation_config_carries_the_configured_weight() -> None:
    """The hop the adapter reads: a non-default value proves it is not a default."""
    isolation = build_isolation_config(
        config=WorkspaceServiceConfig(cpu_shares=256),
        workspace_id="ws-1",
        execution_id="exec-1",
        workflow_id=None,
        phase_id=None,
        extra_environment=None,
    )

    assert isolation.security_policy.cpu_shares == 256
