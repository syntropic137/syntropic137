"""Tests for control CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()

_HELPERS_CLIENT = "syn_cli.commands._api_helpers.get_client"


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _mock_client(*responses: MagicMock) -> MagicMock:
    client = MagicMock()
    all_responses = list(responses)
    call_idx = {"i": 0}

    def _next_response(*_args: object, **_kwargs: object) -> MagicMock:
        idx = call_idx["i"]
        call_idx["i"] += 1
        return all_responses[idx] if idx < len(all_responses) else _mock_response()

    client.get.side_effect = _next_response
    client.post.side_effect = _next_response
    client.__enter__ = lambda _self: client
    client.__exit__ = MagicMock(return_value=False)
    return client


@pytest.mark.unit
class TestControlHelp:
    def test_control_help(self) -> None:
        result = runner.invoke(app, ["control", "--help"])
        assert result.exit_code == 0
        for cmd in ("pause", "resume", "cancel", "status"):
            assert cmd in result.stdout


@pytest.mark.unit
class TestControlPause:
    def test_pause_success(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "paused"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "pause", "exec-001"])
        assert result.exit_code == 0
        assert "Pause signal sent" in result.stdout

    def test_pause_with_reason(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "paused", "message": "OK"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(
                app, ["control", "pause", "exec-001", "--reason", "investigating"]
            )
        assert result.exit_code == 0
        call_kwargs = client.post.call_args
        assert call_kwargs.kwargs.get("json") == {"reason": "investigating"}

    def test_pause_failure(self) -> None:
        client = _mock_client(_mock_response(404, {"detail": "Not found"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "pause", "exec-bad"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout

    def test_pause_connection_error(self) -> None:
        with patch(_HELPERS_CLIENT, side_effect=ConnectionError("refused")):
            result = runner.invoke(app, ["control", "pause", "exec-001"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout


@pytest.mark.unit
class TestControlResume:
    def test_resume_success(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "running"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "resume", "exec-001"])
        assert result.exit_code == 0
        assert "Resume signal sent" in result.stdout


@pytest.mark.unit
class TestControlCancel:
    def test_cancel_with_force(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "cancelled"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "cancel", "exec-001", "--force"])
        assert result.exit_code == 0
        assert "Cancel signal sent" in result.stdout

    def test_cancel_confirmed(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "cancelled"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "cancel", "exec-001"], input="y\n")
        assert result.exit_code == 0

    def test_cancel_aborted(self) -> None:
        result = runner.invoke(app, ["control", "cancel", "exec-001"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.stdout


@pytest.mark.unit
class TestControlStatus:
    def test_status_running(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "running"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "status", "exec-001"])
        assert result.exit_code == 0
        assert "running" in result.stdout

    def test_status_completed(self) -> None:
        client = _mock_client(_mock_response(200, {"state": "completed"}))
        with patch(_HELPERS_CLIENT, return_value=client):
            result = runner.invoke(app, ["control", "status", "exec-001"])
        assert result.exit_code == 0
        assert "completed" in result.stdout
