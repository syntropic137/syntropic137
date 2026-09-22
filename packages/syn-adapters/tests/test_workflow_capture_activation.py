"""Controlled launches always receive persistent local capture, without a store."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_adapters.session_inventory.workspace_location import workspace_capture_location
from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_domain.contexts.agent_sessions import RunIdentity
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
)
from syn_shared.settings.session_store import SessionStoreSettings

pytestmark = pytest.mark.unit


async def test_workflow_launch_mounts_local_spool_without_remote_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AgenticIsolationAdapter(
        session_store=SessionStoreSettings(url=""),
        capture_source_instance_id="installation",
    )
    workspace = MagicMock(id="container", metadata={})
    provider = MagicMock(create=AsyncMock(return_value=workspace))
    monkeypatch.setattr(adapter, "_provider", provider)
    monkeypatch.setattr(
        "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
        AsyncMock(return_value="verified-image"),
    )
    config = IsolationConfig(
        execution_id="run",
        workspace_id="transient",
        capture_session_id="persisted-session",
        environment={
            "AGENTIC_SESSION_STORE_PROVIDER": "none",
            "AGENTIC_SESSION_STORE_EXPORTER_BIN": "/tmp/fake",
            "AGENTIC_CAPABILITIES": "memory",
        },
    )
    await adapter.create(config)
    created = provider.create.await_args.args[0]
    location = workspace_capture_location(
        RunIdentity(source_instance_id="installation", execution_id="run"), "persisted-session"
    )
    assert created.mounts[0].kind == "volume"
    assert created.mounts[0].host_path == location.volume_name
    assert created.mounts[0].container_path == "/spool"
    assert created.environment["AGENTIC_SESSION_STORE_PROVIDER"] == "local"
    assert created.environment["AGENTIC_SESSION_STORE_PARTITION"] == location.partition
    assert (
        created.environment["AGENTIC_SESSION_STORE_EXPORTER_BIN"]
        == "/usr/local/bin/apss-session-exporter"
    )
    assert "session-store" in created.environment["AGENTIC_CAPABILITIES"].split()
    assert "AGENTIC_SESSION_STORE_URL" not in created.environment
    assert "AGENTIC_SESSION_STORE_AUTH" not in created.environment
