"""Tests for workflow search and info CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from syn_cli.commands._marketplace_models import (
    MarketplacePluginEntry,
    RegistryEntry,
)
from syn_cli.main import app

runner = CliRunner()


def _make_plugin(
    name: str = "research-toolkit",
    category: str = "research",
    tags: list[str] | None = None,
    description: str = "Multi-phase research workflows",
) -> MarketplacePluginEntry:
    return MarketplacePluginEntry(
        name=name,
        source=f"./plugins/{name}",
        version="1.0.0",
        description=description,
        category=category,
        tags=tags or ["research"],
    )


class TestSearchWorkflows:
    @patch("syn_cli.commands.workflow._search.search_all_registries")
    def test_search_with_results(self, mock_search: MagicMock) -> None:
        mock_search.return_value = [
            ("official", _make_plugin()),
            ("official", _make_plugin("pr-automation", category="ci")),
        ]

        result = runner.invoke(app, ["workflow", "search", "test"])
        assert result.exit_code == 0
        assert "research-toolkit" in result.stdout
        assert "pr-automation" in result.stdout
        assert "2 results" in result.stdout

    @patch("syn_cli.commands.workflow._search.search_all_registries")
    def test_search_no_results(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []

        result = runner.invoke(app, ["workflow", "search", "nonexistent"])
        assert result.exit_code == 0
        assert "No workflows found" in result.stdout

    @patch("syn_cli.commands.workflow._search.search_all_registries")
    def test_search_empty_query_no_registries(self, mock_search: MagicMock) -> None:
        mock_search.return_value = []

        result = runner.invoke(app, ["workflow", "search"])
        assert result.exit_code == 0
        assert "No workflows found" in result.stdout
        assert "syn marketplace add" in result.stdout

    @patch("syn_cli.commands.workflow._search.search_all_registries")
    def test_search_filter_by_registry(self, mock_search: MagicMock) -> None:
        mock_search.return_value = [
            ("official", _make_plugin()),
            ("company", _make_plugin("internal-tool")),
        ]

        result = runner.invoke(app, ["workflow", "search", "", "--registry", "official"])
        assert result.exit_code == 0
        assert "research-toolkit" in result.stdout
        # internal-tool should be filtered out
        assert "internal-tool" not in result.stdout


class TestWorkflowInfo:
    @patch("syn_cli.commands.workflow._search.resolve_plugin_by_name")
    def test_info_found(self, mock_resolve: MagicMock) -> None:
        mock_resolve.return_value = (
            "official",
            RegistryEntry(
                repo="syntropic137/workflow-library",
                added_at="2026-01-01T00:00:00+00:00",
            ),
            _make_plugin(tags=["research", "analysis"]),
        )

        result = runner.invoke(app, ["workflow", "info", "research-toolkit"])
        assert result.exit_code == 0
        assert "research-toolkit" in result.stdout
        assert "1.0.0" in result.stdout
        assert "research, analysis" in result.stdout
        assert "syn workflow install" in result.stdout

    @patch("syn_cli.commands.workflow._search.resolve_plugin_by_name")
    def test_info_not_found(self, mock_resolve: MagicMock) -> None:
        mock_resolve.return_value = None

        result = runner.invoke(app, ["workflow", "info", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.stdout
