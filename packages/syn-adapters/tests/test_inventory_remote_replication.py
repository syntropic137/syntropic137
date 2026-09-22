"""Local SQL publications -> real Rust exporter -> independent SeshMagic HTTP/SQL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest
from apss_session_capture.inventory import (
    Coverage,
    InventoryRecord,
    InventoryRevision,
    QualifiedRun,
    QualifiedTranscript,
)
from pydantic import BaseModel, ConfigDict, SecretStr
from testcontainers.postgres import PostgresContainer

from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.capture_delivery_jobs import (
    CaptureDeliveryLeaseLost,
    PostgresCaptureDeliveryJobs,
)
from syn_adapters.session_inventory.capture_delivery_worker import CaptureDeliveryWorker
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.exporter_transport import (
    ExporterCaptureTransport,
    ExporterConfig,
    ExporterInventoryTransport,
)
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_adapters.session_inventory.replication_jobs import PostgresReplicationJobs
from syn_adapters.session_inventory.replication_worker import InventoryReplicationWorker
from syn_domain.contexts.agent_sessions import (
    CaptureReceipt,
    CataloguedCapture,
    IdentityBinding,
    InventoryCounts,
    InventoryCoverage,
    InventoryGap,
    InventoryNode,
    InventorySnapshot,
    LineageEdge,
    Membership,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

pytestmark = pytest.mark.integration


class RemotePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    run: QualifiedRun
    revision: InventoryRevision | None
    coverage: Coverage
    records: tuple[InventoryRecord, ...]
    next_after: int | None


class CaptureVersionProjection(BaseModel):
    """Only fields used by this test; the full envelope belongs to APSS."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    content_hash: str
    session_id: str
    raw: str


class McpText(BaseModel):
    type: str
    text: str


class McpResult(BaseModel):
    content: tuple[McpText, ...]


class McpError(BaseModel):
    code: int
    message: str


class McpReply(BaseModel):
    jsonrpc: str
    id: int
    result: McpResult | None = None
    error: McpError | None = None


async def mcp_query(binary: Path, url: str, token: str, run: RunIdentity) -> McpReply:
    process = await asyncio.create_subprocess_exec(
        str(binary),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"SESSION_STORE_URL": url, "SESSIONS_READ_TOKEN": token},
    )
    request = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "workflow_run_sessions",
                    "arguments": {
                        "source_instance_id": run.source_instance_id,
                        "execution_id": run.execution_id,
                    },
                },
            }
        )
        + "\n"
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(request.encode()), timeout=10)
        assert process.returncode == 0, errors.decode()
        return McpReply.model_validate_json(output)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@asynccontextmanager
async def server(
    binary: Path,
    database: str,
    port: int,
    source: str,
    log: Path,
    *,
    read_token: str = "read-test",
    grants: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            stdout=output,
            stderr=output,
            env={
                "DATABASE_URL": database,
                "BIND_ADDR": f"127.0.0.1:{port}",
                "SESSIONS_READ_TOKEN": read_token,
                "SESSIONS_RAW_READ_TOKEN": "raw-test",
                "SESSIONS_WRITE_TOKEN": "ordinary-write-test",
                "INVENTORY_WRITE_GRANTS": json.dumps(
                    [
                        {
                            "token": "inventory-test",
                            "source_instance_id": source,
                            "producer_id": "syntropic137-inventory",
                        }
                    ]
                    if grants
                    else []
                ),
                "CAPTURE_WRITE_GRANTS": json.dumps(
                    [
                        {
                            "token": "capture-test",
                            "source_instance_id": source,
                            "harness": "third-party",
                        }
                    ]
                    if grants
                    else []
                ),
                "LOG_FORMAT": "json",
            },
        )
        try:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False
            ) as client:
                async with asyncio.timeout(30):
                    while True:
                        if process.returncode is not None:
                            raise AssertionError(f"SeshMagic exited during startup; inspect {log}")
                        try:
                            if (await client.get("/healthz")).is_success:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.05)
                yield client
        finally:
            if process.returncode is None:
                process.terminate()
            await process.wait()


