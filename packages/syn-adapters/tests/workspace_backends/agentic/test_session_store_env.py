"""Tests for the session-store contract injected into workspace containers.

The single most important test here is
``TestDisabled::test_no_session_store_variables_when_url_unset`` — Syntropic137
must remain deployable as a full self-hosted stack by operators who have no
SeshMagic instance, and that is only true if the disabled path emits nothing.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.agentic.session_store_env import (
    DEPLOYMENT_SEPARATOR,
    apply_session_store_env,
    build_session_store_env,
    decode_tag_value,
    deployment_identity,
    encode_tag_value,
    sanitize_partition_segment,
)
from syn_shared.env_constants import (
    ENV_AGENTIC_SESSION_STORE_AUTH,
    ENV_AGENTIC_SESSION_STORE_DEPLOYMENT,
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

# These are pure/mocked and must run in CI's `pytest -m unit` job — an opt-in
# guarantee that CI never checks is not a guarantee.
pytestmark = pytest.mark.unit

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
    """Store configured: the full contract is supplied."""

    def test_every_required_variable_is_present(self) -> None:
        """DEPLOYMENT is reserved but OPTIONAL, so this is a subset check.

        It is in the contract set because a caller must not be able to supply
        it - the set is the reserved-names list used for stripping - but it is
        only emitted when this execution knows which deployment it belongs to.
        Emitting it empty would tell the store "deployment: nothing" rather
        than "deployment: unknown".
        """
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            workflow_id="wf-1",
            phase_id="phase-1",
        )
        assert set(env) <= set(SESSION_STORE_CONTRACT_ENV_VARS)
        assert set(env) == set(SESSION_STORE_CONTRACT_ENV_VARS) - {
            ENV_AGENTIC_SESSION_STORE_DEPLOYMENT
        }

    def test_the_deployment_variable_appears_when_supplied(self) -> None:
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            deployment="syntropic137__development",
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

    def test_spool_override_is_honoured(self) -> None:
        env = build_session_store_env(
            _enabled_settings(spool_dir="/var/spool/sessions"),
            execution_id="e",
            workspace_id="w",
        )
        assert env[ENV_AGENTIC_SESSION_STORE_SPOOL] == "/var/spool/sessions"


class TestTagIdentity:
    """Tags are the join key, so a tag value must still EQUAL the identifier.

    ``workflow_id`` and ``phase_id`` come from author-written workflow YAML that
    constrains only length (``workflow_definition.py``: ``min_length=1``,
    ``max_length=100``; no ``pattern``), so a delimiter is legal input, not an
    attack. Substituting delimiters made ``phase:a``, ``phase,a`` and ``phase_a``
    indistinguishable; percent-encoding keeps them distinct and reversible.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            "exec-abc",  # the realistic shape: encoding is the identity function
            "07f3a1e2-4c5b-4c9a-9f27-1a2b3c4d5e6f",
            "phase:a",
            "phase,a",
            "phase_a",
            "plan: step one",
            "a b",
            "100%",
            "%3A",  # an already-encoded-looking value must not double-decode wrong
            "ünïcode",
        ],
    )
    def test_tag_values_round_trip(self, raw: str) -> None:
        assert decode_tag_value(encode_tag_value(raw)) == raw

    def test_encoded_values_contain_no_framing_delimiters(self) -> None:
        for raw in ("phase:a", "phase,a", "plan: step one"):
            encoded = encode_tag_value(raw)
            assert "," not in encoded
            assert ":" not in encoded
            assert " " not in encoded

    def test_delimiter_variants_do_not_collide(self) -> None:
        """The collision this fix exists to remove."""
        variants = ["phase:a", "phase,a", "phase_a", "phase a"]
        assert len({encode_tag_value(v) for v in variants}) == len(variants)

    def test_realistic_identifiers_are_unchanged(self) -> None:
        """Encoding must be a no-op for every identifier that actually occurs,
        so no existing store row's join key shifts."""
        for raw in ("exec-9a3f21bc04de", "create-pr", "claude_first", "deep-dive", "research"):
            assert encode_tag_value(raw) == raw

    def test_identifiers_survive_the_full_tag_string(self) -> None:
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec,abc",
            workspace_id="ws:xyz",
            workflow_id="plan: step one",
            phase_id="phase_a",
        )
        tags = _tags_to_dict(env[ENV_AGENTIC_SESSION_STORE_TAGS])
        assert {k: decode_tag_value(v) for k, v in tags.items()} == {
            "source": "syntropic137",
            "execution_id": "exec,abc",
            "workspace_id": "ws:xyz",
            "workflow_id": "plan: step one",
            "phase_id": "phase_a",
        }

    def test_whitespace_only_identifier_is_dropped_not_emitted_blank(self) -> None:
        env = build_session_store_env(
            _enabled_settings(),
            execution_id="exec-abc",
            workspace_id="ws-xyz",
            phase_id="   ",
        )
        assert "phase_id" not in _tags_to_dict(env[ENV_AGENTIC_SESSION_STORE_TAGS])


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


