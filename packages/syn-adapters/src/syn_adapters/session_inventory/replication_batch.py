"""One bounded, deterministic export step over an explicitly pinned publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apss_session_capture.inventory import (
    InventoryManifestBatch,
    ManifestOperation,
    PublishOperation,
    RecordOperation,
    StageOperation,
)

from syn_domain.contexts.agent_sessions import InventoryPublicationConflict

from .replication_contract import ITEM_KINDS, replication_record, replication_revision

if TYPE_CHECKING:
    from apss_session_capture.inventory import InventoryOperation

    from syn_domain.contexts.agent_sessions import SessionInventoryReadPort

    from .publications import InventoryPublication


@dataclass(frozen=True)
class ReplicationBatch:
    operations: tuple[InventoryOperation, ...]
    next_offset: int | None


async def replication_batch(
    inventory: SessionInventoryReadPort,
    publication: InventoryPublication,
    *,
    offset: int = 0,
    limit: int = 50,
) -> ReplicationBatch:
    """The caller persists the cursor only after every operation is durably queued."""
    revision = replication_revision(publication)
    if not 1 <= limit <= 100 or not 0 <= offset <= revision.expected_record_count:
        raise ValueError("replication batch bounds are invalid")
    stage = StageOperation(operation="stage", body=revision)
    publish = PublishOperation(operation="publish", body=revision)
    if offset == revision.expected_record_count:
        return ReplicationBatch(operations=(stage, publish), next_offset=None)
    prefix = 0
    snapshot = publication.snapshot
    for kind in ITEM_KINDS:
        count = getattr(snapshot.counts, kind)
        if offset >= prefix + count:
            prefix += count
            continue
        ordinal = offset - prefix
        size = min(limit, count - ordinal)
        page = await inventory.page(
            snapshot.run, snapshot.snapshot_id, kind, after=ordinal - 1, limit=size
        )
        if page.snapshot != snapshot or len(page.items) != size:
            raise InventoryPublicationConflict("published snapshot differs from its export plan")
        records = tuple(
            replication_record(publication, kind, ordinal + index, item)
            for index, item in enumerate(page.items)
        )
        next_offset = offset + len(records)
        manifest = ManifestOperation(
            operation="manifest",
            body=InventoryManifestBatch(
                revision=revision,
                start=offset,
                record_ids=tuple(record.record_id for record in records),
            ),
        )
        operations = (
            stage,
            *(RecordOperation(operation="record", body=r) for r in records),
            manifest,
        )
        if next_offset == revision.expected_record_count:
            return ReplicationBatch(operations=(*operations, publish), next_offset=None)
        return ReplicationBatch(operations=operations, next_offset=next_offset)
    raise InventoryPublicationConflict("published snapshot has inconsistent item counts")
