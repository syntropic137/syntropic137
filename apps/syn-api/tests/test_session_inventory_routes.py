"""HTTP inventory contract: explicit pending state, bounded pinned reads, current visibility."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from syn_api.routes.executions import inventory
from syn_domain.contexts.agent_sessions import InventoryNotFound, RunIdentity

pytestmark = pytest.mark.unit


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Mock, AsyncMock, RunIdentity]:
    run = RunIdentity(source_instance_id="installation", execution_id="run")
    visible = AsyncMock(return_value=run)
    runtime = Mock()
    runtime.inventory.head = AsyncMock(return_value=None)
    runtime.jobs.latest = AsyncMock(return_value=None)
    runtime.evidence.watermark = AsyncMock(return_value=0)
    runtime.inventory.page = AsyncMock(side_effect=InventoryNotFound("absent"))
    monkeypatch.setattr(inventory, "_visible_run", visible)
    monkeypatch.setattr(inventory, "get_inventory_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(inventory.router)
    return TestClient(app), runtime, visible, run


def test_no_snapshot_is_not_an_empty_success(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
) -> None:
    client, runtime, _, run = setup
    response = client.get("/executions/run/session-inventory")
    assert response.status_code == 200
    assert response.json()["snapshot"] is None
    assert response.json()["reconstruction_status"] == "not_started"
    runtime.evidence.watermark.return_value = 5
    response = client.get("/executions/run/session-inventory")
    assert response.json()["reconstruction_status"] == "pending"
    assert response.json()["later_evidence_pending"] is True
    runtime.inventory.head.assert_awaited_with(run)


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "after=-2"])
def test_page_bounds_reject_before_storage(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
    query: str,
) -> None:
    client, runtime, _, _ = setup
    response = client.get(f"/executions/run/session-inventory/{uuid4()}/node?{query}")
    assert response.status_code == 422
    runtime.inventory.page.assert_not_awaited()


def test_unknown_snapshot_is_not_replaced_with_head(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
) -> None:
    client, runtime, _, run = setup
    snapshot = uuid4()
    response = client.get(f"/executions/run/session-inventory/{snapshot}/node?after=8&limit=3")
    assert response.status_code == 404
    runtime.inventory.page.assert_awaited_once_with(run, snapshot, "node", after=8, limit=3)
    runtime.inventory.head.assert_not_awaited()


def test_visibility_is_checked_again_for_each_page(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
) -> None:
    client, runtime, visible, _ = setup
    assert client.get("/executions/run/session-inventory").status_code == 200
    visible.side_effect = HTTPException(status_code=404, detail="Execution not found")
    assert client.get(f"/executions/run/session-inventory/{uuid4()}/node").status_code == 404
    runtime.inventory.page.assert_not_awaited()
    assert visible.await_count == 2


def test_published_snapshot_reports_late_evidence_without_replacing_revision(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
) -> None:
    from syn_domain.contexts.agent_sessions import (
        InventoryCounts,
        InventoryCoverage,
        InventoryPage,
        InventorySnapshot,
    )

    client, runtime, _, run = setup
    snapshot = InventorySnapshot(
        snapshot_id=uuid4(),
        run=run,
        revision="revision-one",
        resolver_version="test/1",
        evidence_watermark=3,
        coverage=InventoryCoverage.model_validate({"state": "unknown"}),
        counts=InventoryCounts(node=0, membership=0, edge=0, capture=0, gap=0),
    )
    runtime.inventory.head.return_value = snapshot
    runtime.evidence.watermark.return_value = 3
    assert (
        client.get("/executions/run/session-inventory").json()["reconstruction_status"] == "current"
    )
    runtime.evidence.watermark.return_value = 4
    response = client.get("/executions/run/session-inventory").json()
    assert response["reconstruction_status"] == "pending"
    assert response["snapshot"]["revision"] == "revision-one"
    assert response["snapshot"]["evidence_watermark"] == 3
    runtime.inventory.page.side_effect = None
    runtime.inventory.page.return_value = InventoryPage(snapshot=snapshot, kind="node", items=())
    response = client.get(f"/executions/run/session-inventory/{snapshot.snapshot_id}/node")
    assert response.status_code == 200
    assert response.json()["snapshot"]["revision"] == "revision-one"
    assert response.json()["next_after"] is None
    from syn_domain.contexts.agent_sessions import TranscriptBodyState

    runtime.inventory.page.return_value = InventoryPage(snapshot=snapshot, kind="capture", items=())
    runtime.body_availability.overrides = AsyncMock(
        return_value=(TranscriptBodyState(archive_sha256="a" * 64, status="expired"),)
    )
    restricted = client.get(
        f"/executions/run/session-inventory/{snapshot.snapshot_id}/capture"
    ).json()
    assert restricted["body_overrides"] == [{"archive_sha256": "a" * 64, "status": "expired"}]
    assert restricted["snapshot"]["revision"] == "revision-one"


def test_refresh_acknowledges_durable_job_and_reads_without_projection_lag(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
) -> None:
    from syn_domain.contexts.agent_sessions import InventoryReconciliationAggregate

    client, runtime, _, run = setup
    runtime.source_instance_id = run.source_instance_id
    runtime.repository.get_by_id = AsyncMock(return_value=None)

    async def save(aggregate: InventoryReconciliationAggregate) -> None:
        runtime.repository.get_by_id.return_value = aggregate

    runtime.repository.save_new = AsyncMock(side_effect=save)
    response = client.post(
        "/executions/run/session-inventory/reconcile", json={"idempotency_key": "retry-key"}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    repeated = client.post(
        "/executions/run/session-inventory/reconcile", json={"idempotency_key": "retry-key"}
    )
    assert repeated.json()["job_id"] == job_id
    runtime.repository.save_new.assert_awaited_once()
    progress = client.get(f"/session-inventory-jobs/{job_id}")
    assert progress.status_code == 200
    assert progress.json()["stage"] == "pending"
    assert progress.json()["evidence_watermark"] == 0
    runtime.source_instance_id = "another-installation"
    assert client.get(f"/session-inventory-jobs/{job_id}").status_code == 404


@pytest.mark.parametrize("denied", [False, True])
async def test_real_visibility_helper_resolves_prefix_then_checks_access(
    monkeypatch: pytest.MonkeyPatch, denied: bool
) -> None:
    from syn_api.types import Err, Ok

    full_id = str(uuid4())
    store = AsyncMock()
    store.get.return_value = None
    store.get_by_prefix.return_value = [(full_id, {})]
    manager = Mock(store=store)
    detail = AsyncMock(return_value=Err("hidden") if denied else Ok(None))
    runtime = Mock(source_instance_id="installation")
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", lambda: manager)
    monkeypatch.setattr("syn_api.routes.executions.queries.get_detail", detail)
    monkeypatch.setattr(inventory, "get_inventory_runtime", lambda: runtime)
    if denied:
        with pytest.raises(HTTPException) as caught:
            await inventory._visible_run(full_id[:8])
        assert caught.value.status_code == 404
    else:
        assert await inventory._visible_run(full_id[:8]) == RunIdentity(
            source_instance_id="installation", execution_id=full_id
        )
    store.get_by_prefix.assert_awaited_once_with("workflow_execution_details", full_id[:8])
    detail.assert_awaited_once_with(full_id)


@pytest.mark.parametrize("matches,status", [(0, 404), (2, 409)])
async def test_real_visibility_helper_rejects_unknown_or_ambiguous_prefix(
    monkeypatch: pytest.MonkeyPatch, matches: int, status: int
) -> None:
    store = AsyncMock()
    store.get.return_value = None
    store.get_by_prefix.return_value = [(f"abcd-{index}", {}) for index in range(matches)]
    detail = AsyncMock()
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", lambda: Mock(store=store))
    monkeypatch.setattr("syn_api.routes.executions.queries.get_detail", detail)
    with pytest.raises(HTTPException) as caught:
        await inventory._visible_run("abcd")
    assert caught.value.status_code == status
    detail.assert_not_awaited()


@pytest.mark.parametrize("matches,status", [((), 404), (("one", "two"), 409)])
async def test_job_prefix_rejects_missing_or_ambiguous_matches(
    monkeypatch: pytest.MonkeyPatch, matches: tuple[str, ...], status: int
) -> None:
    runtime = Mock(source_instance_id="local")
    runtime.jobs.find_ids = AsyncMock(return_value=matches)
    monkeypatch.setattr(inventory, "get_inventory_runtime", lambda: runtime)
    with pytest.raises(HTTPException) as caught:
        await inventory._resolve_inventory_job_id("abcd")
    assert caught.value.status_code == status
    runtime.jobs.find_ids.assert_awaited_once_with("local", "abcd")


async def test_job_prefix_resolves_and_full_id_bypasses_projection_lag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = str(uuid4())
    runtime = Mock(source_instance_id="local")
    runtime.jobs.find_ids = AsyncMock(return_value=(job_id,))
    monkeypatch.setattr(inventory, "get_inventory_runtime", lambda: runtime)
    assert await inventory._resolve_inventory_job_id(job_id[:8]) == job_id
    runtime.jobs.find_ids.assert_awaited_once_with("local", job_id[:8])
    runtime.jobs.find_ids.reset_mock()
    assert await inventory._resolve_inventory_job_id(job_id) == job_id
    runtime.jobs.find_ids.assert_not_awaited()


@pytest.mark.parametrize(
    "foreign,denied,status", [(False, False, 200), (True, False, 404), (False, True, 404)]
)
def test_job_prefix_route_checks_source_and_current_execution_visibility(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
    foreign: bool,
    denied: bool,
    status: int,
) -> None:
    from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
        ReconciliationRequest,
        ReconciliationState,
    )

    client, runtime, visible, run = setup
    job_id = str(uuid4())
    runtime.source_instance_id = run.source_instance_id
    runtime.jobs.find_ids = AsyncMock(return_value=(job_id,))
    state = ReconciliationState(
        request=ReconciliationRequest(
            run=run.model_copy(update={"source_instance_id": "foreign"}) if foreign else run,
            evidence_watermark=0,
            expected_head=None,
            snapshot_id=uuid4(),
            resolver_version="test/1",
        )
    )
    runtime.repository.get_by_id = AsyncMock(return_value=Mock(state=state))
    if denied:
        visible.side_effect = HTTPException(status_code=404)
    response = client.get(f"/session-inventory-jobs/{job_id[:8]}")
    assert response.status_code == status
    runtime.repository.get_by_id.assert_awaited_once_with(job_id)
    if foreign:
        visible.assert_not_awaited()
    else:
        visible.assert_awaited_once_with(run.execution_id)
    if status == 200:
        assert response.json()["job_id"] == job_id
        assert response.json()["run"] == run.model_dump()


def test_local_transcript_returns_exact_bytes_without_caching(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity],
) -> None:
    import base64

    from syn_domain.contexts.agent_sessions import (
        ArchivedTranscript,
        CataloguedCapture,
        LocalTranscriptRead,
    )

    client, runtime, visible, run = setup
    body = b"opaque\r\n\x00\xff"
    capture = CataloguedCapture(
        run=run,
        producer_id="p",
        capture_id="c",
        harness="codex",
        native_id="opaque/雪",
        content_format="native",
        archive=ArchivedTranscript(sha256="a" * 64, size=len(body)),
    )
    runtime.transcripts.handle = AsyncMock(
        return_value=LocalTranscriptRead(status="present", capture=capture, body=body)
    )
    response = client.get(
        "/executions/run/session-transcripts/" + "a" * 64,
        params={"harness": "codex", "native_id": "opaque/雪"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert base64.b64decode(response.json()["content_base64"]) == body
    assert response.json()["archive_sha256"] == "a" * 64
    visible.assert_awaited_once_with("run")
    args = runtime.transcripts.handle.await_args.args
    assert args[0] == run
    assert args[1].local_id == "opaque/雪"
    assert args[2] == "a" * 64


@pytest.mark.parametrize(
    "failure,status", [(PermissionError("private-token"), 403), (OSError("private-token"), 503)]
)
def test_transcript_access_errors_never_expose_exception_details(
    setup: tuple[TestClient, Mock, AsyncMock, RunIdentity], failure: Exception, status: int
) -> None:
    client, runtime, _, _ = setup
    runtime.transcripts.handle = AsyncMock(side_effect=failure)
    response = client.get(
        "/executions/run/session-transcripts/" + "a" * 64,
        params={"harness": "codex", "native_id": "native"},
    )
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert "private-token" not in response.text
