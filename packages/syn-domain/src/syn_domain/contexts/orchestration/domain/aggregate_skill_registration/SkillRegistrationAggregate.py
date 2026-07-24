"""SkillRegistration aggregate root (issue #772).

One aggregate per (source_url, version, skill_name). Identity is
deterministic: `skill-{sha256(source_url|version|skill_name)}`. The
`skill_name` component is load-bearing for marketplace repos: a single
(source_url, version) can host many skills. Hashing on the lookup key
without `skill_name` collapses them all to the same stream id and the
first registration shadows the rest. Mirrors
ClaudePluginRegistrationAggregate (issue #726).

The slice handler that calls register() uses repository.save_new() with
ExpectedVersion.NoStream so two concurrent registrations of the same
reference collide cleanly; the losing writer reads the existing aggregate
and short-circuits.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from event_sourcing import AggregateRoot, aggregate, command_handler, event_sourcing_handler

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.skill_ref import SkillManifest
    from syn_domain.contexts.orchestration.domain.commands.RegisterSkillCommand import (
        RegisterSkillCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.SkillRegisteredEvent import (
        SkillRegisteredEvent,
    )


def compute_skill_stream_id(source_url: str, version: str, skill_name: str) -> str:
    """Deterministic stream id derived from the lookup key.

    Why a single hashed id instead of three indexed columns: avoids needing
    a secondary index just to enforce uniqueness on the lookup key - the
    event store's per-stream NoStream check does it for us.

    Why `skill_name` is part of the key: marketplace repos ship multiple
    skills at the same (source_url, version). Hashing without `skill_name`
    collapses them all to one stream and only the first skill registered
    survives.
    """
    digest = hashlib.sha256(f"{source_url}|{version}|{skill_name}".encode()).hexdigest()
    return f"skill-{digest}"


@aggregate("SkillRegistration")
class SkillRegistrationAggregate(AggregateRoot["SkillRegisteredEvent"]):
    _aggregate_type: str

    def __init__(self) -> None:
        super().__init__()
        self._source_url: str | None = None
        # Avoid clashing with BaseAggregate.version (event-store stream version, int)
        self._skill_version: str | None = None
        self._resolved_sha: str | None = None
        self._skill_name: str | None = None
        self._tree_storage_prefix: str | None = None
        # WHY SkillManifest (issue #772): SKILL.md frontmatter may contain
        # nested structures; manifest is opaque metadata downstream.
        self._manifest: SkillManifest = {}
        self._registered_at: datetime | None = None

    def get_aggregate_type(self) -> str:
        return self._aggregate_type

    @staticmethod
    def compute_stream_id(source_url: str, version: str, skill_name: str) -> str:
        return compute_skill_stream_id(source_url, version, skill_name)

    @property
    def source_url(self) -> str | None:
        return self._source_url

    @property
    def skill_version(self) -> str | None:
        return self._skill_version

    @property
    def resolved_sha(self) -> str | None:
        return self._resolved_sha

    @property
    def skill_name(self) -> str | None:
        return self._skill_name

    @property
    def tree_storage_prefix(self) -> str | None:
        return self._tree_storage_prefix

    @property
    def manifest(self) -> SkillManifest:
        return dict(self._manifest)

    @property
    def registered_at(self) -> datetime | None:
        return self._registered_at

    @command_handler("RegisterSkillCommand")
    def register(self, command: RegisterSkillCommand) -> None:
        from syn_domain.contexts.orchestration.domain.events.SkillRegisteredEvent import (
            SkillRegisteredEvent,
        )

        if self.id is not None:
            msg = "Skill already registered"
            raise ValueError(msg)

        self._initialize(command.aggregate_id)

        event = SkillRegisteredEvent(
            source_url=command.source_url,
            version=command.version,
            resolved_sha=command.resolved_sha,
            skill_name=command.skill_name,
            tree_storage_prefix=command.tree_storage_prefix,
            manifest=dict(command.manifest),
            registered_at=datetime.now(UTC),
        )
        self._apply(event)

    @event_sourcing_handler("SkillRegistered")
    def on_skill_registered(self, event: SkillRegisteredEvent) -> None:
        self._source_url = event.source_url
        self._skill_version = event.version
        self._resolved_sha = event.resolved_sha
        self._skill_name = event.skill_name
        self._tree_storage_prefix = event.tree_storage_prefix
        self._manifest = dict(event.manifest)
        self._registered_at = event.registered_at