async def publish(
    store: PostgresSessionInventory, run: RunIdentity, version: int
) -> InventorySnapshot:
    evidence = EvidenceReference(
        evidence_id=f"e{version}",
        producer_id="observer",
        source_revision=str(version),
        locator="fixture",
        extractor_version="fixture/1",
    )
    owner = InventoryNodeRef(
        kind="invocation", source_instance_id=run.source_instance_id, local_id=f"attempt-{version}"
    )
    native = InventoryNodeRef(
        kind="transcript",
        source_instance_id=run.source_instance_id,
        harness="third-party",
        local_id=f"Native/雪 %2F-{version}",
    )
    item = InventorySnapshot(
        snapshot_id=uuid4(),
        run=run,
        revision=f"revision-{version}",
        resolver_version="resolver/1",
        evidence_watermark=version,
        coverage=InventoryCoverage(state=CoverageState.MISSING),
        counts=InventoryCounts(node=2, membership=1, edge=1, capture=1, gap=1, binding=1),
    )
    old = await store.head(run)
    await store.stage(item)
    await store.append(
        run,
        item.snapshot_id,
        "node",
        0,
        (
            InventoryNode(ref=owner, evidence=(evidence,)),
            InventoryNode(ref=native, evidence=(evidence,)),
        ),
    )
    await store.append(
        run,
        item.snapshot_id,
        "membership",
        0,
        (
            Membership(
                node=native,
                run=run,
                phase_id="phase",
                attempt_id=f"attempt-{version}",
                confidence=EvidenceClass.REGISTERED,
                evidence=(evidence,),
            ),
        ),
    )
    await store.append(
        run,
        item.snapshot_id,
        "edge",
        0,
        (
            LineageEdge(
                parent=owner,
                child=native,
                relation="spawn",
                confidence=EvidenceClass.REGISTERED,
                evidence=(evidence,),
            ),
        ),
    )
    await store.append(
        run,
        item.snapshot_id,
        "binding",
        0,
        (
            IdentityBinding(
                owner=owner,
                transcript=native,
                confidence=EvidenceClass.REGISTERED,
                evidence=(evidence,),
            ),
        ),
    )
    await store.append(
        run,
        item.snapshot_id,
        "capture",
        0,
        (
            CaptureReceipt(
                node=native,
                availability=BodyAvailability.MISSING,
                receipt_sequence=version,
                evidence=evidence,
            ),
        ),
    )
    await store.append(
        run,
        item.snapshot_id,
        "gap",
        0,
        (InventoryGap(reason="missing_native_body", node_keys=(native.key,)),),
    )
    await store.publish(run, item.snapshot_id, None if old is None else old.snapshot_id)
    return item


async def queue_all(worker: InventoryReplicationWorker) -> None:
    for _ in range(30):
        if not await worker.enqueue_step():
            return
    pytest.fail("replication did not finish its bounded local fixture")


