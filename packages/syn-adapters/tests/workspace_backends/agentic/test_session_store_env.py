"""Tests for the session-store contract injected into workspace containers.

The single most important test here is
``TestDisabled::test_no_session_store_variables_when_url_unset`` — Syntropic137
must remain deployable as a full self-hosted stack by operators who have no
SeshMagic instance, and that is only true if the disabled path emits nothing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.session_store_env import (
    build_session_store_env,
    sanitize_partition_segment,
)
from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_AUTH,
    ENV_AGENTIC_SESSION_STORE_PARTITION,
    ENV_AGENTIC_SESSION_STORE_PROVIDER,
    ENV_AGENTIC_SESSION_STORE_SPOOL,
    ENV_AGENTIC_SESSION_STORE_TAGS,
    ENV_AGENTIC_SESSION_STORE_URL,
    SESSION_STORE_CONTRACT_ENV_VARS,
)
from syn_shared.settings.session_store import (
    DEFAULT_SPOOL_DIR,
    SESHMAGIC_PROVIDER,
    SessionStoreSettings,
)

STORE_URL = "https://sessions.example.com"
STORE_TOKEN = "s3cr3t-write-token"


def _enabled_settings(**overrides: object) -> SessionStoreSettings:
    """Settings with a store configured, isolated from ambient env and .env."""
    kwargs: dict[str, object] = {
        "_env_file": None,
        "url": STORE_URL,
        "auth_token": SecretStr(STORE_TOKEN),
    }
    kwargs.update(overrides)
    return SessionStoreSettings(**kwargs)  # type: ignore[arg-type]


def _disabled_settings() -> SessionStoreSettings:
    """Settings as a self-hoster who never configured a store would see them."""
    return SessionStoreSettings(_env_file=None, url=None)  # type: ignore[call-arg]


def _tags_to_dict(raw: str) -> dict[str, str]:
    return dict(pair.split(":", 1) for pair in raw.split(",") if pair)


class TestDisabled:
    """Opt-in guarantee: no store configured means nothing is emitted."""

    def test_no_session_store_variables_when_url_unset(self) -> None:
        """THE self-hostability test. Not one contract variable may appear.

        Not ``PROVIDER=none``, not empty values — nothing. With
        AGENTIC_SESSION_STORE_PROVIDER unset the in-container capability does no
        init, no doctor and no finalize, which is what makes behaviour
        byte-identical for an operator with no SeshMagic instance.
        """
        env = build_session_store_env(
            _disabled_settings(),
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            workflow_id="wf-1",
            phase_id="phase-1",
        )
        assert env == {}

    def test_empty_url_string_is_treated_as_disabled(self) -> None:
        """``SYN_SESSION_STORE_URL=`` in a .env template must mean OFF."""
        settings = SessionStoreSettings(_env_file=None, url="   ")  # type: ignore[call-arg]
        assert settings.is_enabled is False
        assert build_session_store_env(settings, execution_id="e", workspace_id="w") == {}

    def test_token_without_url_stays_disabled(self) -> None:
        """A stray token must not switch capture on by itself."""
        settings = SessionStoreSettings(  # type: ignore[call-arg]
            _env_file=None, url=None, auth_token=SecretStr(STORE_TOKEN)
        )
        assert build_session_store_env(settings, execution_id="e", workspace_id="w") == {}


class TestEnabled:
    """Store configured: the full six-variable contract is supplied."""

    def test_all_six_variables_present(self) -> None:
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            workflow_id="wf-1",
            phase_id="phase-1",
        )
        assert set(env) == set(SESSION_STORE_CONTRACT_ENV_VARS)

    def test_provider_url_spool_values(self) -> None:
        env = build_session_store_env(
            _enabled_settings(), execution_id="exec-abc", workspace_id="ws-xyz"
        )
        assert env[ENV_AGENTIC_SESSION_STORE_PROVIDER] == SESHMAGIC_PROVIDER
        assert env[ENV_AGENTIC_SESSION_STORE_PROVIDER] == "seshmagic"
        assert env[ENV_AGENTIC_SESSION_STORE_URL] == STORE_URL
        assert env[ENV_AGENTIC_SESSION_STORE_SPOOL] == DEFAULT_SPOOL_DIR
        assert env[ENV_AGENTIC_SESSION_STORE_SPOOL] == "/spool"

    def test_auth_carries_the_token(self) -> None:
        env = build_session_store_env(
            _enabled_settings(), execution_id="exec-abc", workspace_id="ws-xyz"
        )
        assert env[ENV_AGENTIC_SESSION_STORE_AUTH] == STORE_TOKEN

    def test_auth_is_empty_when_store_needs_no_token(self) -> None:
        """An unauthenticated store is legitimate; a missing token must not
        silently disable capture for an operator who configured a URL."""
        settings = _enabled_settings(auth_token=None)
        env = build_session_store_env(settings, execution_id="e", workspace_id="w")
        assert env[ENV_AGENTIC_SESSION_STORE_AUTH] == ""
        assert env[ENV_AGENTIC_SESSION_STORE_PROVIDER] == SESHMAGIC_PROVIDER

    def test_partition_is_execution_then_workspace(self) -> None:
        env = build_session_store_env(
            _enabled_settings(), execution_id="exec-abc", workspace_id="ws-xyz"
        )
        assert env[ENV_AGENTIC_SESSION_STORE_PARTITION] == "exec-abc/ws-xyz"

    def test_tags_carry_all_available_context(self) -> None:
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            workflow_id="wf-1",
            phase_id="phase-1",
        )
        assert _tags_to_dict(env[ENV_AGENTIC_SESSION_STORE_TAGS]) == {
            "source": "syntropic137",
            "execution_id": "exec-abc",
            "workspace_id": "ws-xyz",
            "workflow_id": "wf-1",
            "phase_id": "phase-1",
        }

    def test_optional_tags_omitted_when_absent(self) -> None:
        """workflow_id/phase_id are optional on IsolationConfig; a tag must
        never claim data that was not there."""
        env = build_session_store_env(
            _enabled_settings(), execution_id="exec-abc", workspace_id="ws-xyz"
        )
        tags = _tags_to_dict(env[ENV_AGENTIC_SESSION_STORE_TAGS])
        assert "workflow_id" not in tags
        assert "phase_id" not in tags
        assert tags["execution_id"] == "exec-abc"
        assert tags["workspace_id"] == "ws-xyz"

    def test_tag_delimiters_are_stripped_from_values(self) -> None:
        """A value containing ``,`` or ``:`` would corrupt the tag string."""
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec,abc",
            workspace_id="ws:xyz",
        )
        tags = _tags_to_dict(env[ENV_AGENTIC_SESSION_STORE_TAGS])
        assert tags["execution_id"] == "exec_abc"
        assert tags["workspace_id"] == "ws_xyz"

    def test_spool_override_is_honoured(self) -> None:
        env = build_session_store_env(
            _enabled_settings(spool_dir="/var/spool/sessions"),
            execution_id="e",
            workspace_id="w",
        )
        assert env[ENV_AGENTIC_SESSION_STORE_SPOOL] == "/var/spool/sessions"


class TestPartitionSafety:
    """The capability HARD-FAILS the workspace on an unsafe partition."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("exec-abc", "exec-abc"),
            ("/absolute", "_absolute"),
            ("..", "unknown"),
            ("../../etc/passwd", "_._etc_passwd"),
            ("a/b", "a_b"),
            ("a\\b", "a_b"),
            (".hidden", "hidden"),
            ("", "unknown"),
            (None, "unknown"),
            ("   ", "___"),
            ("exec id", "exec_id"),
            ("../..", "_"),
        ],
    )
    def test_segment_sanitisation(self, raw: str | None, expected: str) -> None:
        assert sanitize_partition_segment(raw) == expected

    @pytest.mark.parametrize(
        ("execution_id", "workspace_id"),
        [
            ("/etc", "/passwd"),
            ("..", ".."),
            ("../../..", "../.."),
            ("a/../../b", "c/../d"),
            ("", ""),
        ],
    )
    def test_partition_is_always_relative_and_traversal_free(
        self, execution_id: str, workspace_id: str
    ) -> None:
        env = build_session_store_env(
            _enabled_settings(), execution_id=execution_id, workspace_id=workspace_id
        )
        partition = env[ENV_AGENTIC_SESSION_STORE_PARTITION]

        assert not partition.startswith("/")
        assert ".." not in partition
        # Exactly two segments, both non-empty.
        segments = partition.split("/")
        assert len(segments) == 2
        assert all(segments)


