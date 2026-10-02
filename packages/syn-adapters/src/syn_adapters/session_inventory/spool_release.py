"""Restart-safe owner for staged workspace spool bytes (#1398 rows 10/11).

Staged bytes leave the host only after one of two durable facts:

- ``archived``: the session reached a durable terminal fact (its own
  ``SessionCompleted``, or its execution's terminal event, the same one that
  starts coverage settlement) and a complete traversal that began after it,
  with no other container attached, captured every staged entry into the local archive. Nothing else
  qualifies: an unattached workspace may be paused and resume.
- ``expired``: a settled spool exceeded its retention age, or the byte quota
  forced eviction (settled spools first; a non-terminal spool only when settled
  ones cannot satisfy the quota). An explicit acquisition gap is journaled
  before the volume is removed, so the run's inventory keeps the session
  discoverable and says why its body is absent.

``release_reason`` is committed before removal and ``released_at`` after it, so
a crash between them repeats an idempotent removal. Runs only from the live
inventory tick; projections never call it.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.agent_sessions import (
    AcquisitionGapEvidence,
    CaptureSpool,
    EvidenceBatch,
    EvidenceReference,
    InventoryGap,
    InventoryNodeRef,
    SessionEvidence,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import CaptureSpoolLease
    from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
        SessionEvidenceWritePort,
    )

    from .database import Pool

SPOOL_EXPIRED_GAP = "capture_spool_expired"
_PRODUCER = "capture-spool-retention"


class SpoolVolumePort(Protocol):
    async def remove(self, spool: CaptureSpool) -> bool:
        """True when removed or already absent; False while a container uses it."""
        ...


def expiry_gap(spool: CaptureSpool) -> EvidenceBatch:
    """Deterministic, so a repeated sweep appends the same immutable batch."""
    key = json.dumps(
        ["capture-spool-expired/1", spool.run.source_instance_id, spool.session_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    evidence_id = hashlib.sha256(key.encode()).hexdigest()
    reference = EvidenceReference(
        producer_id=_PRODUCER,
        evidence_id=evidence_id,
        source_revision="1",
        locator=f"capture-spool:{evidence_id}",
        extractor_version="spool-retention/1",
    )
    node = InventoryNodeRef(
        kind="platform", source_instance_id=spool.run.source_instance_id, local_id=spool.session_id
    )
    return EvidenceBatch(
        producer_id=_PRODUCER,
        batch_id=evidence_id,
        evidence=SessionEvidence(
            run=spool.run,
            acquisition_gaps=(
                AcquisitionGapEvidence(
                    gap=InventoryGap(
                        reason=SPOOL_EXPIRED_GAP,
                        node_keys=(node.key,),
                        evidence_ids=(evidence_id,),
                    ),
                    evidence=reference,
                ),
            ),
        ),
    )


class CaptureSpoolRetention:
    def __init__(
        self,
        pool: Pool,
        source: str,
        volumes: SpoolVolumePort,
        journal: SessionEvidenceWritePort,
        *,
        age_seconds: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        if age_seconds is not None and age_seconds < 1:
            raise ValueError("spool retention period must be positive")
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("spool byte quota must be positive")
        self._pool, self._source = pool, source
        self._volumes, self._journal = volumes, journal
        self._age, self._max_bytes = age_seconds, max_bytes

    async def after_drain(self, lease: CaptureSpoolLease, *, exclusive: bool) -> bool:
        if not exclusive or lease.spool.run.source_instance_id != self._source:
            return False
        async with self._pool.acquire() as conn:
            marked = await conn.fetchval(
                """UPDATE session_capture_spools SET release_reason='archived'
                WHERE source_instance_id=$1 AND session_id=$2 AND lease_token=$3
                AND release_reason IS NULL AND drained_at IS NOT NULL AND drained_at=claimed_at
                AND settled_at IS NOT NULL AND settled_at<drained_at
                RETURNING session_id""",
                self._source,
                lease.spool.session_id,
                lease.token,
            )
        if marked is None:
            return False
        return await self._release(lease.spool, "archived")

    async def step(self, limit: int = 20) -> int:
        """Mark due expiries, then complete up to ``limit`` pending releases."""
        if not 1 <= limit <= 500:
            raise ValueError("spool release limit must be 1..500")
        await self._discover(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload::text,release_reason FROM session_capture_spools
                WHERE source_instance_id=$1 AND release_reason IS NOT NULL AND released_at IS NULL
                AND leased_until<=now() ORDER BY registered_at,session_id LIMIT $2""",
                self._source,
                limit,
            )
        released = 0
        for row in rows:
            spool = CaptureSpool.model_validate_json(row["payload"])
            released += await self._release(spool, row["release_reason"])
        return released

    async def _discover(self, limit: int) -> None:
        async with self._pool.acquire() as conn:
            if self._age is not None:
                await conn.execute(
                    """UPDATE session_capture_spools SET release_reason='expired'
                    WHERE (source_instance_id,session_id) IN (
                        SELECT source_instance_id,session_id FROM session_capture_spools
                        WHERE source_instance_id=$1 AND release_reason IS NULL
                        AND leased_until<=now() AND settled_at IS NOT NULL
                        AND registered_at<=now()-$2::double precision*interval '1 second'
                        ORDER BY registered_at,session_id LIMIT $3 FOR UPDATE SKIP LOCKED)""",
                    self._source,
                    self._age,
                    limit,
                )
            if self._max_bytes is not None:
                # Settled spools go first. A non-terminal spool is evicted only
                # when settled ones cannot bring retained bytes within quota,
                # and always with a journaled gap. Newest spools keep their place.
                for settled in (True, False):
                    await conn.execute(
                        """WITH total AS (
                            SELECT COALESCE(sum(staged_bytes),0) AS bytes
                            FROM session_capture_spools
                            WHERE source_instance_id=$1 AND release_reason IS NULL
                        ), candidates AS (
                            SELECT session_id,registered_at,
                            sum(staged_bytes) OVER (ORDER BY registered_at,session_id)
                                - staged_bytes AS evicted_before
                            FROM session_capture_spools
                            WHERE source_instance_id=$1 AND release_reason IS NULL
                            AND (settled_at IS NOT NULL)=$4
                        )
                        UPDATE session_capture_spools s SET release_reason='expired'
                        WHERE s.source_instance_id=$1 AND s.release_reason IS NULL
                        AND s.leased_until<=now() AND s.session_id IN (
                            SELECT c.session_id FROM candidates c,total t
                            WHERE c.evicted_before<t.bytes-$2
                            ORDER BY c.registered_at,c.session_id LIMIT $3)""",
                        self._source,
                        self._max_bytes,
                        limit,
                        settled,
                    )

    async def _release(self, spool: CaptureSpool, reason: str) -> bool:
        if reason == "expired":
            # The gap is durable before any byte disappears.
            await self._journal.append(expiry_gap(spool))
        removed = await self._volumes.remove(spool)
        async with self._pool.acquire() as conn:
            if removed:
                await conn.execute(
                    """UPDATE session_capture_spools SET released_at=now()
                    WHERE source_instance_id=$1 AND session_id=$2 AND released_at IS NULL""",
                    self._source,
                    spool.session_id,
                )
            elif reason == "archived":
                # A container attached after the traversal; its writes are not
                # archived yet, so reopen the spool for capture.
                await conn.execute(
                    """UPDATE session_capture_spools SET release_reason=NULL
                    WHERE source_instance_id=$1 AND session_id=$2
                    AND release_reason='archived' AND released_at IS NULL""",
                    self._source,
                    spool.session_id,
                )
        return removed
