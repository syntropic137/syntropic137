"""Rows 10/11 (#1398): transcript HTTP matrix on real PostgreSQL and a real archive.

Scope decision: Syntropic137 has no per-user principal (ADR-059), so the
boundary here is the installation plus current execution visibility, with
object-level revocation and deletion. Raw-token scope is proven in SeshMagic.
Every case goes through the real routes, catalog, policy and archive; only
execution visibility (a projection lookup) is doubled.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from syn_adapters.session_inventory.body_retention import LocalBodyRetention
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.transcript_access import InstallationTranscriptAccess
from syn_adapters.session_inventory.transcript_deletions import PostgresTranscriptDeletions
from syn_api.routes.executions import transcripts
from syn_domain.contexts.agent_sessions import (
    CataloguedCapture,
    ReadLocalTranscriptHandler,
    RunIdentity,
    TranscriptDeletedError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import asyncpg

pytestmark = pytest.mark.integration

SECRET = "planted-secret-7f3a9c"
VISIBLE = ("run-a", "run-b", "run-c")


@dataclass
class Runtime:
    catalog: PostgresCaptureCatalog
    access: InstallationTranscriptAccess
    deletions: PostgresTranscriptDeletions
    transcripts: ReadLocalTranscriptHandler


@dataclass
class Stack:
    client: httpx.AsyncClient
    runtime: Runtime
    archive: LocalSessionTranscriptArchive
    root: Path
    source: str
    pool: asyncpg.Pool

    async def capture(
        self, execution: str, body: bytes, *, native: str = "native", source: str | None = None
    ) -> CataloguedCapture:
        capture = CataloguedCapture.model_validate(
            {
                "run": {"source_instance_id": source or self.source, "execution_id": execution},
                "producer_id": "test",
                "capture_id": str(uuid4()),
                "harness": "codex",
                "native_id": native,
                "content_format": "native",
                "archive": (await self.archive.put(body)).model_dump(),
            }
        )
        await self.runtime.catalog.record(capture)
        return capture

    async def read(
        self, execution: str, archive_hash: str, *, harness: str = "codex", native: str = "native"
    ) -> httpx.Response:
        return await self.client.get(
            f"/executions/{execution}/session-transcripts/{archive_hash}",
            params={"harness": harness, "native_id": native},
        )


@pytest.fixture
async def stack(
    db_pool: asyncpg.Pool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stack]:
    await PostgresSessionEvidence(db_pool).ensure_ready()
    source = str(uuid4())
    root = tmp_path / "archive"
    archive = LocalSessionTranscriptArchive(root)
    await archive.ensure_ready()
    catalog = PostgresCaptureCatalog(db_pool)
    access = InstallationTranscriptAccess(db_pool, source)
    runtime = Runtime(
        catalog=catalog,
        access=access,
        deletions=PostgresTranscriptDeletions(db_pool, source, None),
        transcripts=ReadLocalTranscriptHandler(catalog, archive, access, max_bytes=64),
    )

    async def visible(execution_id: str) -> RunIdentity:
        if execution_id not in VISIBLE:
            raise HTTPException(status_code=404, detail="Execution not found")
        return RunIdentity(source_instance_id=source, execution_id=execution_id)

    monkeypatch.setattr(transcripts, "_visible_run", visible)
    monkeypatch.setattr(transcripts, "get_inventory_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(transcripts.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield Stack(client, runtime, archive, root, source, db_pool)


def _files(root: Path) -> set[str]:
    return {path.name for path in root.iterdir()}


async def test_shared_object_is_served_exactly_with_named_hash_and_source_redaction(
    stack: Stack,
) -> None:
    body = b"line one\r\n\x00\xff secret-free"
    first = await stack.capture("run-a", body)
    await stack.capture("run-b", body)
    for execution in ("run-a", "run-b"):
        response = await stack.read(execution, first.archive.sha256)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["status"] == "present" and payload["redaction"] == "source"
        assert payload["archive_sha256"] == first.archive.sha256 and payload["size"] == len(body)
        assert base64.b64decode(payload["content_base64"]) == body


@pytest.mark.parametrize(
    "path",
    [
        "/executions/run-a/session-transcripts/" + "A" * 64,
        "/executions/run-a/session-transcripts/" + "a" * 63,
        "/executions/run-a/session-transcripts/..%2F..%2Fetc%2Fpasswd",
        "/executions/run-a/session-transcripts/" + "a" * 64 + "%2F..",
        "/executions/..%2F..%2Fetc/session-transcripts/" + "a" * 64,
    ],
)
async def test_malformed_and_traversal_ids_never_reach_storage(stack: Stack, path: str) -> None:
    before = _files(stack.root)
    response = await stack.client.get(path, params={"harness": "codex", "native_id": "native"})
    assert response.status_code in (404, 422)
    assert "content_base64" not in response.text
    assert _files(stack.root) == before


@pytest.mark.parametrize(
    ("harness", "native"),
    [("codex", "../../../../etc/passwd"), ("../../x", "native"), ("codex", "/etc/shadow")],
)
async def test_traversal_identities_are_opaque_keys_not_paths(
    stack: Stack, harness: str, native: str
) -> None:
    capture = await stack.capture("run-a", b"real bytes")
    before = _files(stack.root)
    response = await stack.read("run-a", capture.archive.sha256, harness=harness, native=native)
    assert response.status_code == 200
    assert response.json()["status"] == "not_captured"
    assert response.json()["content_base64"] is None
    assert _files(stack.root) == before


async def test_nul_identity_is_rejected(stack: Stack) -> None:
    response = await stack.read("run-a", "a" * 64, native="bad\x00id")
    assert response.status_code == 422


async def test_foreign_run_and_foreign_installation_disclose_nothing(stack: Stack) -> None:
    capture = await stack.capture("run-a", b"private to run-a")
    # Not visible: the execution itself does not exist for this caller.
    hidden = await stack.read("run-z", capture.archive.sha256)
    assert hidden.status_code == 404 and capture.archive.sha256 not in hidden.text
    # Visible run without that revision: no bytes, size or format.
    other = await stack.read("run-c", capture.archive.sha256)
    assert other.json() == {
        "status": "not_captured",
        "archive_sha256": capture.archive.sha256,
        "content_format": None,
        "size": None,
        "redaction": "source",
        "content_base64": None,
    }
    for action in ("deletion", "revocation"):
        refused = await stack.client.post(
            f"/executions/run-c/session-transcripts/{capture.archive.sha256}/{action}",
            json={"harness": "codex", "native_id": "native"},
        )
        assert refused.status_code == 404
        assert refused.json() == {"detail": "Transcript revision not found"}
    # Same run name and bytes in another installation: never resolved here.
    foreign = await stack.capture("run-b", b"foreign bytes", source=str(uuid4()))
    response = await stack.read("run-b", foreign.archive.sha256)
    assert response.json()["status"] == "not_captured"
    assert await stack.archive.get(capture.archive) == b"private to run-a"


async def test_revocation_is_whole_object_idempotent_and_retains_bytes(stack: Stack) -> None:
    capture = await stack.capture("run-a", b"shared revoked")
    await stack.capture("run-b", b"shared revoked")
    url = f"/executions/run-a/session-transcripts/{capture.archive.sha256}/revocation"
    identity = {"harness": "codex", "native_id": "native"}
    first = await stack.client.post(url, json=identity)
    assert first.status_code == 200
    assert first.json() == {
        "archive_sha256": capture.archive.sha256,
        "status": "withheld",
        "created": True,
    }
    assert (await stack.client.post(url, json=identity)).json()["created"] is False
    denied = await stack.read("run-b", capture.archive.sha256)
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Transcript access denied"}
    assert denied.headers["cache-control"] == "no-store"
    assert await stack.archive.get(capture.archive) == b"shared revoked"


async def test_deletion_withholds_at_once_erases_later_and_cannot_be_resurrected(
    stack: Stack,
) -> None:
    capture = await stack.capture("run-a", b"delete me")
    await stack.capture("run-b", b"delete me")
    base = f"/executions/run-b/session-transcripts/{capture.archive.sha256}/deletion"
    params = {"harness": "codex", "native_id": "native"}
    assert (await stack.client.get(base, params=params)).status_code == 404
    requested = await stack.client.post(base, json={**params, "reason": "retraction"})
    assert requested.status_code == 202
    assert requested.headers["cache-control"] == "no-store"
    deletion = requested.json()["deletion"]
    assert requested.json()["created"] is True
    assert deletion["reason"] == "retraction" and deletion["local_status"] == "pending"
    assert deletion["archive_sha256"] == capture.archive.sha256
    assert deletion["replication"] == "disabled" and deletion["requested_at"].endswith("Z")
    # Withheld through the other membership before any byte is removed.
    assert (await stack.read("run-a", capture.archive.sha256)).json()["status"] == "deleted"
    assert await stack.archive.get(capture.archive) == b"delete me"
    assert await LocalBodyRetention(stack.pool, stack.archive, stack.source).drain() == 1
    state = await stack.client.get(base, params=params)
    assert state.status_code == 200
    assert state.json()["deletion"]["local_status"] == "deleted"
    assert state.json()["deletion"]["deleted_at"] is not None
    repeat = await stack.client.post(base, json={**params, "reason": "deletion"})
    assert repeat.status_code == 202 and repeat.json()["created"] is False
    assert repeat.json()["deletion"]["reason"] == "retraction"
    with pytest.raises(TranscriptDeletedError):
        await stack.archive.put(b"delete me")
    for execution in ("run-a", "run-b"):
        response = await stack.read(execution, capture.archive.sha256)
        assert response.json()["status"] == "deleted"
        assert response.json()["content_base64"] is None


async def test_expired_missing_and_too_large_are_explicit_states(stack: Stack) -> None:
    expired = await stack.capture("run-a", b"old body")
    async with stack.pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_capture_catalog SET created_at=now()-interval '2 days'
            WHERE source_instance_id=$1""",
            stack.source,
        )
    assert await LocalBodyRetention(
        stack.pool, stack.archive, stack.source, age_seconds=86400
    ).drain()
    assert (await stack.read("run-a", expired.archive.sha256)).json()["status"] == "expired"
    missing = await stack.capture("run-a", b"vanishes", native="gone")
    (stack.root / missing.archive.sha256).unlink()
    response = await stack.read("run-a", missing.archive.sha256, native="gone")
    assert response.json()["status"] == "missing"
    large = await stack.capture("run-a", b"x" * 65, native="large")
    response = await stack.read("run-a", large.archive.sha256, native="large")
    assert response.json()["status"] == "too_large"
    assert response.json()["size"] == 65 and response.json()["content_base64"] is None


