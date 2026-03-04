"""Tests for agent CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from syn_cli.main import app

runner = CliRunner()


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
class TestAgentHelp:
    def test_agent_help(self) -> None:
        result = runner.invoke(app, ["agent", "--help"])
        assert result.exit_code == 0
        for cmd in ("list", "test", "chat"):
            assert cmd in result.stdout


@pytest.mark.unit
class TestAgentList:
    def test_list_providers(self) -> None:
        providers = [
            {
                "provider": "claude",
                "display_name": "Anthropic Claude",
                "available": True,
                "default_model": "claude-sonnet-4-5-20250929",
            },
            {
                "provider": "openai",
                "display_name": "OpenAI GPT",
                "available": False,
                "default_model": "gpt-4o",
            },
        ]
        client = _mock_client(_mock_response(200, providers))
        with patch("syn_cli.commands.agent.get_client", return_value=client):
            result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "Claude" in result.stdout
        assert "OpenAI" in result.stdout


@pytest.mark.unit
class TestAgentTest:
    def test_test_success(self) -> None:
        test_result = {
            "provider": "mock",
            "model": "mock-v1",
            "response_text": "Hello, world!",
            "input_tokens": 10,
            "output_tokens": 5,
        }
        client = _mock_client(_mock_response(200, test_result))
        with patch("syn_cli.commands.agent.get_client", return_value=client):
            result = runner.invoke(app, ["agent", "test", "--provider", "mock"])
        assert result.exit_code == 0
        assert "Hello, world!" in result.stdout
        assert "mock" in result.stdout

    def test_test_failure(self) -> None:
        client = _mock_client(_mock_response(400, {"detail": "Unknown provider: bad"}))
        with patch("syn_cli.commands.agent.get_client", return_value=client):
            result = runner.invoke(app, ["agent", "test", "--provider", "bad"])
        assert result.exit_code == 1
        assert "Unknown provider" in result.stdout

    def test_test_help(self) -> None:
        result = runner.invoke(app, ["agent", "test", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.stdout
        assert "--prompt" in result.stdout
        assert "--model" in result.stdout