async def _passthrough_verify(image_ref: str) -> str:
    """Stand in for the supply-chain gate, returning the reference unchanged."""
    return image_ref


def _mock_provider() -> MagicMock:
    workspace = MagicMock()
    workspace.id = "ws-123"
    workspace.metadata = {"workspace_dir": "/tmp/x"}
    provider = MagicMock()
    provider.create = AsyncMock(return_value=workspace)
    return provider


def _config(environment: dict[str, str] | None = None) -> object:
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
        IsolationConfig,
    )

    return IsolationConfig(
        execution_id="exec-abc",
        workspace_id="ws-xyz",
        workflow_id="wf-1",
        phase_id="phase-1",
        image="test:latest",
        environment=environment if environment is not None else {"EXISTING_VAR": "kept"},
    )


async def _create(
    settings: SessionStoreSettings,
    environment: dict[str, str] | None = None,
) -> MagicMock:
    """Provision through the real adapter against a mocked provider.

    The image supply-chain gate is stubbed out: these tests are about what
    lands in the container environment, and `test:latest` is deliberately not a
    verifiable reference. The gate has its own suite in
    tests/workspace_backends/test_image_verification.py.
    """
    adapter = AgenticIsolationAdapter(session_store=settings)
    provider = _mock_provider()
    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.agentic.adapter.verify_image_async",
            side_effect=_passthrough_verify,
        ),
    ):
        await adapter.create(_config(environment))  # type: ignore[arg-type]
    return provider


class TestAdapterIntegration:
    """The adapter is the seam that actually reaches the provider."""

    @pytest.mark.asyncio
    async def test_configured_store_reaches_the_provider(self) -> None:
        provider = await _create(_enabled_settings())
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
            # Which deployment produced this session. Only the adapter path
            # resolves this, from APP_ENVIRONMENT - which is "test" here. The
            # direct build_session_store_env test above passes no deployment
            # and correctly gets no tag.
            "deployment": "syntropic137__test",
        }
        # Pre-existing environment is preserved.
        assert ws_config.environment["EXISTING_VAR"] == "kept"

    @pytest.mark.asyncio
    async def test_unconfigured_store_changes_nothing(self) -> None:
        """Self-hostability guarantee at the real call site."""
        provider = await _create(_disabled_settings())
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
        provider = await _create(_enabled_settings())
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
            await adapter.create(_config())  # type: ignore[arg-type]

        assert STORE_TOKEN not in str(exc_info.value)


#: What a hostile (or merely confused) caller might pass as `extra_environment`
#: to redirect capture at a store of its own, or to switch capture on entirely.
HOSTILE_ENV: dict[str, str] = {
    ENV_AGENTIC_SESSION_STORE_PROVIDER: "seshmagic",
    ENV_AGENTIC_SESSION_STORE_URL: "https://attacker.example.com",
    ENV_AGENTIC_SESSION_STORE_AUTH: "attacker-token",
    ENV_AGENTIC_SESSION_STORE_SPOOL: "/attacker-spool",
    ENV_AGENTIC_SESSION_STORE_PARTITION: "someone-elses/partition",
    ENV_AGENTIC_SESSION_STORE_TAGS: "source:not-syn137",
}


