"""Read historical run evidence from sources that already exist (#1398).

Every read here is read-only. Capture verdicts come through the existing typed
payload reader, native facts through the agentic-primitives extraction port,
and billed delegates through a SELECT on the ledger. Nothing here prices,
bills, imports, or parses a harness wire format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syn_adapters.postgres_text import pg_safe
from syn_adapters.session_inventory.deletion_fence import DeletionFence
from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
    read_agent_session_ids,
)
from syn_domain.contexts.agent_sessions import (
    ArchivedTranscriptFacts,
    CataloguedCapture,
    HistoricalAcquisition,
    HistoricalAcquisitionQuotaExceeded,
    LegacyCaptureObservation,
    LegacyDelegateAlias,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.agent_sessions import (
        NativeSessionEvidencePort,
        NativeTranscriptFacts,
        RunIdentity,
        SessionTranscriptArchivePort,
    )

    from .database import Pool


class ObservationRow(Protocol):
    """One flattened observability row; values are validated before use."""

    def get(self, key: str, /) -> object: ...


class CaptureObservationQuery(Protocol):
    """The observability lane's execution-scoped read (``AgentEventStore``)."""

    async def query_by_execution(
        self,
        execution_id: str,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> Sequence[ObservationRow]: ...


def _text(row: ObservationRow, key: str) -> str | None:
    value = row.get(key)
    return value if isinstance(value, str) and value.strip() and "\x00" not in value else None


def legacy_observation(row: ObservationRow) -> LegacyCaptureObservation | None:
    """None for a row that names no phase session: it cannot be scoped honestly."""
    session_id = _text(row, "session_id")
    if session_id is None:
        return None
    version = row.get("schema_version")
    # The existing version-gated reader, never a second copy of its rules.
    natives = read_agent_session_ids(
        {"schema_version": version, "agent_session_ids": row.get("agent_session_ids")}
    )
    return LegacyCaptureObservation(
        platform_session_id=session_id,
        phase_id=_text(row, "phase_id"),
        observed_at=_text(row, "timestamp") or "unrecorded",
        # `type(...) is int`: bool is an int subclass and must not read as 1.
        schema_version=version if type(version) is int else None,
        native_session_ids=None if natives is None else tuple(natives),
    )


class PostgresHistoricalEvidenceSource:
    def __init__(
        self,
        pool: Pool,
        observations: CaptureObservationQuery,
        archive: SessionTranscriptArchivePort,
        extractor: NativeSessionEvidencePort,
        *,
        max_observations: int,
        max_archives: int,
    ) -> None:
        if max_observations < 1 or max_archives < 1:
            raise ValueError("historical acquisition bounds must be positive")
        self._pool, self._observations = pool, observations
        self._archive, self._extractor = archive, extractor
        self._max_observations, self._max_archives = max_observations, max_archives

    async def acquire(self, run: RunIdentity) -> HistoricalAcquisition:
        return HistoricalAcquisition(
            run=run,
            observations=await self._capture_observations(run),
            delegate_aliases=await self._delegate_aliases(run),
            archives=await self._archives(run),
        )

    async def _capture_observations(self, run: RunIdentity) -> tuple[LegacyCaptureObservation, ...]:
        # ALL execution-scoped verdicts, not the latest-per-phase display join.
        rows = await self._observations.query_by_execution(
            run.execution_id,
            event_type=SESSION_CAPTURE_OBSERVATION,
            limit=self._max_observations + 1,
        )
        if len(rows) > self._max_observations:
            raise HistoricalAcquisitionQuotaExceeded("capture observation quota exceeded")
        parsed = (legacy_observation(row) for row in rows)
        return tuple(item for item in parsed if item is not None)

    async def _delegate_aliases(self, run: RunIdentity) -> tuple[LegacyDelegateAlias, ...]:
        async with self._pool.acquire() as conn:
            if await conn.fetchval("SELECT to_regclass('delegate_import_ledger')::text") is None:
                return ()
            rows = await conn.fetch(
                """SELECT harness_session_id FROM delegate_import_ledger
                WHERE execution_id=$1 ORDER BY harness_session_id""",
                pg_safe(run.execution_id),
            )
        return tuple(
            LegacyDelegateAlias(native_session_id=row["harness_session_id"])
            for row in rows
            if row["harness_session_id"].strip()
        )

    async def _archives(self, run: RunIdentity) -> tuple[ArchivedTranscriptFacts, ...]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload::text FROM session_capture_catalog
                WHERE source_instance_id=$1 AND payload->'run'->>'execution_id'=$2
                ORDER BY producer_id,capture_id LIMIT $3""",
                run.source_instance_id,
                run.execution_id,
                self._max_archives + 1,
            )
        if len(rows) > self._max_archives:
            raise HistoricalAcquisitionQuotaExceeded("archived transcript quota exceeded")
        result: list[ArchivedTranscriptFacts] = []
        fence = DeletionFence(self._pool, run.source_instance_id)
        for row in rows:
            capture = CataloguedCapture.model_validate_json(row["payload"])
            if capture.run != run:
                continue
            facts = await self._facts(fence, capture)
            result.append(
                ArchivedTranscriptFacts(
                    producer_id=capture.producer_id,
                    capture_id=capture.capture_id,
                    harness=capture.harness,
                    archive_sha256=capture.archive.sha256,
                    catalogued_native_id=capture.native_id,
                    facts=facts,
                )
            )
        return tuple(result)

    async def _facts(
        self, fence: DeletionFence, capture: CataloguedCapture
    ) -> NativeTranscriptFacts | None:
        """Facts only from bodies with no tombstone, checked and read under the fence.

        A withdrawn body yields no facts, exactly like an absent one: backfill
        never publishes derived content after a deletion request.
        """
        async with fence.shared() as conn:
            tombstoned = await conn.fetchval(
                """SELECT archive_sha256 FROM session_body_deletions
                WHERE source_instance_id=$1 AND archive_sha256=$2""",
                capture.run.source_instance_id,
                capture.archive.sha256,
            )
            if tombstoned is not None:
                return None
            body = await self._archive.get(capture.archive)
            if body is None:
                return None
            return (
                self._extractor.extract_envelope(capture.harness, body)
                if capture.content_format == "envelope"
                else self._extractor.extract(capture.harness, body)
            )
