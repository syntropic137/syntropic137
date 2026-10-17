"""The Docker BackendKit and its credential policy (#1914).

Under HostCredentials the kit is the adapter as it was: capture only with a
capture source, every image through the cosign gate, `isolation_type="docker"`.
Under NoCredentials it refuses any image not approved for credential-free runs
and drops the session-store write token, the one credential source that lives
in the Docker adapter rather than the provision handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation.providers.base import ExecuteResult
from pydantic import SecretStr

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.session_store_env import (
    session_store_credential_bindings,
)
from syn_adapters.workspace_backends.backend_kit import BackendKit, CredentialFreeImageError
from syn_domain.contexts.orchestration._shared.workspace_credential_policy import (
    HOST_CREDENTIALS,
    NO_CREDENTIALS,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
)
from syn_shared.settings.session_store import SessionStoreSettings
from syn_shared.settings.workspace_images import (
    PINNED_DIGESTS,
    WorkspaceImageProvider,
    workspace_image_ref,
)

pytestmark = pytest.mark.unit

_CLAUDE_CLI = workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI)
# Invented: no stub image is pinned yet (step H). Never a real digest.
_STUB = "ghcr.io/example/scripted-stub@sha256:" + "19" * 32
_STORE_URL = "https://sessions.example.invalid"
_STORE_TOKEN = "FAKE1914-session-store-write-token"


def _store() -> SessionStoreSettings:
    return SessionStoreSettings(  # type: ignore[call-arg]
        _env_file=None, url=_STORE_URL, auth_token=SecretStr(_STORE_TOKEN)
    )


def _config(image: str | None = None) -> IsolationConfig:
    return IsolationConfig(
        execution_id="exec-1914", workspace_id="ws-1914", phase_id="p", image=image
    )


def _mock_provider() -> MagicMock:
    workspace = MagicMock()
    workspace.id = "ws-1914"
    workspace.metadata = {"workspace_dir": "/tmp/x"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)
    provider.execute = AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr=""))
    return provider


async def _passthrough(image_ref: str) -> str:
    return image_ref


class TestCredentialFreeKitRefusesToStart:
    def test_with_the_claude_cli_digest(self) -> None:
        assert PINNED_DIGESTS[WorkspaceImageProvider.CLAUDE_CLI] in _CLAUDE_CLI
        with pytest.raises(CredentialFreeImageError, match="refuses image"):
            BackendKit(default_image=_CLAUDE_CLI, credential_policy=NO_CREDENTIALS)

    @pytest.mark.parametrize("provider", list(WorkspaceImageProvider))
    def test_with_any_pinned_image_when_none_is_approved(
        self, provider: WorkspaceImageProvider
    ) -> None:
        """An allowlist, not a claude-cli denylist: omni-agent and toolchain are refused too."""
        with pytest.raises(CredentialFreeImageError):
            BackendKit(
                default_image=workspace_image_ref(provider), credential_policy=NO_CREDENTIALS
            )

    def test_through_the_adapter_too(self) -> None:
        kit_args = {"default_image": _CLAUDE_CLI, "credential_policy": NO_CREDENTIALS}
        with pytest.raises(CredentialFreeImageError):
            AgenticIsolationAdapter(kit=BackendKit(**kit_args))  # type: ignore[arg-type]

    async def test_an_approved_kit_refuses_a_per_run_image(self) -> None:
        kit = BackendKit(
            default_image=_STUB,
            credential_policy=NO_CREDENTIALS,
            credential_free_images=frozenset({_STUB}),
        )
        with (
            patch(
                "syn_adapters.workspace_backends.backend_kit.verify_image_async",
                side_effect=_passthrough,
            ),
            pytest.raises(CredentialFreeImageError),
        ):
            await kit.resolve_image(_CLAUDE_CLI)
        with patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            side_effect=_passthrough,
        ):
            assert await kit.resolve_image(None) == _STUB


class TestHostCredentialsKitIsTodaysAdapter:
    async def test_every_image_still_goes_through_the_cosign_gate(self) -> None:
        verify = AsyncMock(return_value="verified@sha256:" + "ab" * 32)
        adapter = AgenticIsolationAdapter(session_store=_store())
        provider = _mock_provider()
        with (
            patch.object(adapter, "_provider", provider),
            patch("syn_adapters.workspace_backends.backend_kit.verify_image_async", verify),
        ):
            handle = await adapter.create(_config(_CLAUDE_CLI))

        verify.assert_awaited_once_with(_CLAUDE_CLI)
        (ws_config,) = provider.create.call_args.args
        assert ws_config.image == "verified@sha256:" + "ab" * 32
        assert handle.isolation_type == "docker"
        assert ws_config.mounts == [], "no capture source, so no capture mount"
        assert adapter.credential_policy is HOST_CREDENTIALS
        assert session_store_credential_bindings(adapter._session_store), (
            "HostCredentials must still bind the session-store write token"
        )

    def test_the_kit_and_loose_arguments_cannot_both_be_given(self) -> None:
        with pytest.raises(ValueError, match="BackendKit"):
            AgenticIsolationAdapter(kit=BackendKit(), capture_source_instance_id="src")


class TestNoCredentialsDropsTheSessionStoreToken:
    async def test_no_binding_and_no_store_env(self) -> None:
        host = AgenticIsolationAdapter(session_store=_store())
        assert session_store_credential_bindings(host._session_store), (
            "positive control: the configured store does produce a binding"
        )

        kit = BackendKit(
            default_image=_STUB,
            credential_policy=NO_CREDENTIALS,
            credential_free_images=frozenset({_STUB}),
        )
        adapter = AgenticIsolationAdapter(session_store=_store(), kit=kit)
        provider = _mock_provider()
        with (
            patch.object(adapter, "_provider", provider),
            patch(
                "syn_adapters.workspace_backends.backend_kit.verify_image_async",
                side_effect=_passthrough,
            ),
        ):
            await adapter.create(_config())

        (ws_config,) = provider.create.call_args.args
        assert list(ws_config.credentials) == []
        scanned = f"{ws_config.environment!r} {ws_config.credentials!r} {ws_config.labels!r}"
        assert _STORE_TOKEN not in scanned
        assert _STORE_URL not in scanned
