"""Tests for marketplace Pydantic models."""

from __future__ import annotations

import pytest

from syn_cli.commands._marketplace_models import (
    CachedMarketplace,
    MarketplaceIndex,
    MarketplacePluginEntry,
    RegistryConfig,
    RegistryEntry,
    SyntropicMarker,
)
from syn_cli.commands._package_models import InstallationRecord


class TestSyntropicMarker:
    def test_valid_marker(self) -> None:
        marker = SyntropicMarker(type="workflow-marketplace", min_platform_version="0.7.0")
        assert marker.type == "workflow-marketplace"
        assert marker.min_platform_version == "0.7.0"

    def test_defaults(self) -> None:
        marker = SyntropicMarker(type="workflow-marketplace")
        assert marker.min_platform_version == "0.0.0"

    def test_extra_fields_ignored(self) -> None:
        marker = SyntropicMarker(type="workflow-marketplace", future_field="hello")
        assert marker.type == "workflow-marketplace"


class TestMarketplacePluginEntry:
    def test_full_entry(self) -> None:
        entry = MarketplacePluginEntry(
            name="research-toolkit",
            source="./plugins/research-toolkit",
            version="1.0.0",
            description="Multi-phase research",
            category="research",
            tags=["research", "analysis"],
        )
        assert entry.name == "research-toolkit"
        assert entry.tags == ["research", "analysis"]

    def test_minimal_entry(self) -> None:
        entry = MarketplacePluginEntry(
            name="my-plugin",
            source="./plugins/my-plugin",
        )
        assert entry.version == "0.1.0"
        assert entry.description == ""
        assert entry.tags == []

    def test_extra_fields_ignored(self) -> None:
        entry = MarketplacePluginEntry(
            name="test",
            source="./test",
            downloads=9999,
        )
        assert entry.name == "test"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            MarketplacePluginEntry(name="", source="./test")


class TestMarketplaceIndex:
    def test_full_index(self) -> None:
        index = MarketplaceIndex(
            name="my-marketplace",
            syntropic137=SyntropicMarker(type="workflow-marketplace"),
            plugins=[
                MarketplacePluginEntry(name="p1", source="./p1"),
                MarketplacePluginEntry(name="p2", source="./p2"),
            ],
        )
        assert index.name == "my-marketplace"
        assert len(index.plugins) == 2

    def test_from_dict(self) -> None:
        data = {
            "name": "test-marketplace",
            "syntropic137": {
                "type": "workflow-marketplace",
                "min_platform_version": "0.7.0",
            },
            "plugins": [
                {
                    "name": "research-toolkit",
                    "source": "./plugins/research-toolkit",
                    "version": "1.0.0",
                    "description": "Research workflows",
                    "category": "research",
                    "tags": ["research"],
                }
            ],
        }
        index = MarketplaceIndex.model_validate(data)
        assert index.name == "test-marketplace"
        assert index.syntropic137.min_platform_version == "0.7.0"
        assert len(index.plugins) == 1
        assert index.plugins[0].name == "research-toolkit"

    def test_empty_plugins(self) -> None:
        index = MarketplaceIndex(
            name="empty",
            syntropic137=SyntropicMarker(type="workflow-marketplace"),
        )
        assert index.plugins == []


class TestRegistryConfig:
    def test_empty_config(self) -> None:
        config = RegistryConfig()
        assert config.version == 1
        assert config.registries == {}

    def test_with_entries(self) -> None:
        config = RegistryConfig(
            registries={
                "official": RegistryEntry(
                    repo="syntropic137/workflow-library",
                    ref="main",
                    added_at="2026-03-31T00:00:00+00:00",
                )
            }
        )
        assert "official" in config.registries
        assert config.registries["official"].repo == "syntropic137/workflow-library"

    def test_round_trip_json(self) -> None:
        config = RegistryConfig(
            registries={
                "test": RegistryEntry(
                    repo="org/repo",
                    added_at="2026-01-01T00:00:00+00:00",
                )
            }
        )
        json_str = config.model_dump_json()
        restored = RegistryConfig.model_validate_json(json_str)
        assert restored == config


class TestCachedMarketplace:
    def test_round_trip(self) -> None:
        cached = CachedMarketplace(
            fetched_at="2026-03-31T12:00:00+00:00",
            index=MarketplaceIndex(
                name="test",
                syntropic137=SyntropicMarker(type="workflow-marketplace"),
                plugins=[MarketplacePluginEntry(name="p1", source="./p1")],
            ),
        )
        json_str = cached.model_dump_json()
        restored = CachedMarketplace.model_validate_json(json_str)
        assert restored.index.name == "test"
        assert len(restored.index.plugins) == 1


class TestInstallationRecordExtension:
    """Test backward compat of the extended InstallationRecord."""

    def test_new_fields_default_to_none(self) -> None:
        record = InstallationRecord(
            package_name="test",
            package_version="1.0.0",
            source="./test",
            source_ref="main",
            installed_at="2026-01-01T00:00:00+00:00",
            format="single",
        )
        assert record.marketplace_source is None
        assert record.git_sha is None

    def test_new_fields_populated(self) -> None:
        record = InstallationRecord(
            package_name="test",
            package_version="1.0.0",
            source="research-toolkit",
            source_ref="main",
            installed_at="2026-01-01T00:00:00+00:00",
            format="multi",
            marketplace_source="syntropic137-official",
            git_sha="abc123def456",
        )
        assert record.marketplace_source == "syntropic137-official"
        assert record.git_sha == "abc123def456"

    def test_backward_compat_json_without_new_fields(self) -> None:
        """Old installed.json without marketplace fields should still parse."""
        old_json = (
            '{"package_name":"test","package_version":"1.0.0",'
            '"source":"./test","source_ref":"main",'
            '"installed_at":"2026-01-01T00:00:00+00:00",'
            '"format":"single","workflows":[]}'
        )
        record = InstallationRecord.model_validate_json(old_json)
        assert record.package_name == "test"
        assert record.marketplace_source is None
        assert record.git_sha is None
