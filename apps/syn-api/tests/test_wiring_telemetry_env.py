"""Tests for workspace telemetry environment variable injection.

Verifies that _build_workspace_telemetry_env() correctly injects OTel env vars
into workspace containers when a collector URL is configured.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from syn_api._wiring import _build_workspace_telemetry_env
from syn_shared.env_constants import (
    ENV_CLAUDE_CODE_ENABLE_TELEMETRY,
    ENV_OTEL_EXPORTER_OTLP_ENDPOINT,
)


def _mock_settings(collector_url: str | None) -> MagicMock:
    settings = MagicMock()
    settings.collector_url = collector_url
    return settings


def test_telemetry_env_with_collector_url() -> None:
    """When collector_url is set, both OTel env vars are returned."""
    with patch(
        "syn_shared.settings.get_settings", return_value=_mock_settings("http://collector:8080")
    ):
        env = _build_workspace_telemetry_env()

    assert env[ENV_CLAUDE_CODE_ENABLE_TELEMETRY] == "1"
    assert env[ENV_OTEL_EXPORTER_OTLP_ENDPOINT] == "http://collector:8080"
    assert len(env) == 2


def test_telemetry_env_without_collector_url() -> None:
    """When collector_url is None, empty dict is returned (graceful no-op)."""
    with patch("syn_shared.settings.get_settings", return_value=_mock_settings(None)):
        env = _build_workspace_telemetry_env()

    assert env == {}


def test_telemetry_env_endpoint_matches_collector_url() -> None:
    """OTLP endpoint value exactly matches whatever collector_url is set to."""
    url = "http://my-custom-collector:9090"
    with patch("syn_shared.settings.get_settings", return_value=_mock_settings(url)):
        env = _build_workspace_telemetry_env()

    assert env[ENV_OTEL_EXPORTER_OTLP_ENDPOINT] == url


def test_env_var_names_use_constants() -> None:
    """Env var key names match the canonical constants — no typos."""
    assert ENV_CLAUDE_CODE_ENABLE_TELEMETRY == "CLAUDE_CODE_ENABLE_TELEMETRY"
    assert ENV_OTEL_EXPORTER_OTLP_ENDPOINT == "OTEL_EXPORTER_OTLP_ENDPOINT"


@pytest.mark.parametrize(
    "url",
    [
        "http://collector:8080",
        "http://localhost:8138",
        "http://syn-collector:8080",
    ],
)
def test_telemetry_env_various_urls(url: str) -> None:
    """Accepts any valid collector URL format."""
    with patch("syn_shared.settings.get_settings", return_value=_mock_settings(url)):
        env = _build_workspace_telemetry_env()

    assert env[ENV_OTEL_EXPORTER_OTLP_ENDPOINT] == url
    assert env[ENV_CLAUDE_CODE_ENABLE_TELEMETRY] == "1"
