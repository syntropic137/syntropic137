"""Regression tests for the configuration architecture (ADR-004).

Guards against the class of bugs that started this cleanup: a script
hitting the wrong port because a default URL drifted out of sync with
the actual stack topology.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from syn_shared.settings.constants import (
    DEFAULT_DEV_API_URL,
    DEFAULT_SELFHOST_API_URL,
    DEV_API_HOST_PORT,
    ENV_SYN_PUBLIC_HOSTNAME,
    SELFHOST_GATEWAY_PORT,
)
from syn_shared.settings.dev_tooling import DevToolingSettings, get_dev_api_url
from syn_shared.settings.infra import InfraSettings


class TestGetDevApiUrl:
    """get_dev_api_url() is the single entry point for dev tool API URLs."""

    def test_default_is_dev_port(self) -> None:
        """Default must point at the dev stack (9137), never selfhost (8137)."""
        with patch.dict(os.environ, {}, clear=True):
            url = get_dev_api_url()
        assert url == DEFAULT_DEV_API_URL
        assert str(DEV_API_HOST_PORT) in url
        assert str(SELFHOST_GATEWAY_PORT) not in url

    def test_env_override(self) -> None:
        """DEV__API_URL env var takes precedence over the default."""
        with patch.dict(os.environ, {"DEV__API_URL": "http://remote:4000"}, clear=True):
            url = get_dev_api_url()
        assert url == "http://remote:4000"

    def test_settings_field_uses_constant(self) -> None:
        """DevToolingSettings.api_url default must come from the constant."""
        with patch.dict(os.environ, {}, clear=True):
            settings = DevToolingSettings(_env_file=None)
        assert settings.api_url == DEFAULT_DEV_API_URL


class TestPortConstants:
    """Port constants must stay in sync with the stack topology."""

    def test_dev_and_selfhost_ports_differ(self) -> None:
        """Dev and selfhost must never share a port - that's the original bug."""
        assert DEV_API_HOST_PORT != SELFHOST_GATEWAY_PORT

    def test_default_urls_use_correct_ports(self) -> None:
        assert f":{DEV_API_HOST_PORT}" in DEFAULT_DEV_API_URL
        assert f":{SELFHOST_GATEWAY_PORT}" in DEFAULT_SELFHOST_API_URL


class TestSynPublicHostname:
    """SYN_PUBLIC_HOSTNAME replaced SYN_DOMAIN - guard the rename."""

    def test_infra_settings_env_var_name(self) -> None:
        """The InfraSettings field must map to SYN_PUBLIC_HOSTNAME, not SYN_DOMAIN."""
        field = InfraSettings.model_fields["syn_public_hostname"]
        assert field is not None
        # Verify no field named syn_domain exists
        assert "syn_domain" not in InfraSettings.model_fields

    def test_env_var_constant_matches_settings(self) -> None:
        """The constant must match what Pydantic generates."""
        assert ENV_SYN_PUBLIC_HOSTNAME == "SYN_PUBLIC_HOSTNAME"

    def test_env_override(self) -> None:
        """SYN_PUBLIC_HOSTNAME env var should populate the field."""
        with patch.dict(os.environ, {"SYN_PUBLIC_HOSTNAME": "syn.example.com"}, clear=True):
            settings = InfraSettings(_env_file=None)
        assert settings.syn_public_hostname == "syn.example.com"
