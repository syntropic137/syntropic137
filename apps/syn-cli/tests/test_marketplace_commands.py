"""Tests for marketplace CLI commands — add, list, remove, refresh."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from typer.testing import CliRunner

from syn_cli.commands._marketplace_models import (
    MarketplaceIndex,
    MarketplacePluginEntry,
    RegistryConfig,
    RegistryEntry,
    SyntropicMarker,
)
from syn_cli.main import app

runner = CliRunner()


def _make_index(
    name: str = "test-marketplace",
    plugins: list[MarketplacePluginEntry] | None = None,
) -> MarketplaceIndex:
    return MarketplaceIndex(
        name=name,
        syntropic137=SyntropicMarker(type="workflow-marketplace"),
        plugins=plugins or [MarketplacePluginEntry(name="p1", source="./p1")],
    )


class TestMarketplaceAdd:
    @patch("syn_cli.commands.marketplace._registry.fetch_marketplace_json")
    @patch("syn_cli.commands.marketplace._registry.save_registries")
    @patch("syn_cli.commands.marketplace._registry.load_registries")
    @patch("syn_cli.commands.marketplace._registry.save_cached_index")
    def test_add_success(
        self,
        mock_save_cache: MagicMock,
        mock_load: MagicMock,
        mock_save: MagicMock,
        mock_fetch: MagicMock,
    ) -> None:
        mock_load.return_value = RegistryConfig()
        mock_fetch.return_value = _make_index()

        result = runner.invoke(app, ["marketplace", "add", "org/repo"])
        assert result.exit_code == 0
        assert "Added marketplace" in result.stdout
        mock_save.assert_called_once()

    @patch("syn_cli.commands.marketplace._registry.fetch_marketplace_json")
    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_add_duplicate(
        self,
        mock_load: MagicMock,
        mock_fetch: MagicMock,
    ) -> None:
        mock_fetch.return_value = _make_index()
        mock_load.return_value = RegistryConfig(
            registries={
                "test-marketplace": RegistryEntry(
                    repo="org/repo",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )

        result = runner.invoke(app, ["marketplace", "add", "org/repo"])
        assert result.exit_code == 1
        assert "already registered" in result.stdout

    @patch("syn_cli.commands.marketplace._registry.fetch_marketplace_json")
    def test_add_invalid_repo(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = RuntimeError("git clone failed")

        result = runner.invoke(app, ["marketplace", "add", "org/nonexistent"])
        assert result.exit_code == 1
        assert "git clone failed" in result.stdout


class TestMarketplaceList:
    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_list_empty(self, mock_load: MagicMock) -> None:
        mock_load.return_value = RegistryConfig()

        result = runner.invoke(app, ["marketplace", "list"])
        assert result.exit_code == 0
        assert "No marketplaces registered" in result.stdout

    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_list_with_entries(self, mock_load: MagicMock) -> None:
        mock_load.return_value = RegistryConfig(
            registries={
                "official": RegistryEntry(
                    repo="syntropic137/workflow-library",
                    added_at="2026-03-31T00:00:00+00:00",
                ),
                "company": RegistryEntry(
                    repo="myorg/internal",
                    ref="develop",
                    added_at="2026-03-31T00:00:00+00:00",
                ),
            }
        )

        result = runner.invoke(app, ["marketplace", "list"])
        assert result.exit_code == 0
        assert "official" in result.stdout
        assert "syntropic137/workflow-library" in result.stdout
        assert "company" in result.stdout


class TestMarketplaceRemove:
    @patch("syn_cli.commands.marketplace._registry.save_registries")
    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_remove_success(
        self,
        mock_load: MagicMock,
        mock_save: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_load.return_value = RegistryConfig(
            registries={
                "official": RegistryEntry(
                    repo="org/repo",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )

        with patch("syn_cli.commands._marketplace_client._CACHE_DIR", tmp_path):
            result = runner.invoke(app, ["marketplace", "remove", "official"])

        assert result.exit_code == 0
        assert "Removed marketplace" in result.stdout
        mock_save.assert_called_once()

    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_remove_nonexistent(self, mock_load: MagicMock) -> None:
        mock_load.return_value = RegistryConfig()

        result = runner.invoke(app, ["marketplace", "remove", "nonexistent"])
        assert result.exit_code == 1
        assert "not registered" in result.stdout


class TestMarketplaceRefresh:
    @patch("syn_cli.commands.marketplace._registry.refresh_index")
    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_refresh_all(
        self,
        mock_load: MagicMock,
        mock_refresh: MagicMock,
    ) -> None:
        mock_load.return_value = RegistryConfig(
            registries={
                "official": RegistryEntry(
                    repo="org/repo",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )
        mock_refresh.return_value = _make_index()

        result = runner.invoke(app, ["marketplace", "refresh"])
        assert result.exit_code == 0
        assert "Refreshing" in result.stdout
        assert "done" in result.stdout

    @patch("syn_cli.commands.marketplace._registry.load_registries")
    def test_refresh_nonexistent(self, mock_load: MagicMock) -> None:
        mock_load.return_value = RegistryConfig(
            registries={
                "other": RegistryEntry(
                    repo="org/repo",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )

        result = runner.invoke(app, ["marketplace", "refresh", "nonexistent"])
        assert result.exit_code == 1
        assert "not registered" in result.stdout