async def test_failures_never_expose_secrets_tokens_or_host_paths(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SYN_SESSION_INVENTORY_CAPTURE_WRITE_TOKEN", SECRET)
    monkeypatch.setenv("SYN_SESSION_INVENTORY_REPLICATION_WRITE_TOKEN", SECRET)
    capture = await stack.capture("run-a", b"body")
    outside = f"/private/etc/{SECRET}/{os.getpid()}"
    leaks = (SECRET, outside, str(stack.root))

    async def storage_failure(*_: object) -> None:
        raise OSError(f"cannot open {outside} with token {os.environ[SECRET_ENV]}")

    async def policy_failure(*_: object) -> None:
        raise PermissionError(f"denied by {SECRET} at {stack.root}")

    identity = {"harness": "codex", "native_id": "native"}
    item = f"/executions/run-a/session-transcripts/{capture.archive.sha256}"
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(stack.runtime.access, "require_read", policy_failure)
    denied = await stack.read("run-a", capture.archive.sha256)
    assert denied.status_code == 403
    monkeypatch.setattr(stack.archive, "get", storage_failure)
    monkeypatch.setattr(stack.runtime.access, "require_read", lambda *_: _none())
    unavailable = await stack.read("run-a", capture.archive.sha256)
    assert unavailable.status_code == 503
    monkeypatch.setattr(stack.runtime.catalog, "get_revision", storage_failure)
    responses = [
        denied,
        unavailable,
        await stack.client.post(f"{item}/deletion", json=identity),
        await stack.client.post(f"{item}/revocation", json=identity),
        await stack.client.get(f"{item}/deletion", params=identity),
    ]
    assert [r.status_code for r in responses] == [403, 503, 503, 503, 503]
    for response in responses:
        assert response.headers["cache-control"] == "no-store"
        for leak in leaks:
            assert leak not in response.text
    for leak in leaks:
        assert leak not in caplog.text


SECRET_ENV = "SYN_SESSION_INVENTORY_CAPTURE_WRITE_TOKEN"


async def _none() -> None:
    return None
