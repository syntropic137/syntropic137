"""PR2 routing primitive for the materialized skill (issue #772).

A ``ResolvedSkill`` is the lock-resolved counterpart of a
``SkillRef``: source + version + a content-addressed pointer
(``resolved_sha`` + ``tree_storage_prefix``) into the skill storage
bucket. PR1 declares the field on ``ExecutablePhase`` and
``PhaseDefinition`` but never populates it. PR2 fills it via the
resolution service and the workspace materializer reads it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedSkill:
    """Lock-resolved pointer to a skill tree in MinIO.

    Attributes:
        skill_name: Directory name under ``<workspace>/.syn-skills/<skill_name>/``.
        source_url: Canonical source URL (matches the lock key).
        version: User-facing version string (tag/branch/sha as declared).
        resolved_sha: Content sha256 of the skill tree (lock projection key).
        tree_storage_prefix: MinIO object prefix from which to fetch the tree.
    """

    skill_name: str
    source_url: str
    version: str
    resolved_sha: str
    tree_storage_prefix: str