async def test_real_capture_delivery_preserves_versions_and_survives_revocation(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
    unused_tcp_port: int,
) -> None:
    exporter_path = os.environ.get("SYN_TEST_EXPORTER_BINARY")
    server_path = os.environ.get("SYN_TEST_SESHMAGIC_BINARY")
    if exporter_path is None or server_path is None:
        pytest.skip("built exporter and SeshMagic server binaries required")
    binary = Path(exporter_path)
    source = f"capture-{uuid4()}"
    native = "Native/雪 %2F"
    url = f"http://127.0.0.1:{unused_tcp_port}"
    root = tmp_path / "capture-outbox"

    identity = QualifiedTranscript(
        source_instance_id=source, harness="third-party", native_session_id=native
    )
    config = ExporterConfig(
        binary=binary, outbox_dir=root, store_url=url, token=SecretStr("capture-test")
    )
    transport = ExporterCaptureTransport(config)
    await PostgresSessionInventory(db_pool).ensure_ready()
    archive = LocalSessionTranscriptArchive(tmp_path / "archive")
    await archive.ensure_ready()
    catalog = PostgresCaptureCatalog(db_pool)
    jobs = PostgresCaptureDeliveryJobs(db_pool, source, "capture-integration")
    worker = CaptureDeliveryWorker(jobs, archive, transport, retry_seconds=0)
    run = RunIdentity(source_instance_id=source, execution_id="run")

    async def capture(capture_id: str, body: bytes) -> None:
        await catalog.record(
            CataloguedCapture(
                run=run,
                producer_id="producer",
                capture_id=capture_id,
                harness=identity.harness,
                native_id=native,
                content_format="envelope",
                archive=await archive.put(body),
            )
        )
        assert await worker.enqueue_step()
        assert not await worker.enqueue_step()

    def payload(raw: str) -> bytes:
        return json.dumps(
            {
                "scs_version": "1.0",
                "origin": {"host": "test", "environment": "local"},
                "agent": "third-party",
                "source_format": "third-party-jsonl",
                "session_id": native,
                "started_at": "2026-09-22T00:00:00Z",
                "last_activity_at": "2026-09-22T00:00:01Z",
                "raw": raw,
            }
        ).encode()

    first = payload("line\r\nsk-123456789012345678901234\r\n")
    await capture("first", first)
    pending_lease = await jobs.claim_receipt()
    assert pending_lease is not None
    assert await jobs.claim_receipt() is None
    await jobs.finish_receipt(pending_lease, recorded=False, retry_seconds=0)
    assert await transport.receipt(identity, first) is None
    outage = await worker.drain_step()
    assert outage.failed == 1 and outage.remaining == 1
    worker = CaptureDeliveryWorker(
        PostgresCaptureDeliveryJobs(db_pool, source, "capture-integration"),
        LocalSessionTranscriptArchive(tmp_path / "archive"),
        ExporterCaptureTransport(config),
        retry_seconds=0,
    )
    assert not await worker.enqueue_step()
    with PostgresContainer("postgres:16-alpine") as remote_db:
        database = remote_db.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        async with server(
            Path(server_path), database, unused_tcp_port, source, tmp_path / "capture.log"
        ) as client:
            sent = await worker.drain_step()
            assert sent.acknowledged == 1 and sent.remaining == 0
            accepted = await ExporterCaptureTransport(config).receipt(identity, first)
            assert accepted is not None
            assert accepted.storage_key == identity.storage_key()
            assert await transport.receipt(identity, payload("not-delivered")) is None
            params = (
                ("source_instance_id", source),
                ("harness", "third-party"),
                ("native_session_id", native),
            )
            response = await client.get(
                "/v1/transcripts", params=params, headers={"Authorization": "Bearer read-test"}
            )
            response.raise_for_status()
            old = CaptureVersionProjection.model_validate_json(response.content)
            assert old.session_id == native and old.raw == "line\r\n[REDACTED]\r\n"
            assert accepted.content_hash == old.content_hash
            receipt_lease = await jobs.claim_receipt()
            assert receipt_lease is not None and receipt_lease.token > pending_lease.token
            with pytest.raises(CaptureDeliveryLeaseLost):
                await jobs.finish_receipt(pending_lease, recorded=True)
            await jobs.finish_receipt(receipt_lease, recorded=False, retry_seconds=0)
            journal = PostgresSessionEvidence(db_pool)
            receipt_worker = CaptureDeliveryWorker(
                jobs, archive, ExporterCaptureTransport(config), journal=journal, retry_seconds=0
            )
            assert await receipt_worker.receipt_step()
            assert await journal.watermark(run) == 1
            assert not await receipt_worker.receipt_step()
            assert await journal.watermark(run) == 1
            assert await jobs.claim_receipt() is None
            await capture("second", payload("second\r\n"))
            assert (await worker.drain_step()).remaining == 0
            retry = await transport.enqueue(identity, first)
            assert retry.inserted is False
            raw = await client.get(
                "/v1/transcripts/raw", params=params, headers={"Authorization": "Bearer raw-test"}
            )
            assert raw.content == b"second\r\n"
            assert (
                raw.headers["X-Stored-Content-Hash"]
                == f"sha256:{hashlib.sha256(raw.content).hexdigest()}"
            )
            history = await client.get(
                "/v1/transcripts/raw",
                params=(*params, ("content_hash", old.content_hash)),
                headers={"Authorization": "Bearer raw-test"},
            )
            assert history.content == old.raw.encode()
        await capture("third", payload("third\r\n"))
        async with server(
            Path(server_path),
            database,
            unused_tcp_port,
            source,
            tmp_path / "capture-revoked.log",
            grants=False,
        ) as client:
            pending = await worker.drain_step()
            assert pending.failed == 1 and pending.remaining == 1
            raw = await client.get(
                "/v1/transcripts/raw", params=params, headers={"Authorization": "Bearer raw-test"}
            )
            assert raw.content == b"second\r\n"


