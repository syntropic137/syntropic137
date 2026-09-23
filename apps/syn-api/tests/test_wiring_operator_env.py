"""Operator attribution reaches the workspace container's environment.

The hook that writes the Co-authored-by trailer has shipped in the workspace
image for some time and has never fired, because nothing on this side set the
two variables it reads. These tests pin the connection, and in particular pin
that attribution does not depend on telemetry being configured - the two were
composed into one environment and could otherwise take each other down.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from syn_api._wiring import (
    _build_workspace_env,
    _build_workspace_operator_env,
)
from syn_shared.env_constants import (
    ENV_CLAUDE_CODE_ENABLE_TELEMETRY,
    ENV_OTEL_EXPORTER_OTLP_ENDPOINT,
)

# CI runs `pytest -m unit`; an unmarked module collects zero tests and the
# gate goes green having run nothing.
pytestmark = pytest.mark.unit

NAME = "Neural Empowerment"
EMAIL = "129192050+NeuralEmpowerment@users.noreply.github.com"


def _telemetry(collector_url: str | None) -> MagicMock:
    settings = MagicMock()
    settings.collector_url = collector_url
    return settings


def _with_operator(**env: str):
    """Patch the operator settings the wiring reads."""
    return patch.dict("os.environ", env, clear=False)


def test_operator_env_carries_both_variables() -> None:
    with _with_operator(SYN_OPERATOR_NAME=NAME, SYN_OPERATOR_EMAIL=EMAIL):
        env = _build_workspace_operator_env()

    assert env == {"SYN_OPERATOR_NAME": NAME, "SYN_OPERATOR_EMAIL": EMAIL}


def test_attribution_survives_telemetry_being_unconfigured() -> None:
    """The load-bearing case.

    Telemetry returns {} whenever no collector is set. If the two builders were
    folded together, or merged in the wrong order, a deployment with no
    collector would silently lose attribution as well - two unrelated features
    failing as one.
    """
    with (
        patch("syn_shared.settings.get_settings", return_value=_telemetry(None)),
        _with_operator(SYN_OPERATOR_NAME=NAME, SYN_OPERATOR_EMAIL=EMAIL),
    ):
        env = _build_workspace_env()

    assert env["SYN_OPERATOR_NAME"] == NAME
    assert env["SYN_OPERATOR_EMAIL"] == EMAIL


def test_telemetry_survives_attribution_being_unconfigured() -> None:
    """The same argument in the other direction."""
    with (
        patch("syn_shared.settings.get_settings", return_value=_telemetry("http://collector:8080")),
        patch(
            "syn_api._wiring._build_workspace_operator_env",
            return_value={},
        ),
    ):
        env = _build_workspace_env()

    assert env[ENV_CLAUDE_CODE_ENABLE_TELEMETRY] == "1"
    assert env[ENV_OTEL_EXPORTER_OTLP_ENDPOINT] == "http://collector:8080"


def test_both_are_present_together() -> None:
    with (
        patch("syn_shared.settings.get_settings", return_value=_telemetry("http://collector:8080")),
        _with_operator(SYN_OPERATOR_NAME=NAME, SYN_OPERATOR_EMAIL=EMAIL),
    ):
        env = _build_workspace_env()

    assert set(env) >= {
        ENV_CLAUDE_CODE_ENABLE_TELEMETRY,
        ENV_OTEL_EXPORTER_OTLP_ENDPOINT,
        "SYN_OPERATOR_NAME",
        "SYN_OPERATOR_EMAIL",
    }


def test_neither_configured_is_an_empty_environment() -> None:
    """No attribution and no collector must not invent variables."""
    with (
        patch("syn_shared.settings.get_settings", return_value=_telemetry(None)),
        patch("syn_api._wiring._build_workspace_operator_env", return_value={}),
    ):
        assert _build_workspace_env() == {}
