"""Tests for AgenticIsolationAdapter error surfacing (P0-2 regression)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.workspace_backends.agentic.adapter import (
    AgenticIsolationAdapter,
    WorkspaceProvisionError,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _stub_image_verification() -> object:
    """Stub the supply-chain gate; these tests are about error surfacing.

    `test:latest` is deliberately not a verifiable reference. The gate's own
    behaviour is covered in tests/workspace_backends/test_image_verification.py.
    """

    async def _passthrough(image_ref: str) -> str:
        return image_ref

    with patch(
        "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
        side_effect=_passthrough,
    ) as stub:
        yield stub


@pytest.mark.asyncio
async def test_provision_failure_surfaces_real_message() -> None:
    """Underlying docker error must propagate as WorkspaceProvisionError with context.

    Regression: previously the error became a generic "Unknown error" by the time
    it reached `syn execution show`, leaving users unable to diagnose Docker
    socket-proxy denials (P0-2).
    """
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    adapter = AgenticIsolationAdapter()

    mock_provider = MagicMock()
    mock_provider.create = AsyncMock(
        side_effect=RuntimeError(
            "Failed to create container: docker: Error response from daemon: "
            "network agent-net not found"
        )
    )

    config = IsolationConfig(
        execution_id="exec-abc",
        workspace_id="ws-xyz",
        image="test:latest",
        environment={},
    )

    with (
        patch.object(adapter, "_provider", mock_provider),
        pytest.raises(WorkspaceProvisionError) as exc_info,
    ):
        await adapter.create(config)

    msg = str(exc_info.value)
    assert "exec-abc" in msg
    assert "network agent-net not found" in msg
    # And the original exception is chained so logs preserve the cause
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_provision_success_does_not_raise() -> None:
    """Happy path is unaffected by the error-wrap."""
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    adapter = AgenticIsolationAdapter()

    mock_workspace = MagicMock()
    mock_workspace.id = "ws-123"
    mock_workspace.metadata = {"workspace_dir": "/tmp/x"}

    mock_provider = MagicMock()
    mock_provider.create = AsyncMock(return_value=mock_workspace)
    mock_provider.execute = AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr=""))

    config = IsolationConfig(
        execution_id="exec-abc",
        workspace_id="ws-xyz",
        image="test:latest",
        environment={},
    )

    with patch.object(adapter, "_provider", mock_provider):
        handle = await adapter.create(config)

    assert handle.isolation_id == "ws-123"
    assert handle.isolation_type == "docker"


# --- Host-security refusals from agentic_isolation (#1398) -------------------


def _refusals() -> list[tuple[Exception, type[WorkspaceProvisionError], str]]:
    from agentic_isolation import (
        AppArmorProfileNotLoadedError,
        CodexSandboxPolicyError,
        DockerDetectionError,
    )

    from syn_adapters.workspace_backends.errors import (
        AppArmorProfileMissingError,
        CodexSandboxPolicyConflictError,
        DockerHostDetectionError,
        ProvisionFailureReason,
    )

    return [
        (
            AppArmorProfileNotLoadedError("agentic-codex-sandbox"),
            AppArmorProfileMissingError,
            ProvisionFailureReason.APPARMOR_PROFILE_NOT_LOADED,
        ),
        (
            CodexSandboxPolicyError("image does not declare codex"),
            CodexSandboxPolicyConflictError,
            ProvisionFailureReason.CODEX_SANDBOX_POLICY_CONFLICT,
        ),
        (
            DockerDetectionError("docker info exited 1: permission denied"),
            DockerHostDetectionError,
            ProvisionFailureReason.DOCKER_DETECTION_FAILED,
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(3))
async def test_host_security_refusal_is_a_typed_provision_failure(index: int) -> None:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    error, expected, reason = _refusals()[index]
    adapter = AgenticIsolationAdapter()
    mock_provider = MagicMock()
    mock_provider.create = AsyncMock(side_effect=error)
    config = IsolationConfig(
        execution_id="exec-abc", workspace_id="ws-xyz", image="test:latest", environment={}
    )
    with (
        patch.object(adapter, "_provider", mock_provider),
        pytest.raises(WorkspaceProvisionError) as exc_info,
    ):
        await adapter.create(config)
    assert type(exc_info.value) is expected
    assert exc_info.value.reason == reason
    assert exc_info.value.__cause__ is error
    assert "exec-abc" in str(exc_info.value)


def test_apparmor_failure_names_the_host_fix() -> None:
    from agentic_isolation import AppArmorProfileNotLoadedError, codex_sandbox_apparmor_profile_path

    from syn_adapters.workspace_backends.errors import AppArmorProfileMissingError
    from syn_adapters.workspace_backends.host_security import host_security_failure

    failure = host_security_failure(AppArmorProfileNotLoadedError("agentic-codex-sandbox"), "run")
    assert isinstance(failure, AppArmorProfileMissingError)
    assert failure.profile == "agentic-codex-sandbox"
    assert "just apparmor-setup" in failure.remedy
    assert f"apparmor_parser -r {codex_sandbox_apparmor_profile_path()}" in failure.remedy
    assert failure.remedy in str(failure)
    # The profile the remedy points at is really shipped with the pinned AW.
    assert codex_sandbox_apparmor_profile_path().is_file()


def test_generic_and_image_failures_keep_their_reasons() -> None:
    from syn_adapters.workspace_backends.errors import ProvisionFailureReason
    from syn_adapters.workspace_backends.image_verification import ImageVerificationError

    assert WorkspaceProvisionError("x").reason is ProvisionFailureReason.PROVIDER_FAILED
    assert ImageVerificationError("x").reason is ProvisionFailureReason.IMAGE_VERIFICATION_FAILED
