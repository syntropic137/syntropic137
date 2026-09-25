"""Current restriction lookup is scoped, bounded and cannot rewrite receipts."""

import json
from uuid import uuid4

import pytest

from syn_adapters.session_inventory.body_availability import PostgresBodyAvailability
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_domain.contexts.agent_sessions import (
    CaptureReceipt,
    EvidenceReference,
    InventoryCounts,
    InventoryCoverage,
    InventoryNodeRef,
    InventoryPage,
    InventorySnapshot,
    RunIdentity,
)

pytestmark = pytest.mark.integration


async def test_current_restrictions_preserve_historical_receipts_and_scope(db_pool):
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    run = RunIdentity(source_instance_id=source, execution_id="run")
    snapshot = InventorySnapshot(
        snapshot_id=uuid4(),
        run=run,
        revision="immutable",
        resolver_version="test",
        evidence_watermark=1,
        coverage=InventoryCoverage(state="unknown"),
        counts=InventoryCounts(node=0, membership=0, edge=0, capture=3, gap=0),
    )
    captures = tuple(
        CaptureReceipt(
            node=InventoryNodeRef(
                kind="transcript", source_instance_id=source, harness="codex", local_id=str(i)
            ),
            availability="present",
            receipt_sequence=i,
            archived_byte_hash=digit * 64,
            evidence=EvidenceReference(
                producer_id="test",
                evidence_id=str(i),
                source_revision="1",
                locator="test",
                extractor_version="1",
            ),
        )
        for i, digit in enumerate("abc", 1)
    )
    page = InventoryPage(snapshot=snapshot, kind="capture", items=captures)
    before = page.model_dump_json()
    reader = PostgresBodyAvailability(db_pool)
    assert await reader.overrides(page) == ()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO session_body_deletions(source_instance_id,archive_sha256,archive,deleted_at) VALUES($1,$2,$3::jsonb,now())",
            source,
            "a" * 64,
            json.dumps({"sha256": "a" * 64, "size": 0}),
        )
        await conn.execute(
            "INSERT INTO session_transcript_revocations(source_instance_id,archive_sha256) VALUES($1,$2)",
            source,
            "b" * 64,
        )
        await conn.execute(
            "INSERT INTO session_transcript_revocations(source_instance_id,archive_sha256) VALUES($1,$2)",
            str(uuid4()),
            "c" * 64,
        )
    result = await reader.overrides(page)
    assert [(item.archive_sha256, item.status) for item in result] == [
        ("a" * 64, "expired"),
        ("b" * 64, "withheld"),
    ]
    assert page.model_dump_json() == before
    remote = page.model_copy(
        update={
            "items": tuple(item.model_copy(update={"destination": "remote"}) for item in captures)
        }
    )
    assert await reader.overrides(remote) == ()
    empty = page.model_copy(update={"items": ()})
    assert await reader.overrides(empty) == ()
