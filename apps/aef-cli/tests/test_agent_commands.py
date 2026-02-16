"""Tests for agent CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from aef_api.types import AgentProviderInfo, AgentTestResult, Err, Ok
from aef_cli.main import app

runner = CliRunner()


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
            AgentProviderInfo(
                provider="claude",
                display_name="Anthropic Claude",
                available=True,
                default_model="claude-sonnet-4-5-20250929",
            ),
            AgentProviderInfo(
                provider="openai",
                display_name="OpenAI GPT",
                available=False,
                default_model="gpt-4o",
            ),
        ]
        with patch("aef_api.v1.agents.list_providers", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(providers)
            result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "Claude" in result.stdout
        assert "OpenAI" in result.stdout


@pytest.mark.unit
class TestAgentTest:
    def test_test_success(self) -> None:
        test_result = AgentTestResult(
            provider="mock",
            model="mock-v1",
            response_text="Hello, world!",
            input_tokens=10,
            output_tokens=5,
        )
        with patch("aef_api.v1.agents.test_agent", new_callable=AsyncMock) as mock:
            mock.return_value = Ok(test_result)
            result = runner.invoke(app, ["agent", "test", "--provider", "mock"])
        assert result.exit_code == 0
        assert "Hello, world!" in result.stdout
        assert "mock" in result.stdout

    def test_test_failure(self) -> None:
        with patch("aef_api.v1.agents.test_agent", new_callable=AsyncMock) as mock:
            mock.return_value = Err("provider_not_found", message="Unknown provider: bad")
            result = runner.invoke(app, ["agent", "test", "--provider", "bad"])
        assert result.exit_code == 1
        assert "Unknown provider" in result.stdout

    def test_test_help(self) -> None:
        result = runner.invoke(app, ["agent", "test", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.stdout
        assert "--prompt" in result.stdout
        assert "--model" in result.stdout
