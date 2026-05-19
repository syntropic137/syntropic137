"""Tests for ClaudePluginRegistrationAggregate (issue #726)."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_claude_plugin_registration.ClaudePluginRegistrationAggregate import (
    ClaudePluginRegistrationAggregate,
    compute_claude_plugin_stream_id,
)
from syn_domain.contexts.orchestration.domain.commands.RegisterClaudePluginCommand import (
    RegisterClaudePluginCommand,
)


def _command(
    source_url: str = "https://github.com/syntropic137/software-leverage-points",
    version: str = "5.0.7",
    name: str = "software-leverage-points",
) -> RegisterClaudePluginCommand:
    return RegisterClaudePluginCommand(
        aggregate_id=compute_claude_plugin_stream_id(source_url, version, name),
        source_url=source_url,
        version=version,
        resolved_sha="a" * 64,
        name=name,
        tree_storage_prefix="claude-plugins/sha256-aaaa/",
        manifest={"name": name, "version": version},
    )


@pytest.mark.unit
class TestStreamId:
    def test_deterministic(self) -> None:
        a = compute_claude_plugin_stream_id("https://example/x", "1.0.0", "p")
        b = compute_claude_plugin_stream_id("https://example/x", "1.0.0", "p")
        assert a == b
        assert a.startswith("claude-plugin-")

    def test_static_helper_matches_module_function(self) -> None:
        assert ClaudePluginRegistrationAggregate.compute_stream_id(
            "https://example/x", "1.0.0", "p"
        ) == compute_claude_plugin_stream_id("https://example/x", "1.0.0", "p")

    def test_different_inputs_differ(self) -> None:
        assert compute_claude_plugin_stream_id("u", "1", "p") != compute_claude_plugin_stream_id(
            "u", "2", "p"
        )
        assert compute_claude_plugin_stream_id("u1", "1", "p") != compute_claude_plugin_stream_id(
            "u2", "1", "p"
        )

    def test_marketplace_plugins_differ_by_name(self) -> None:
        # Regression for the collision bug fixed in #726: marketplace repos
        # ship multiple plugins at the same (source_url, version); each must
        # land in its own stream.
        a = compute_claude_plugin_stream_id("u", "1", "sdlc")
        b = compute_claude_plugin_stream_id("u", "1", "workspace")
        assert a != b


@pytest.mark.unit
class TestClaudePluginRegistrationAggregate:
    def test_register_initializes_state(self) -> None:
        agg = ClaudePluginRegistrationAggregate()
        cmd = _command()
        agg.register(cmd)

        assert agg.id is not None
        assert agg.source_url == cmd.source_url
        assert agg.plugin_version == cmd.version
        assert agg.resolved_sha == cmd.resolved_sha
        assert agg.name == cmd.name
        assert agg.tree_storage_prefix == cmd.tree_storage_prefix
        assert agg.manifest == dict(cmd.manifest)
        assert agg.registered_at is not None

    def test_register_twice_raises(self) -> None:
        agg = ClaudePluginRegistrationAggregate()
        agg.register(_command())
        with pytest.raises(ValueError, match="already registered"):
            agg.register(_command())

    def test_emits_one_event(self) -> None:
        agg = ClaudePluginRegistrationAggregate()
        agg.register(_command())
        events = agg.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "ClaudePluginRegistered"

    def test_aggregate_type(self) -> None:
        agg = ClaudePluginRegistrationAggregate()
        agg.register(_command())
        assert agg.get_aggregate_type() == "ClaudePluginRegistration"

    def test_replay_reconstructs_state(self) -> None:
        # Build event stream from a populated aggregate, then replay onto a fresh one
        original = ClaudePluginRegistrationAggregate()
        cmd = _command()
        original.register(cmd)
        envelopes = original.get_uncommitted_events()

        replayed = ClaudePluginRegistrationAggregate()
        replayed.rehydrate(list(envelopes))

        assert replayed.source_url == cmd.source_url
        assert replayed.plugin_version == cmd.version
        assert replayed.resolved_sha == cmd.resolved_sha
        assert replayed.name == cmd.name
        assert replayed.tree_storage_prefix == cmd.tree_storage_prefix
        assert replayed.manifest == dict(cmd.manifest)
