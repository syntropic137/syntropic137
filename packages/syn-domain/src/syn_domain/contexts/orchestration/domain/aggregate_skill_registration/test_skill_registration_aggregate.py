"""Tests for SkillRegistrationAggregate (issue #772)."""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_skill_registration.SkillRegistrationAggregate import (
    SkillRegistrationAggregate,
    compute_skill_stream_id,
)
from syn_domain.contexts.orchestration.domain.commands.RegisterSkillCommand import (
    RegisterSkillCommand,
)


def _command(
    source_url: str = "https://github.com/acme/agent-skills",
    version: str = "v2.0.0",
    skill_name: str = "code-review",
) -> RegisterSkillCommand:
    return RegisterSkillCommand(
        aggregate_id=compute_skill_stream_id(source_url, version, skill_name),
        source_url=source_url,
        version=version,
        resolved_sha="a" * 64,
        skill_name=skill_name,
        tree_storage_prefix="skills/sha256-aaaa/",
        manifest={"name": skill_name, "description": "Review diffs"},
    )


@pytest.mark.unit
class TestStreamId:
    def test_deterministic(self) -> None:
        a = compute_skill_stream_id("https://example/x", "1.0.0", "p")
        b = compute_skill_stream_id("https://example/x", "1.0.0", "p")
        assert a == b
        assert a.startswith("skill-")

    def test_static_helper_matches_module_function(self) -> None:
        assert SkillRegistrationAggregate.compute_stream_id(
            "https://example/x", "1.0.0", "p"
        ) == compute_skill_stream_id("https://example/x", "1.0.0", "p")

    def test_different_inputs_differ(self) -> None:
        assert compute_skill_stream_id("u", "1", "p") != compute_skill_stream_id("u", "2", "p")
        assert compute_skill_stream_id("u1", "1", "p") != compute_skill_stream_id("u2", "1", "p")

    def test_marketplace_skills_differ_by_name(self) -> None:
        # Regression for the collision bug fixed in #726/#772: marketplace
        # repos ship multiple skills at the same (source_url, version); each
        # must land in its own stream.
        a = compute_skill_stream_id("u", "1", "code-review")
        b = compute_skill_stream_id("u", "1", "test-writer")
        assert a != b


@pytest.mark.unit
class TestSkillRegistrationAggregate:
    def test_register_initializes_state(self) -> None:
        agg = SkillRegistrationAggregate()
        cmd = _command()
        agg.register(cmd)

        assert agg.id is not None
        assert agg.source_url == cmd.source_url
        assert agg.skill_version == cmd.version
        assert agg.resolved_sha == cmd.resolved_sha
        assert agg.skill_name == cmd.skill_name
        assert agg.tree_storage_prefix == cmd.tree_storage_prefix
        assert agg.manifest == dict(cmd.manifest)
        assert agg.registered_at is not None

    def test_register_twice_raises(self) -> None:
        agg = SkillRegistrationAggregate()
        agg.register(_command())
        with pytest.raises(ValueError, match="already registered"):
            agg.register(_command())

    def test_emits_one_event(self) -> None:
        agg = SkillRegistrationAggregate()
        agg.register(_command())
        events = agg.get_uncommitted_events()
        assert len(events) == 1
        assert events[0].event.event_type == "SkillRegistered"

    def test_aggregate_type(self) -> None:
        agg = SkillRegistrationAggregate()
        agg.register(_command())
        assert agg.get_aggregate_type() == "SkillRegistration"

    def test_replay_reconstructs_state(self) -> None:
        # Build event stream from a populated aggregate, then replay onto a fresh one
        original = SkillRegistrationAggregate()
        cmd = _command()
        original.register(cmd)
        envelopes = original.get_uncommitted_events()

        replayed = SkillRegistrationAggregate()
        replayed.rehydrate(list(envelopes))

        assert replayed.source_url == cmd.source_url
        assert replayed.skill_version == cmd.version
        assert replayed.resolved_sha == cmd.resolved_sha
        assert replayed.skill_name == cmd.skill_name
        assert replayed.tree_storage_prefix == cmd.tree_storage_prefix
        assert replayed.manifest == dict(cmd.manifest)
