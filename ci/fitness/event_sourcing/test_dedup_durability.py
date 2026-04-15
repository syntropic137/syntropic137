"""Fitness function: dedup durability (content-based, durable dedup in pipeline).

Every event entering the trigger pipeline must pass through a durable
dedup check using content-based keys (commit SHA, PR number, check run ID)
rather than synthetic IDs. This prevents duplicate workflow executions from
the same logical event arriving via multiple sources (webhook, polling,
retry).

Principle: 4. Idempotency (docs/architecture/architectural-fitness.md)
Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import repo_root

if TYPE_CHECKING:
    from pathlib import Path

# Key files in the dedup chain
_PIPELINE_FILE = (
    "packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/pipeline.py"
)
_DEDUP_KEYS_FILE = (
    "packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/dedup_keys.py"
)
_DEDUP_PORT_FILE = (
    "packages/syn-domain/src/syn_domain/contexts/github/slices/event_pipeline/dedup_port.py"
)

# Event types that must have content-based dedup key extractors.
# If a new event type is added and doesn't get a dedup key, it could
# bypass dedup entirely (every occurrence looks unique).
_EXPECTED_DEDUP_EVENT_TYPES = [
    "push",
    "pull_request",
    "check_run",
    "issue_comment",
    "create",
    "delete",
    "pull_request_review",
]


def _file_references(path: Path, symbol: str) -> bool:
    """Check if a file references a symbol (as string in source)."""
    source = path.read_text(encoding="utf-8")
    return symbol in source


@pytest.mark.architecture
class TestDedupDurability:
    """Pipeline must use content-based, durable deduplication."""

    def test_pipeline_calls_dedup(self) -> None:
        """EventPipeline.ingest() must call the dedup port's is_duplicate().

        If the pipeline doesn't check dedup, every event source (webhook,
        Events API poller, Checks API poller) can independently trigger
        the same workflow execution.
        """
        root = repo_root()
        path = root / _PIPELINE_FILE
        assert path.exists(), f"Pipeline file not found: {_PIPELINE_FILE}"
        assert _file_references(path, "is_duplicate"), (
            "EventPipeline must call dedup.is_duplicate() during ingestion. "
            "Without dedup, the same event arriving via webhook AND polling "
            "will trigger duplicate workflow executions."
        )

    def test_dedup_port_protocol_exists(self) -> None:
        """DedupPort protocol must define is_duplicate() and mark_seen()."""
        root = repo_root()
        path = root / _DEDUP_PORT_FILE
        assert path.exists(), f"Dedup port not found: {_DEDUP_PORT_FILE}"

        source = path.read_text(encoding="utf-8")
        assert "is_duplicate" in source, "DedupPort must define is_duplicate()"
        assert "mark_seen" in source, "DedupPort must define mark_seen()"
        assert "Protocol" in source, "DedupPort must be a Protocol class"

    def test_content_based_dedup_keys_exist(self) -> None:
        """compute_dedup_key() must exist and handle multiple event types.

        Dedup keys must be content-based (commit SHA, PR number, etc.)
        rather than synthetic (UUIDs). Content-based keys ensure that the
        same logical event from different sources produces the same key.
        """
        root = repo_root()
        path = root / _DEDUP_KEYS_FILE
        assert path.exists(), f"Dedup keys module not found: {_DEDUP_KEYS_FILE}"
        assert _file_references(path, "compute_dedup_key"), (
            "dedup_keys.py must define compute_dedup_key() for content-based key extraction."
        )

    def test_dedup_keys_cover_known_event_types(self) -> None:
        """compute_dedup_key() must handle all known event types.

        Each event type needs a specific key extractor that uses content
        fields (SHA, PR number, etc.) to produce a deterministic key.
        A generic fallback is acceptable but each known type should have
        its own branch.
        """
        root = repo_root()
        path = root / _DEDUP_KEYS_FILE
        assert path.exists()

        source = path.read_text(encoding="utf-8")
        missing = [et for et in _EXPECTED_DEDUP_EVENT_TYPES if et not in source]

        if missing:
            pytest.fail(
                f"compute_dedup_key() does not reference these event types: {missing}\n\n"
                "Each event type needs a content-based key extractor. Without one,\n"
                "dedup falls through to a generic key that may not correctly identify\n"
                "the same logical event from different sources."
            )

    def test_pipeline_uses_content_based_keys(self) -> None:
        """Pipeline must use event.dedup_key (from compute_dedup_key), not UUIDs.

        If the pipeline generates a new UUID per event, every event looks
        unique and dedup is effectively disabled.
        """
        root = repo_root()
        path = root / _PIPELINE_FILE
        source = path.read_text(encoding="utf-8")

        # Pipeline should reference event.dedup_key (content-based, computed externally)
        assert "event.dedup_key" in source or "dedup_key" in source, (
            "EventPipeline must use content-based dedup keys from the event. "
            "The dedup_key field on NormalizedEvent is computed by compute_dedup_key() "
            "using content fields (SHA, PR number). If the pipeline generates its own "
            "keys (e.g., UUIDs), dedup is effectively disabled."
        )

        # Pipeline should NOT generate UUIDs for dedup (red flag)
        assert "uuid4()" not in source and "uuid.uuid4" not in source, (
            "EventPipeline appears to generate UUIDs for dedup keys. "
            "Dedup keys must be content-based (deterministic from event content) "
            "not synthetic (unique per attempt). See ADR-060."
        )

    def test_postgres_dedup_adapter_exists(self) -> None:
        """A durable (Postgres-backed) dedup adapter must exist.

        In-memory dedup is lost on restart. Redis dedup may be unavailable.
        Postgres dedup is the durable last line of defense.
        """
        root = repo_root()
        adapters = list(root.glob("packages/syn-adapters/src/**/postgres_dedup.py"))
        assert len(adapters) >= 1, (
            "No PostgresDedupAdapter found in syn-adapters. "
            "A durable, Postgres-backed dedup adapter is required to survive restarts. "
            "In-memory and Redis dedup are supplementary, not sufficient."
        )
