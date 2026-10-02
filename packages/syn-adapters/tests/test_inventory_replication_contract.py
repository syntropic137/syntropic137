"""Stable identities and standard validation at the replication boundary."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from syn_adapters.session_inventory.publications import InventoryPublication
from syn_adapters.session_inventory.replication_contract import (
    replication_record,
    replication_revision,
)
from syn_domain.contexts.agent_sessions import (
    InventoryCounts,
    InventoryCoverage,
    InventoryNode,
    InventorySnapshot,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CoverageState,
    InventoryNodeRef,
)

pytestmark = pytest.mark.unit


def publication() -> InventoryPublication:
    return InventoryPublication(
        snapshot=InventorySnapshot(
            snapshot_id=uuid4(),
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            revision="content-digest",
            resolver_version="resolver/1",
            evidence_watermark=3,
            coverage=InventoryCoverage(state=CoverageState.MISSING),
            counts=InventoryCounts(node=1, membership=0, edge=0, capture=0, gap=0),
        ),
        parent_snapshot_id=uuid4(),
        revision_sequence=2,
        first_record_sequence=100,
        record_high_watermark=100,
    )


def test_roundtrip_preserves_qualified_native_identity_and_retry_bytes() -> None:
    local = publication()
    node = InventoryNode(
        ref=InventoryNodeRef(
            kind="transcript",
            source_instance_id="source",
            harness="new-harness",
            local_id="Native/雪 %2F",
        )
    )
    restored = InventoryPublication.model_validate_json(local.model_dump_json())
    first = replication_record(local, "node", 0, node)
    retry = replication_record(restored, "node", 0, node)
    assert first.model_dump_json() == retry.model_dump_json()
    assert first.producer_sequence == 100
    assert first.fact.kind == "node"
    assert first.fact.payload.ref.local_id == node.ref.local_id
    header = replication_revision(local)
    assert header.revision_id == str(local.snapshot.snapshot_id)
    assert header.parent_revision_id == str(local.parent_snapshot_id)
    assert header.coverage == "missing"
    assert header.expected_record_count == 1


def test_cannot_export_cross_namespace_or_wrong_fact_kind() -> None:
    local = publication()
    foreign = InventoryNode(
        ref=InventoryNodeRef(
            kind="transcript", source_instance_id="other", harness="codex", local_id="same-id"
        )
    )
    with pytest.raises(ValidationError):
        replication_record(local, "node", 0, foreign)
    with pytest.raises(ValueError):
        replication_record(local, "node", 1, foreign)
    with pytest.raises(ValueError):
        replication_record(local, "membership", 0, foreign)


async def test_batch_uses_pinned_page_and_queues_publication_after_complete_manifest() -> None:
    from unittest.mock import AsyncMock

    from syn_adapters.session_inventory.replication_batch import replication_batch
    from syn_domain.contexts.agent_sessions import InventoryPage, SessionInventoryReadPort

    local = publication()
    node = InventoryNode(
        ref=InventoryNodeRef(
            kind="transcript", source_instance_id="source", harness="codex", local_id="native"
        )
    )
    store = AsyncMock(spec=SessionInventoryReadPort)
    store.page.return_value = InventoryPage(snapshot=local.snapshot, kind="node", items=(node,))
    batch = await replication_batch(store, local)
    assert batch.next_offset is None
    assert tuple(op.operation for op in batch.operations) == (
        "stage",
        "record",
        "manifest",
        "publish",
    )
    store.head.assert_not_called()
    store.page.assert_awaited_once_with(
        local.snapshot.run, local.snapshot.snapshot_id, "node", after=-1, limit=1
    )
    replay = await replication_batch(store, local)
    assert tuple(op.model_dump_json() for op in replay.operations) == tuple(
        op.model_dump_json() for op in batch.operations
    )


async def test_batch_refuses_missing_published_items() -> None:
    from unittest.mock import AsyncMock

    from syn_adapters.session_inventory.replication_batch import replication_batch
    from syn_domain.contexts.agent_sessions import (
        InventoryPage,
        InventoryPublicationConflict,
        SessionInventoryReadPort,
    )

    local = publication()
    store = AsyncMock(spec=SessionInventoryReadPort)
    store.page.return_value = InventoryPage(snapshot=local.snapshot, kind="node", items=())
    with pytest.raises(InventoryPublicationConflict):
        await replication_batch(store, local)
