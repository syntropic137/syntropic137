"""An exporter failure cannot acknowledge a catalogued capture."""

from unittest.mock import AsyncMock

import pytest

from syn_adapters.session_inventory.capture_delivery_jobs import CaptureDeliveryLease
from syn_adapters.session_inventory.capture_delivery_worker import CaptureDeliveryWorker
from syn_domain.contexts.agent_sessions import CataloguedCapture, RunIdentity
from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import ArchivedTranscript

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("failure", ["archive", "exporter", None])
async def test_capture_checkpoint_follows_durable_enqueue(failure: str | None) -> None:
    jobs, archive, transport = AsyncMock(), AsyncMock(), AsyncMock()
    lease = CaptureDeliveryLease(
        capture=CataloguedCapture(
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            producer_id="spool",
            capture_id="capture",
            harness="codex",
            native_id="native",
            content_format="envelope",
            archive=ArchivedTranscript(sha256="a" * 64, size=2),
        ),
        destination_id="store",
        token=1,
    )
    jobs.claim.return_value = lease
    archive.get.return_value = None if failure == "archive" else b"{}"
    if failure == "exporter":
        transport.enqueue.side_effect = RuntimeError("do-not-log-this-token")
    worker = CaptureDeliveryWorker(jobs, archive, transport, retry_seconds=10)
    assert await worker.enqueue_step()
    if failure is None:
        jobs.finish.assert_awaited_once_with(lease, queued=True)
        assert transport.enqueue.await_args.args[1] == b"{}"
    else:
        jobs.finish.assert_awaited_once_with(lease, queued=False, retry_seconds=10)
    transport.drain.assert_not_awaited()


@pytest.mark.parametrize("failure", ["missing", "journal", "checkpoint", None])
async def test_receipt_publication_precedes_checkpoint_and_retries_identically(
    failure: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    from apss_session_capture.inventory import QualifiedTranscript

    from syn_adapters.session_inventory.exporter_transport import ExporterCaptureReceipt

    jobs, archive, transport, journal = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id="source", execution_id="run"),
        producer_id="spool",
        capture_id="capture",
        harness="codex",
        native_id="native",
        content_format="envelope",
        archive=ArchivedTranscript(sha256="a" * 64, size=2),
    )
    lease = CaptureDeliveryLease(capture=capture, destination_id="store", token=1)
    jobs.claim_receipt.return_value = lease
    archive.get.return_value = b"{}"
    identity = QualifiedTranscript(
        source_instance_id="source", harness="codex", native_session_id="native"
    )
    receipt = ExporterCaptureReceipt(
        storage_key=identity.storage_key(),
        content_hash="sha256:" + "b" * 64,
        stored_content_hash="sha256:" + "c" * 64,
        duplicate=False,
    )
    transport.receipt.return_value = None if failure == "missing" else receipt
    if failure == "journal":
        journal.append.side_effect = RuntimeError("private-token")
    if failure == "checkpoint":
        jobs.finish_receipt.side_effect = [RuntimeError("private-token"), None, None]
    worker = CaptureDeliveryWorker(jobs, archive, transport, journal=journal, retry_seconds=10)
    assert await worker.receipt_step()
    if failure is None:
        jobs.finish_receipt.assert_awaited_once_with(lease, recorded=True, retry_seconds=10)
        journal.append.assert_awaited_once()
    elif failure == "missing":
        journal.append.assert_not_called()
        jobs.finish_receipt.assert_awaited_once_with(lease, recorded=False, retry_seconds=10)
    else:
        assert jobs.finish_receipt.await_args.kwargs["recorded"] is False
        original = journal.append.await_args.args[0]
        journal.append.side_effect = None
        transport.receipt.return_value = receipt.model_copy(update={"duplicate": True})
        assert await worker.receipt_step()
        assert journal.append.await_args.args[0] == original
        assert jobs.finish_receipt.await_args.kwargs["recorded"] is True
    assert "private-token" not in caplog.text
    transport.enqueue.assert_not_called()
    transport.drain.assert_not_called()
