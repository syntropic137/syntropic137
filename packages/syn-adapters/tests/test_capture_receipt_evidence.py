"""Acknowledgement retries must produce the same immutable evidence batch."""

from unittest.mock import AsyncMock

import pytest
from apss_session_capture.inventory import QualifiedTranscript

from syn_adapters.session_inventory.capture_receipt_evidence import publish_capture_receipt
from syn_adapters.session_inventory.exporter_transport import ExporterCaptureReceipt
from syn_domain.contexts.agent_sessions import CataloguedCapture, RunIdentity
from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import ArchivedTranscript

pytestmark = pytest.mark.unit


async def test_duplicate_acknowledgements_replay_identically_and_reject_wrong_identity() -> None:
    capture = CataloguedCapture(
        run=RunIdentity(source_instance_id="source", execution_id="run"),
        producer_id="producer",
        capture_id="capture",
        harness="codex",
        native_id="native",
        content_format="envelope",
        archive=ArchivedTranscript(sha256="a" * 64, size=2),
    )
    identity = QualifiedTranscript(
        source_instance_id="source", harness="codex", native_session_id="native"
    )
    receipt = ExporterCaptureReceipt(
        storage_key=identity.storage_key(),
        content_hash="sha256:" + "b" * 64,
        stored_content_hash="sha256:" + "c" * 64,
        duplicate=False,
    )
    journal = AsyncMock()
    journal.append.return_value = 42
    assert await publish_capture_receipt(journal, capture, "destination", receipt) == 42
    first = journal.append.await_args.args[0]
    await publish_capture_receipt(
        journal, capture, "destination", receipt.model_copy(update={"duplicate": True})
    )
    assert journal.append.await_args.args[0] == first
    assert first.evidence.captures[0].destination == "remote"
    await publish_capture_receipt(journal, capture, "another-destination", receipt)
    assert journal.append.await_args.args[0].batch_id != first.batch_id
    journal.reset_mock()
    with pytest.raises(ValueError, match="another transcript"):
        await publish_capture_receipt(
            journal,
            capture,
            "destination",
            receipt.model_copy(update={"storage_key": "qts1:" + "d" * 64}),
        )
    journal.append.assert_not_called()