class TestAdapterIntegration:
    """The adapter is the seam that actually reaches the provider."""

    @staticmethod
    def _mock_provider() -> MagicMock:
        workspace = MagicMock()
        workspace.id = "ws-123"
        workspace.metadata = {"workspace_dir": "/tmp/x"}
        provider = MagicMock()
        provider.create = AsyncMock(return_value=workspace)
        return provider

    @staticmethod
    def _config() -> object:
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
            IsolationConfig,
        )

        return IsolationConfig(
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            workflow_id="wf-1",
            phase_id="phase-1",
            image="test:latest",
            environment={"EXISTING_VAR": "kept"},
        )

    async def _create(self, settings: SessionStoreSettings) -> MagicMock:
        adapter = AgenticIsolationAdapter(session_store=settings)
        provider = self._mock_provider()
        with patch.object(adapter, "_provider", provider):
            await adapter.create(self._config())  # type: ignore[arg-type]
        return provider

    @pytest.mark.asyncio
    async def test_configured_store_reaches_the_provider(self) -> None:
        provider = await self._create(_enabled_settings())
        ws_config = provider.create.await_args.args[0]

        assert set(SESSION_STORE_CONTRACT_ENV_VARS) <= set(ws_config.environment)
        assert ws_config.environment[ENV_AGENTIC_SESSION_STORE_URL] == STORE_URL
        assert ws_config.environment[ENV_AGENTIC_SESSION_STORE_AUTH] == STORE_TOKEN
        assert ws_config.environment[ENV_AGENTIC_SESSION_STORE_PARTITION] == "exec-abc/ws-xyz"
        assert _tags_to_dict(ws_config.environment[ENV_AGENTIC_SESSION_STORE_TAGS]) == {
            "source": "syntropic137",
            "execution_id": "exec-abc",
            "workspace_id": "ws-xyz",
            "workflow_id": "wf-1",
            "phase_id": "phase-1",
        }
        # Pre-existing environment is preserved.
        assert ws_config.environment["EXISTING_VAR"] == "kept"

    @pytest.mark.asyncio
    async def test_unconfigured_store_changes_nothing(self) -> None:
        """Self-hostability guarantee at the real call site."""
        provider = await self._create(_disabled_settings())
        ws_config = provider.create.await_args.args[0]

        assert ws_config.environment == {"EXISTING_VAR": "kept"}
        assert not (set(SESSION_STORE_CONTRACT_ENV_VARS) & set(ws_config.environment))
        assert ws_config.labels == {
            "syn.execution_id": "exec-abc",
            "syn.workspace_id": "ws-xyz",
        }

    @pytest.mark.asyncio
    async def test_token_never_lands_in_labels(self) -> None:
        """Labels are readable via ``docker inspect`` — no credential there."""
        provider = await self._create(_enabled_settings())
        ws_config = provider.create.await_args.args[0]

        assert STORE_TOKEN not in "".join(ws_config.labels.values())
        assert STORE_TOKEN not in "".join(ws_config.labels)

    @pytest.mark.asyncio
    async def test_token_absent_from_provisioning_error_message(self) -> None:
        """A docker failure must not leak the write token into logs or the CLI."""
        from syn_adapters.workspace_backends.errors import WorkspaceProvisionError

        adapter = AgenticIsolationAdapter(session_store=_enabled_settings())
        provider = MagicMock()
        provider.create = AsyncMock(side_effect=RuntimeError("network agent-net not found"))

        with (
            patch.object(adapter, "_provider", provider),
            pytest.raises(WorkspaceProvisionError) as exc_info,
        ):
            await adapter.create(self._config())  # type: ignore[arg-type]

        assert STORE_TOKEN not in str(exc_info.value)


class TestSecretHandling:
    """The write token is a credential."""

    def test_token_is_a_secret_str(self) -> None:
        settings = _enabled_settings()
        assert isinstance(settings.auth_token, SecretStr)

    def test_repr_does_not_leak_the_token(self) -> None:
        settings = _enabled_settings()
        assert STORE_TOKEN not in repr(settings)
        assert STORE_TOKEN not in str(settings)
        assert STORE_TOKEN not in str(settings.auth_token)
