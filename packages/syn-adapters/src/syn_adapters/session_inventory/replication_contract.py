"""Map published domain snapshots to the canonical APSS replication contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from apss_session_capture.inventory import (
    Coverage,
    Fact,
    InventoryRecord,
    InventoryRevision,
    QualifiedRun,
)
from pydantic import BaseModel, ConfigDict, TypeAdapter

from syn_domain.contexts.agent_sessions import (
    InventoryItem,  # noqa: TC001 - Pydantic resolves the fact payload at runtime
    ItemKind,  # noqa: TC001 - Pydantic resolves the discriminator at runtime
)

if TYPE_CHECKING:
    from .publications import InventoryPublication

PRODUCER_ID = "syntropic137-inventory"
# Persisted sequence allocation depends on this order. Changes require a new producer version.
ITEM_KINDS: tuple[ItemKind, ...] = (
    "node",
    "membership",
    "edge",
    "capture",
    "gap",
    "retraction",
    "binding",
)
_FACT: TypeAdapter[Fact] = TypeAdapter(Fact)


class _FactInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ItemKind
    payload: InventoryItem


def replication_revision(publication: InventoryPublication) -> InventoryRevision:
    snapshot = publication.snapshot
    return InventoryRevision(
        run=QualifiedRun(
            source_instance_id=snapshot.run.source_instance_id,
            execution_id=snapshot.run.execution_id,
        ),
        revision_id=str(snapshot.snapshot_id),
        parent_revision_id=str(publication.parent_snapshot_id)
        if publication.parent_snapshot_id is not None
        else None,
        revision_sequence=publication.revision_sequence,
        producer_id=PRODUCER_ID,
        sequence_high_watermark=publication.record_high_watermark,
        resolver_version=snapshot.resolver_version,
        coverage=cast("Coverage", snapshot.coverage.state.value),
        expected_record_count=sum(getattr(snapshot.counts, kind) for kind in ITEM_KINDS),
    )


def replication_record(
    publication: InventoryPublication, kind: ItemKind, ordinal: int, item: InventoryItem
) -> InventoryRecord:
    counts = publication.snapshot.counts
    if kind not in ITEM_KINDS or not 0 <= ordinal < getattr(counts, kind):
        raise ValueError("record ordinal exceeds the published snapshot")
    offset = sum(getattr(counts, previous) for previous in ITEM_KINDS[: ITEM_KINDS.index(kind)])
    revision = replication_revision(publication)
    return InventoryRecord(
        run=revision.run,
        producer_id=PRODUCER_ID,
        record_id=f"{revision.revision_id}:{kind}:{ordinal}",
        producer_sequence=publication.first_record_sequence + offset + ordinal,
        fact=_FACT.validate_json(_FactInput(kind=kind, payload=item).model_dump_json()),
    )
