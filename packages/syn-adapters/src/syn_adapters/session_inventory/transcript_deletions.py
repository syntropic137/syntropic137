"""Owner-requested body deletion and retraction, recorded before any byte removal.

The request is a durable SQL tombstone keyed by the exact archived bytes. From
that commit on, reads withhold the body, capture delivery stops retrying it and
spool replay cannot restore it. The retention worker erases local bytes; the
capture deletion worker propagates to each configured replication destination.
Catalog rows and inventory revisions are never removed, so the session stays
discoverable with an explicit deleted state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from syn_domain.contexts.agent_sessions import TranscriptDeletion, TranscriptDeletionReplica

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import CataloguedCapture, OwnerDeletionReason

    from .database import Pool


# ISO 8601 UTC rendered by the database; clients format for their locale.
_UTC = """to_char({} AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')"""


class PostgresTranscriptDeletions:
    def __init__(self, pool: Pool, source_instance_id: str, destination_id: str | None) -> None:
        self._pool, self._source, self._destination = pool, source_instance_id, destination_id

    async def request(
        self, capture: CataloguedCapture, reason: OwnerDeletionReason
    ) -> tuple[TranscriptDeletion, bool]:
        """Idempotently record a tombstone. Returns the state and whether it is new.

        An existing tombstone keeps its original reason: bytes already scheduled
        for removal are removed once, and history never changes retroactively.
        """
        if capture.run.source_instance_id != self._source:
            raise PermissionError("transcript is outside this installation")
        async with self._pool.acquire() as conn, conn.transaction():
            created = await conn.fetchval(
                """INSERT INTO session_body_deletions
                (source_instance_id,archive_sha256,archive,reason)
                VALUES ($1,$2,$3::jsonb,$4) ON CONFLICT DO NOTHING RETURNING archive_sha256""",
                self._source,
                capture.archive.sha256,
                capture.archive.model_dump_json(),
                reason,
            )
            # Stop retries now rather than at the next retention tick.
            await conn.execute(
                """UPDATE session_capture_delivery_jobs j SET cancelled=TRUE
                FROM session_capture_catalog c
                WHERE j.source_instance_id=c.source_instance_id
                AND j.producer_id=c.producer_id AND j.capture_id=c.capture_id
                AND c.source_instance_id=$1 AND c.payload->'archive'->>'sha256'=$2
                AND NOT j.cancelled""",
                self._source,
                capture.archive.sha256,
            )
        state = await self.state(capture)
        if state is None:
            raise RuntimeError("deletion tombstone was not recorded")
        return state, created is not None

    async def state(self, capture: CataloguedCapture) -> TranscriptDeletion | None:
        if capture.run.source_instance_id != self._source:
            raise PermissionError("transcript is outside this installation")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT reason,content_hash,{_UTC.format("requested_at")} AS requested_at,
                {_UTC.format("deleted_at")} AS deleted_at
                FROM session_body_deletions WHERE source_instance_id=$1 AND archive_sha256=$2""",
                self._source,
                capture.archive.sha256,
            )
            if not rows:
                return None
            replicable = pending = 0
            if self._destination is not None:
                counts = await conn.fetch(
                    """SELECT count(*)::text AS total,
                    (count(*) FILTER (WHERE k.capture_id IS NULL))::text AS pending
                    FROM session_capture_catalog c
                    LEFT JOIN session_capture_deletion_checkpoints k
                    ON k.source_instance_id=c.source_instance_id AND k.destination_id=$3
                    AND k.producer_id=c.producer_id AND k.capture_id=c.capture_id
                    WHERE c.source_instance_id=$1 AND c.payload->'archive'->>'sha256'=$2
                    AND c.payload->>'content_format'='envelope'
                    AND c.payload->>'native_id' IS NOT NULL""",
                    self._source,
                    capture.archive.sha256,
                    self._destination,
                )
                replicable, pending = int(counts[0]["total"]), int(counts[0]["pending"])
        row = rows[0]
        replication: Literal["disabled", "propagate", "not_applicable"] = "disabled"
        replicas: tuple[TranscriptDeletionReplica, ...] = ()
        if self._destination is not None:
            replication = "propagate" if replicable else "not_applicable"
            if replicable:
                replicas = (
                    TranscriptDeletionReplica(
                        destination_id=self._destination,
                        status="pending" if pending else "propagated",
                    ),
                )
        # Validated, not trusted: a stored reason outside the contract fails loudly.
        return TranscriptDeletion.model_validate(
            {
                "archive_sha256": capture.archive.sha256,
                "source_content_hash": row["content_hash"],
                "reason": row["reason"],
                "local_status": "pending" if row["deleted_at"] is None else "deleted",
                "requested_at": row["requested_at"],
                "deleted_at": row["deleted_at"],
                "replication": replication,
                "replicas": replicas,
            }
        )