class TestReservedKeys:
    """The contract variables are RESERVED — the adapter owns them.

    The public workspace path accepts arbitrary ``extra_environment``, so
    without this the opt-in switch is defeatable by any caller.
    """

    @pytest.mark.asyncio
    async def test_disabled_strips_caller_supplied_contract_variables(self) -> None:
        """THE most important test in this module.

        A self-hosted deployment with no store configured must not be able to
        start capturing because a caller passed the variables itself.
        """
        caller_env = {"EXISTING_VAR": "kept", **HOSTILE_ENV}
        provider = await _create(_disabled_settings(), caller_env)
        ws_config = provider.create.await_args.args[0]

        assert ws_config.environment == {"EXISTING_VAR": "kept"}
        assert not (set(SESSION_STORE_CONTRACT_ENV_VARS) & set(ws_config.environment))

    @pytest.mark.asyncio
    async def test_enabled_adapter_values_beat_caller_values(self) -> None:
        """A caller must not redirect capture to a different store or partition."""
        caller_env = {"EXISTING_VAR": "kept", **HOSTILE_ENV}
        provider = await _create(_enabled_settings(), caller_env)
        env = provider.create.await_args.args[0].environment

        assert env[ENV_AGENTIC_SESSION_STORE_URL] == STORE_URL
        assert env[ENV_AGENTIC_SESSION_STORE_AUTH] == STORE_TOKEN
        assert env[ENV_AGENTIC_SESSION_STORE_SPOOL] == DEFAULT_SPOOL_DIR
        assert env[ENV_AGENTIC_SESSION_STORE_PARTITION] == "exec-abc/ws-xyz"
        assert _tags_to_dict(env[ENV_AGENTIC_SESSION_STORE_TAGS])["source"] == "syntropic137"
        assert env["EXISTING_VAR"] == "kept"
        # Nothing distinctive to the caller survived anywhere in the environment.
        rendered = "\n".join(f"{k}={v}" for k, v in env.items())
        for marker in ("attacker", "someone-elses", "not-syn137"):
            assert marker not in rendered

    def test_stripping_is_logged_by_name_without_values(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An operator must be able to discover the silent override in logs, but
        the write token must never appear in one."""
        with caplog.at_level(logging.WARNING):
            env = apply_session_store_env(
                {**HOSTILE_ENV},
                _disabled_settings(),
                execution_id="exec-abc",
                workspace_id="ws-xyz",
            )

        assert env == {}
        text = caplog.text
        assert ENV_AGENTIC_SESSION_STORE_URL in text
        assert ENV_AGENTIC_SESSION_STORE_AUTH in text
        for value in HOSTILE_ENV.values():
            assert value not in text

    def test_caller_environment_is_not_mutated(self) -> None:
        caller_env = {"EXISTING_VAR": "kept", **HOSTILE_ENV}
        original = dict(caller_env)
        apply_session_store_env(
            caller_env,
            _enabled_settings(),
            execution_id="e",
            workspace_id="w",
        )
        assert caller_env == original

    def test_no_warning_when_caller_supplies_nothing_reserved(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            apply_session_store_env(
                {"EXISTING_VAR": "kept"},
                _enabled_settings(),
                execution_id="e",
                workspace_id="w",
            )
        assert not caplog.records


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


@pytest.mark.unit
class TestDeploymentIdentity:
    """`origin.environment` is the runtime CLASS; this is WHICH deployment.

    Every Syn137 workspace reports the same class, so without this a multi-tier
    install is unattributable in the corpus.
    """

    def test_uses_the_app_env_double_underscore_convention(self) -> None:
        assert deployment_identity("beta") == "syntropic137__beta"

    def test_tier_is_the_raw_app_environment_value_not_an_abbreviation(self) -> None:
        # AppEnvironment.DEVELOPMENT serialises as "development". A
        # development -> dev mapping would be a second source of truth that
        # drifts from the enum the rest of the platform switches on.
        assert deployment_identity("development") == "syntropic137__development"

    def test_splitting_on_the_first_separator_recovers_app_and_tier(self) -> None:
        app, _, tier = deployment_identity("production").partition(DEPLOYMENT_SEPARATOR)
        assert app == "syntropic137"
        assert tier == "production"
