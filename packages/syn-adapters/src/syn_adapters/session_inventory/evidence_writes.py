"""Atomic evidence writes and bounded acquisition-status transition checkpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    InventoryPublicationConflict,
    SessionEvidence,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import RunIdentity

    from .database import Connection


async def lock_run(conn: Connection, run: RunIdentity) -> int:
    args = (run.source_instance_id, run.execution_id)
    await conn.execute(
        """INSERT INTO session_evidence_watermarks (source_instance_id,execution_id)
        VALUES ($1,$2) ON CONFLICT DO NOTHING""",
        *args,
    )
    current = await conn.fetchval(
        """SELECT watermark::text FROM session_evidence_watermarks
        WHERE source_instance_id=$1 AND execution_id=$2 FOR UPDATE""",
        *args,
    )
    if current is None:
        raise RuntimeError("missing evidence counter after initialization")
    return int(current)


async def append_locked(conn: Connection, batch: EvidenceBatch, current: int) -> int:
    run = batch.evidence.run
    args = (run.source_instance_id, run.execution_id)
    prior = await conn.fetch(
        """SELECT sequence::text,payload::text FROM session_evidence_batches
        WHERE source_instance_id=$1 AND execution_id=$2 AND producer_id=$3 AND batch_id=$4""",
        *args,
        batch.producer_id,
        batch.batch_id,
    )
    if prior:
        if EvidenceBatch.model_validate_json(prior[0]["payload"]) != batch:
            raise InventoryPublicationConflict("evidence batch identity reused")
        return int(prior[0]["sequence"])
    sequence = current + 1
    await conn.execute(
        """INSERT INTO session_evidence_batches
        (source_instance_id,execution_id,sequence,producer_id,batch_id,payload)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
        *args,
        sequence,
        batch.producer_id,
        batch.batch_id,
        batch.model_dump_json(),
    )
    await conn.execute(
        """UPDATE session_evidence_watermarks SET watermark=$3
        WHERE source_instance_id=$1 AND execution_id=$2""",
        *args,
        sequence,
    )
    return sequence


async def observe_status(conn: Connection, batch: EvidenceBatch, current: int) -> int:
    source = batch.evidence
    if len(source.acquisition_statuses) != 1 or source != SessionEvidence(
        run=source.run, acquisition_statuses=source.acquisition_statuses
    ):
        raise ValueError("Acquisition observation must contain exactly one status")
    status = source.acquisition_statuses[0]
    if status.evidence.producer_id != batch.producer_id:
        raise ValueError("Acquisition producer differs from its batch")
    args = (
        source.run.source_instance_id,
        source.run.execution_id,
        batch.producer_id,
        status.stream_id,
    )
    prior = await conn.fetch(
        """SELECT evidence_sequence::text AS sequence,payload::text
        FROM session_acquisition_heads
        WHERE source_instance_id=$1 AND execution_id=$2 AND producer_id=$3 AND stream_id=$4""",
        *args,
    )
    if not prior:
        # Seed once from an indexed legacy status. Upgrades must not forget the
        # old sequence fence, even when the first incoming observation is stale.
        prior = await conn.fetch(
            """SELECT sequence::text,payload::text FROM session_evidence_batches
            WHERE source_instance_id=$1 AND execution_id=$2 AND producer_id=$3
              AND jsonb_array_length(payload->'evidence'->'acquisition_statuses')=1
              AND payload->'evidence'->'acquisition_statuses'->0->>'stream_id'=$4
            ORDER BY (payload->'evidence'->'acquisition_statuses'->0->>'sequence')::bigint DESC
            LIMIT 1""",
            *args,
        )
    sequence = None
    if prior:
        previous = EvidenceBatch.model_validate_json(prior[0]["payload"])
        prior_status = previous.evidence.acquisition_statuses[0]
        if status.sequence < prior_status.sequence:
            return int(prior[0]["sequence"])
        if status.sequence == prior_status.sequence:
            if previous != batch:
                raise InventoryPublicationConflict("acquisition sequence reused")
            return int(prior[0]["sequence"])
        if (status.failed, status.reason, status.evidence.extractor_version) == (
            prior_status.failed,
            prior_status.reason,
            prior_status.evidence.extractor_version,
        ):
            sequence = int(prior[0]["sequence"])
    if sequence is None:
        sequence = await append_locked(conn, batch, current)
    await conn.execute(
        """INSERT INTO session_acquisition_heads
        (source_instance_id,execution_id,producer_id,stream_id,evidence_sequence,payload)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb)
        ON CONFLICT (source_instance_id,execution_id,producer_id,stream_id)
        DO UPDATE SET evidence_sequence=EXCLUDED.evidence_sequence,payload=EXCLUDED.payload""",
        *args,
        sequence,
        batch.model_dump_json(),
    )
    return sequence
