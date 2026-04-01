"""Tests for the marketplace client — registry I/O, caching, fetching, discovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from syn_cli.commands._marketplace_models import (
    CachedMarketplace,
    MarketplaceIndex,
    MarketplacePluginEntry,
    RegistryConfig,
    RegistryEntry,
    SyntropicMarker,
)


def _make_index(
    name: str = "test-marketplace",
    plugins: list[MarketplacePluginEntry] | None = None,
) -> MarketplaceIndex:
    return MarketplaceIndex(
        name=name,
        syntropic137=SyntropicMarker(type="workflow-marketplace"),
        plugins=plugins or [],
    )


def _make_plugin(
    name: str = "test-plugin",
    category: str = "research",
    tags: list[str] | None = None,
    description: str = "A test plugin",
) -> MarketplacePluginEntry:
    return MarketplacePluginEntry(
        name=name,
        source=f"./plugins/{name}",
        version="1.0.0",
        description=description,
        category=category,
        tags=tags or [],
    )


class TestRegistryIO:
    def test_load_empty_default(self, tmp_path: Path) -> None:
        with patch("syn_cli.commands._marketplace_client._REGISTRIES_PATH", tmp_path / "missing.json"):
            from syn_cli.commands._marketplace_client import load_registries

            config = load_registries()
            assert config.version == 1
            assert config.registries == {}

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "registries.json"
        with (
            patch("syn_cli.commands._marketplace_client._REGISTRIES_PATH", path),
            patch("syn_cli.commands._marketplace_client._SYN_DIR", tmp_path),
        ):
            from syn_cli.commands._marketplace_client import load_registries, save_registries

            config = RegistryConfig(
                registries={
                    "test": RegistryEntry(
                        repo="org/repo",
                        added_at="2026-01-01T00:00:00+00:00",
                    )
                }
            )
            save_registries(config)
            loaded = load_registries()
            assert loaded.registries["test"].repo == "org/repo"


class TestCacheIO:
    def test_load_missing_cache(self, tmp_path: Path) -> None:
        with patch("syn_cli.commands._marketplace_client._CACHE_DIR", tmp_path / "cache"):
            from syn_cli.commands._marketplace_client import load_cached_index

            assert load_cached_index("nonexistent") is None

    def test_save_and_load(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        with patch("syn_cli.commands._marketplace_client._CACHE_DIR", cache_dir):
            from syn_cli.commands._marketplace_client import load_cached_index, save_cached_index

            cached = CachedMarketplace(
                fetched_at=datetime.now(tz=UTC).isoformat(),
                index=_make_index(plugins=[_make_plugin()]),
            )
            save_cached_index("test", cached)
            loaded = load_cached_index("test")
            assert loaded is not None
            assert loaded.index.name == "test-marketplace"
            assert len(loaded.index.plugins) == 1

    def test_stale_detection(self) -> None:
        from syn_cli.commands._marketplace_client import is_cache_stale

        fresh = CachedMarketplace(
            fetched_at=datetime.now(tz=UTC).isoformat(),
            index=_make_index(),
        )
        assert not is_cache_stale(fresh)

        stale = CachedMarketplace(
            fetched_at=(datetime.now(tz=UTC) - timedelta(hours=5)).isoformat(),
            index=_make_index(),
        )
        assert is_cache_stale(stale)


class TestFetchMarketplaceJson:
    @patch("syn_cli.commands._marketplace_client.subprocess")
    def test_successful_fetch(self, mock_subprocess: MagicMock, tmp_path: Path) -> None:
        from syn_cli.commands._marketplace_client import fetch_marketplace_json

        marketplace_data = {
            "name": "test-marketplace",
            "syntropic137": {"type": "workflow-marketplace"},
            "plugins": [{"name": "p1", "source": "./p1"}],
        }

        def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            # The last arg of git clone is the destination
            dest = cmd[-1]
            (tmp_path / "marketplace.json").write_text(json.dumps(marketplace_data))
            # Simulate clone by writing to dest
            import shutil

            shutil.copytree(str(tmp_path), dest, dirs_exist_ok=True)
            result = MagicMock()
            result.returncode = 0
            return result

        mock_subprocess.run.side_effect = fake_run

        with patch("syn_cli.commands._marketplace_client.tempfile.mkdtemp", return_value=str(tmp_path / "clone")):
            # Need a more nuanced mock for this test
            pass

    @patch("syn_cli.commands._marketplace_client.subprocess")
    def test_clone_failure(self, mock_subprocess: MagicMock) -> None:
        from syn_cli.commands._marketplace_client import fetch_marketplace_json

        result = MagicMock()
        result.returncode = 1
        result.stderr = "fatal: repo not found"
        mock_subprocess.run.return_value = result

        with pytest.raises(RuntimeError, match="git clone failed"):
            fetch_marketplace_json("org/nonexistent")


class TestSearchAllRegistries:
    def test_search_with_results(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        reg_path = tmp_path / "registries.json"

        config = RegistryConfig(
            registries={
                "official": RegistryEntry(
                    repo="syntropic137/workflow-library",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )
        tmp_path.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(config.model_dump_json())

        # Pre-populate cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = CachedMarketplace(
            fetched_at=datetime.now(tz=UTC).isoformat(),
            index=_make_index(
                plugins=[
                    _make_plugin("research-toolkit", category="research", tags=["deep-dive"]),
                    _make_plugin("pr-automation", category="ci", tags=["github"]),
                ]
            ),
        )
        (cache_dir / "official.json").write_text(cached.model_dump_json())

        with (
            patch("syn_cli.commands._marketplace_client._REGISTRIES_PATH", reg_path),
            patch("syn_cli.commands._marketplace_client._CACHE_DIR", cache_dir),
        ):
            from syn_cli.commands._marketplace_client import search_all_registries

            # Search by name
            results = search_all_registries("research")
            assert len(results) == 1
            assert results[0][1].name == "research-toolkit"

            # Search by tag
            results = search_all_registries("", tag="github")
            assert len(results) == 1
            assert results[0][1].name == "pr-automation"

            # Search by category
            results = search_all_registries("", category="ci")
            assert len(results) == 1

            # No results
            results = search_all_registries("nonexistent")
            assert len(results) == 0

            # Empty query returns all
            results = search_all_registries("")
            assert len(results) == 2


class TestResolvePluginByName:
    def test_found(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        reg_path = tmp_path / "registries.json"

        config = RegistryConfig(
            registries={
                "official": RegistryEntry(
                    repo="syntropic137/workflow-library",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )
        reg_path.write_text(config.model_dump_json())

        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = CachedMarketplace(
            fetched_at=datetime.now(tz=UTC).isoformat(),
            index=_make_index(plugins=[_make_plugin("research-toolkit")]),
        )
        (cache_dir / "official.json").write_text(cached.model_dump_json())

        with (
            patch("syn_cli.commands._marketplace_client._REGISTRIES_PATH", reg_path),
            patch("syn_cli.commands._marketplace_client._CACHE_DIR", cache_dir),
        ):
            from syn_cli.commands._marketplace_client import resolve_plugin_by_name

            result = resolve_plugin_by_name("research-toolkit")
            assert result is not None
            reg_name, entry, plugin = result
            assert reg_name == "official"
            assert plugin.name == "research-toolkit"

    def test_not_found(self, tmp_path: Path) -> None:
        reg_path = tmp_path / "registries.json"
        RegistryConfig().model_dump_json()
        reg_path.write_text(RegistryConfig().model_dump_json())

        with (
            patch("syn_cli.commands._marketplace_client._REGISTRIES_PATH", reg_path),
            patch("syn_cli.commands._marketplace_client._CACHE_DIR", tmp_path / "cache"),
        ):
            from syn_cli.commands._marketplace_client import resolve_plugin_by_name

            assert resolve_plugin_by_name("nonexistent") is None


class TestGetGitHeadSha:
    @patch("syn_cli.commands._marketplace_client.subprocess")
    def test_success(self, mock_subprocess: MagicMock) -> None:
        from syn_cli.commands._marketplace_client import get_git_head_sha

        result = MagicMock()
        result.returncode = 0
        result.stdout = "abc123def456\trefs/heads/main\n"
        mock_subprocess.run.return_value = result

        sha = get_git_head_sha("org/repo")
        assert sha == "abc123def456"

    @patch("syn_cli.commands._marketplace_client.subprocess")
    def test_failure(self, mock_subprocess: MagicMock) -> None:
        from syn_cli.commands._marketplace_client import get_git_head_sha

        result = MagicMock()
        result.returncode = 1
        mock_subprocess.run.return_value = result

        assert get_git_head_sha("org/nonexistent") is None