async def test_outage_restart_historical_pages_and_revoked_grants(
    db_pool: asyncpg.Pool,
    tmp_path: Path,
    unused_tcp_port: int,
) -> None:
    exporter_path, server_path = (
        os.environ.get("SYN_TEST_EXPORTER_BINARY"),
        os.environ.get("SYN_TEST_SESHMAGIC_BINARY"),
    )
    mcp_path = os.environ.get("SYN_TEST_SESHMAGIC_MCP_BINARY")
    if exporter_path is None or server_path is None or mcp_path is None:
        pytest.skip("built exporter, SeshMagic server, and MCP binaries required")
    run = RunIdentity(source_instance_id=f"integration-{uuid4()}", execution_id="run")
    local = PostgresSessionInventory(db_pool)
    await local.ensure_ready()
    config = ExporterConfig(
        binary=Path(exporter_path),
        outbox_dir=tmp_path / "outbox",
        store_url=f"http://127.0.0.1:{unused_tcp_port}",
        token=SecretStr("inventory-test"),
    )
    jobs = PostgresReplicationJobs(db_pool, run.source_instance_id, "integration-destination")
    worker = InventoryReplicationWorker(
        jobs, local, ExporterInventoryTransport(config), retry_seconds=0
    )
    first = await publish(local, run, 1)
    await queue_all(worker)
    outage = await worker.drain_step()
    assert outage.failed > 0 and outage.remaining > 0
    second = await publish(local, run, 2)
    assert await local.head(run) == second
    await queue_all(worker)
    # Fresh Python adapter and fresh exporter processes recover the existing outbox.
    restarted = InventoryReplicationWorker(jobs, local, ExporterInventoryTransport(config))
    with PostgresContainer("postgres:16-alpine") as remote_db:
        database = remote_db.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        endpoint = f"/v1/workflow-runs/{run.source_instance_id}/{run.execution_id}/sessions"
        async with server(
            Path(server_path),
            database,
            unused_tcp_port,
            run.source_instance_id,
            tmp_path / "server.log",
        ) as client:
            for _ in range(5):
                if (await restarted.drain_step()).remaining == 0:
                    break
            else:
                pytest.fail("remote inventory publication did not converge")
            response = await client.get(endpoint, headers={"Authorization": "Bearer read-test"})
            response.raise_for_status()
            page = RemotePage.model_validate_json(response.content)
            assert page.revision is not None and page.revision.revision_id == str(
                second.snapshot_id
            )
            assert page.coverage == "missing"
            assert {record.fact.kind for record in page.records} == {
                "node",
                "membership",
                "edge",
                "binding",
                "capture",
                "gap",
            }
            native = [
                record.fact.payload.ref.local_id
                for record in page.records
                if record.fact.kind == "node" and record.fact.payload.ref.kind == "transcript"
            ]
            assert native == ["Native/雪 %2F-2"]
            mcp = await mcp_query(Path(mcp_path), config.store_url, "read-test", run)
            assert mcp.error is None and mcp.result is not None
            discovered = RemotePage.model_validate_json(mcp.result.content[0].text)
            assert discovered == page

            history = await client.get(
                endpoint,
                params={"revision_id": str(first.snapshot_id), "limit": 1},
                headers={"Authorization": "Bearer read-test"},
            )
            pinned = RemotePage.model_validate_json(history.content)
            assert pinned.revision is not None and pinned.revision.revision_id == str(
                first.snapshot_id
            )
            assert pinned.next_after == 0
            next_page = await client.get(
                endpoint,
                params={
                    "revision_id": str(first.snapshot_id),
                    "after": pinned.next_after,
                    "limit": 1,
                },
                headers={"Authorization": "Bearer read-test"},
            )
            assert RemotePage.model_validate_json(next_page.content).records[0].fact.kind == "node"
            assert (
                await client.get(endpoint, headers={"Authorization": "Bearer inventory-test"})
            ).status_code == 401
        third = await publish(local, run, 3)
        await queue_all(restarted)
        async with server(
            Path(server_path),
            database,
            unused_tcp_port,
            run.source_instance_id,
            tmp_path / "restarted.log",
            read_token="new-read",
            grants=False,
        ) as client:
            revoked = await restarted.drain_step()
            assert revoked.failed > 0 and revoked.remaining > 0
            assert await local.head(run) == third
            denied_mcp = await mcp_query(Path(mcp_path), config.store_url, "read-test", run)
            assert denied_mcp.result is None and denied_mcp.error is not None
            assert "401" in denied_mcp.error.message

            assert (
                await client.get(endpoint, headers={"Authorization": "Bearer read-test"})
            ).status_code == 401
            response = await client.get(endpoint, headers={"Authorization": "Bearer new-read"})
            page = RemotePage.model_validate_json(response.content)
            assert page.revision is not None and page.revision.revision_id == str(
                second.snapshot_id
            )
