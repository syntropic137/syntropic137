"""Tests for GlobalClaudePluginRegistryAggregate (issue #726)."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
    GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
    GlobalClaudePluginRegistryAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.AddGlobalClaudePluginCommand import (
    AddGlobalClaudePluginCommand,
)
from syn_domain.contexts.orchestration.domain.commands.RemoveGlobalClaudePluginCommand import (
    RemoveGlobalClaudePluginCommand,
)


def _add(name: str = "software-leverage-points") -> AddGlobalClaudePluginCommand:
    return AddGlobalClaudePluginCommand(
        aggregate_id=GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
        name=name,
        source_url=f"https://github.com/syntropic137/{name}",
        version="1.0.0",
        resolved_sha="a" * 64,
    )


def _remove(name: str = "software-leverage-points") -> RemoveGlobalClaudePluginCommand:
    return RemoveGlobalClaudePluginCommand(
        aggregate_id=GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
        name=name,
    )


@pytest.mark.unit
class TestGlobalClaudePluginRegistryAggregate:
    def test_singleton_constant_matches_class_attr(self) -> None:
        assert (
            GlobalClaudePluginRegistryAggregate.STREAM_ID
            == GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID
            == "global-claude-plugins"
        )

    def test_add_appends(self) -> None:
        agg = GlobalClaudePluginRegistryAggregate()
        agg.add(_add("alpha"))
        agg.add(_add("beta"))

        names = [entry.name for entry in agg.plugins]
        assert names == ["alpha", "beta"]

    def test_add_duplicate_raises(self) -> None:
        agg = GlobalClaudePluginRegistryAggregate()
        agg.add(_add("alpha"))
        with pytest.raises(ValueError, match="already added"):
            agg.add(_add("alpha"))

    def test_remove_missing_raises(self) -> None:
        agg = GlobalClaudePluginRegistryAggregate()
        agg.add(_add("alpha"))
        with pytest.raises(ValueError, match="not present"):
            agg.remove(_remove("beta"))

    def test_remove_missing_on_empty_raises(self) -> None:
        agg = GlobalClaudePluginRegistryAggregate()
        with pytest.raises(ValueError, match="not present"):
            agg.remove(_remove("alpha"))

    def test_remove_present_succeeds(self) -> None:
        agg = GlobalClaudePluginRegistryAggregate()
        agg.add(_add("alpha"))
        agg.add(_add("beta"))
        agg.remove(_remove("alpha"))

        assert [entry.name for entry in agg.plugins] == ["beta"]

    def test_replay_rebuilds_list(self) -> None:
        original = GlobalClaudePluginRegistryAggregate()
        original.add(_add("alpha"))
        original.add(_add("beta"))
        original.remove(_remove("alpha"))
        envelopes = original.get_uncommitted_events()

        replayed = GlobalClaudePluginRegistryAggregate()
        replayed.rehydrate(list(envelopes))

        assert [entry.name for entry in replayed.plugins] == ["beta"]
