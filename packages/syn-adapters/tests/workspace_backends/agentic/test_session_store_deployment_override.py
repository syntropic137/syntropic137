"""``SYN_SESSION_STORE_DEPLOYMENT`` overrides the derived deployment identity.

The override exists for one concrete failure: two installs that share an
APP_ENVIRONMENT are different deployments, and without it their sessions are
indistinguishable in the store. Migrating a selfhost install between hosts is
the case that produced it - both report ``syntropic137__selfhost``.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.agentic.capture_observation import build_expectations
from syn_adapters.workspace_backends.agentic.session_store_env import (
    DEPLOYMENT_SEPARATOR,
    deployment_identity,
)
from syn_shared.settings.session_store import SessionStoreSettings, usable_deployment

pytestmark = pytest.mark.unit

_STORE_URL = "http://store.invalid:18090"


class TestDeploymentIdentity:
    def test_derives_from_app_environment_when_no_override(self) -> None:
        assert deployment_identity("selfhost") == "syntropic137__selfhost"

    def test_override_replaces_the_derived_identity(self) -> None:
        assert deployment_identity("selfhost", "syntropic137__vps") == "syntropic137__vps"

    def test_empty_override_falls_back_to_derived(self) -> None:
        """ "" is the "unset" signal, not a deployment named empty string."""
        assert deployment_identity("selfhost", "") == "syntropic137__selfhost"

    def test_override_need_not_use_the_separator(self) -> None:
        """The convention is ours; an operator's own identifier is still theirs."""
        assert deployment_identity("selfhost", "acme-prod") == "acme-prod"


class TestOverrideValidation:
    @pytest.mark.parametrize(
        "value",
        ["syntropic137__vps", "acme-prod", "tenant.a", "a", "9"],
    )
    def test_plain_identifiers_are_usable(self, value: str) -> None:
        assert usable_deployment(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "syn/vps",  # path separator
            "syn vps",  # space
            "syn\nvps",  # newline could forge a second posture record
            "syntropic137__vpś",  # non-ASCII homoglyph
            "x" * 65,  # over the length bound
            "",
            "   ",
        ],
    )
    def test_unusable_values_are_rejected(self, value: str) -> None:
        assert usable_deployment(value) == ""

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        assert usable_deployment("  syntropic137__vps  ") == "syntropic137__vps"

    def test_unusable_override_is_reported_not_silently_dropped(self) -> None:
        settings = SessionStoreSettings(url=_STORE_URL, deployment="syn/vps")
        assert settings.display_deployment == ""
        assert settings.has_unusable_deployment is True

    def test_unset_override_is_not_reported_as_unusable(self) -> None:
        settings = SessionStoreSettings(url=_STORE_URL)
        assert settings.display_deployment == ""
        assert settings.has_unusable_deployment is False


class TestExpectationsAgreeWithInjectedValue:
    """The injected value and the expectation are compared on every execution.

    `capture_result._mismatch` fails a capture whose reported deployment differs
    from the expectation, so an override honoured on only one side would report
    every single capture as failed. This is the regression that would matter.
    """

    def test_expectations_use_the_override(self) -> None:
        settings = SessionStoreSettings(url=_STORE_URL, deployment="syntropic137__vps")
        expectations = build_expectations(settings, "selfhost", expect_sessions=True)
        assert expectations is not None
        assert expectations.deployment == "syntropic137__vps"

    def test_expectations_match_what_the_adapter_would_inject(self) -> None:
        settings = SessionStoreSettings(url=_STORE_URL, deployment="syntropic137__vps")
        injected = deployment_identity("selfhost", settings.display_deployment)
        expectations = build_expectations(settings, "selfhost", expect_sessions=True)
        assert expectations is not None
        assert expectations.deployment == injected

    def test_unusable_override_still_agrees_on_the_fallback(self) -> None:
        """A rejected override must degrade on BOTH sides, not just one."""
        settings = SessionStoreSettings(url=_STORE_URL, deployment="syn/vps")
        injected = deployment_identity("selfhost", settings.display_deployment)
        expectations = build_expectations(settings, "selfhost", expect_sessions=True)
        assert expectations is not None
        assert injected == f"syntropic137{DEPLOYMENT_SEPARATOR}selfhost"
        assert expectations.deployment == injected

    def test_no_override_agrees_on_the_derived_identity(self) -> None:
        settings = SessionStoreSettings(url=_STORE_URL)
        injected = deployment_identity("selfhost", settings.display_deployment)
        expectations = build_expectations(settings, "selfhost", expect_sessions=True)
        assert expectations is not None
        assert expectations.deployment == injected == "syntropic137__selfhost"


class TestEnvVarBinding:
    def test_reads_syn_session_store_deployment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYN_SESSION_STORE_DEPLOYMENT", "syntropic137__vps")
        settings = SessionStoreSettings(url=_STORE_URL)
        assert settings.display_deployment == "syntropic137__vps"
