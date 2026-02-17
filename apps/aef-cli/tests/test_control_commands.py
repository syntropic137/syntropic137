"""Tests for control CLI commands (HTTP delegation)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from aef_cli.main import app

runner = CliRunner()


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


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
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"state": "paused"})
            result = runner.invoke(app, ["control", "pause", "exec-001"])
        assert result.exit_code == 0
        assert "Pause signal sent" in result.stdout

    def test_pause_with_reason(self) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"state": "paused", "message": "OK"})
            result = runner.invoke(
                app, ["control", "pause", "exec-001", "--reason", "investigating"]
            )
        assert result.exit_code == 0
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("json") == {"reason": "investigating"}

    def test_pause_failure(self) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(404, {"detail": "Not found"})
            result = runner.invoke(app, ["control", "pause", "exec-bad"])
        assert result.exit_code == 1
        assert "Failed to pause" in result.stdout

    def test_pause_connection_error(self) -> None:
        import httpx

        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            result = runner.invoke(app, ["control", "pause", "exec-001"])
        assert result.exit_code == 1
        assert "Could not connect" in result.stdout


@pytest.mark.unit
class TestControlResume:
    def test_resume_success(self) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"state": "running"})
            result = runner.invoke(app, ["control", "resume", "exec-001"])
        assert result.exit_code == 0
        assert "Resume signal sent" in result.stdout


@pytest.mark.unit
class TestControlCancel:
    def test_cancel_with_force(self) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"state": "cancelled"})
            result = runner.invoke(app, ["control", "cancel", "exec-001", "--force"])
        assert result.exit_code == 0
        assert "Cancel signal sent" in result.stdout

    def test_cancel_confirmed(self) -> None:
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_response(200, {"state": "cancelled"})
            result = runner.invoke(app, ["control", "cancel", "exec-001"], input="y\n")
        assert result.exit_code == 0

    def test_cancel_aborted(self) -> None:
        result = runner.invoke(app, ["control", "cancel", "exec-001"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.stdout


@pytest.mark.unit
class TestControlStatus:
    def test_status_running(self) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"state": "running"})
            result = runner.invoke(app, ["control", "status", "exec-001"])
        assert result.exit_code == 0
        assert "running" in result.stdout

    def test_status_completed(self) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"state": "completed"})
            result = runner.invoke(app, ["control", "status", "exec-001"])
        assert result.exit_code == 0
        assert "completed" in result.stdout

    def test_status_custom_url(self) -> None:
        with patch("httpx.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"state": "running"})
            result = runner.invoke(
                app, ["control", "status", "exec-001", "--url", "http://custom:9000"]
            )
        assert result.exit_code == 0
        mock_get.assert_called_once()
        assert "custom:9000" in mock_get.call_args[0][0]
