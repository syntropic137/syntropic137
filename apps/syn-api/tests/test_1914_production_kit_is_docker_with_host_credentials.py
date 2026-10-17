"""Production still builds the Docker BackendKit under HostCredentials (#1914).

A refactor of the composition point breaks wiring, not tests: every unit test
builds its own kit. So this builds the workspace service through the same
function `get_execution_processor` calls, and reads what it produced.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.agentic import AgenticIsolationAdapter
from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_api._wiring import build_workspace_service
from syn_domain.contexts.orchestration._shared.workspace_credential_policy import HostCredentials
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


def test_the_production_workspace_service_is_the_docker_kit_with_host_credentials() -> None:
    service = build_workspace_service(
        WorkspaceServiceConfig.from_settings(WorkspaceSettings()), "source-1914"
    )

    isolation = service._isolation
    assert isinstance(isolation, AgenticIsolationAdapter)
    kit = isolation._kit
    assert isinstance(service.credential_policy, HostCredentials)
    assert kit.credential_policy is service.credential_policy
    assert kit.isolation_type == "docker"
    # Capture stays exactly as conditional as before the kit: on, because
    # production passed a capture source.
    assert kit.capture_source_instance_id == "source-1914"
    assert kit.captures_sessions
