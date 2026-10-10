"""The API's production wiring carries the operator's workspace limits (#1606).

The adapter tests in `syn-adapters` build `WorkspaceServiceConfig` themselves
and prove the downstream hop to `docker run`. They cannot see the upstream one:
`get_execution_processor` is where the API turns `SYN_WORKSPACE_*` into the
config it hands to `WorkspaceService.create`. Before #1606 that call site passed
`image=` alone, so the limits were dropped there too - and restoring that line
leaves every adapter test green.

So this test drives the real factory and inspects the config it hands over.
The stores it awaits first need live Postgres and MinIO; they are stubbed,
because none of them takes part in building the workspace config.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig

pytestmark = pytest.mark.unit


class _Captured(Exception):
    """Stops the factory once the workspace config has been handed over."""

    def __init__(self, config: WorkspaceServiceConfig | None) -> None:
        super().__init__("captured")
        self.config = config


def _capture(**kwargs: object) -> None:
    config = kwargs.get("config")
    assert config is None or isinstance(config, WorkspaceServiceConfig)
    raise _Captured(config)


async def test_operator_limits_reach_the_workspace_service() -> None:
    from syn_api import _wiring

    # Non-default on both axes, so a config built from dataclass defaults
    # (4096 / 2.0) cannot pass by coincidence.
    with (
        patch.dict(
            os.environ,
            {"SYN_WORKSPACE_MEMORY_LIMIT_MB": "1536", "SYN_WORKSPACE_CPU_LIMIT": "1.5"},
        ),
        patch.object(_wiring, "get_event_store", return_value=AsyncMock()),
        patch.object(_wiring, "get_artifact_storage", AsyncMock()),
        patch.object(_wiring, "get_conversation_storage", AsyncMock()),
        patch.object(_wiring, "get_projection_manager", MagicMock()),
        patch.object(_wiring, "get_claude_plugin_materializer", AsyncMock()),
        patch.object(_wiring, "get_skill_materializer", AsyncMock()),
        patch.object(_wiring.WorkspaceService, "create", side_effect=_capture),
        pytest.raises(_Captured) as captured,
    ):
        await _wiring.get_execution_processor()

    config = captured.value.config
    assert config is not None, "the wiring handed WorkspaceService no config at all"
    assert config.memory_limit_mb == 1536, (
        f"SYN_WORKSPACE_MEMORY_LIMIT_MB=1536 reached the workspace service as "
        f"{config.memory_limit_mb} MB; the wiring is not reading the setting"
    )
    assert config.cpu_limit_cores == 1.5, (
        f"SYN_WORKSPACE_CPU_LIMIT=1.5 reached the workspace service as "
        f"{config.cpu_limit_cores} cores; the wiring is not reading the setting"
    )
