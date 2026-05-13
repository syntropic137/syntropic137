"""PR2 routing primitive for the materialized claude-plugin (issue #726).

A ``ResolvedClaudePlugin`` is the lock-resolved counterpart of a
``ClaudePluginRef``: source + version + a content-addressed pointer
(``resolved_sha`` + ``tree_storage_prefix``) into the plugin storage
bucket. PR1 declares the field on ``ExecutablePhase`` and
``PhaseDefinition`` but never populates it. PR2 fills it via the
resolution service and the workspace materializer reads it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedClaudePlugin:
    """Lock-resolved pointer to a claude plugin tree in MinIO.

    Attributes:
        name: Directory name under ``<workspace>/.syn-plugins/<name>/``.
        source_url: Canonical source URL (matches the lock key).
        version: User-facing version string (tag/branch/sha as declared).
        resolved_sha: Content sha256 of the plugin tree (lock projection key).
        tree_storage_prefix: MinIO object prefix from which to fetch the tree.
    """

    name: str
    source_url: str
    version: str
    resolved_sha: str
    tree_storage_prefix: str
