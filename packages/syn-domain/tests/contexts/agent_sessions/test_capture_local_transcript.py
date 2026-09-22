"""Capture cannot acknowledge metadata before local bytes are durable."""

import hashlib
from unittest.mock import AsyncMock, Mock

import pytest

from syn_domain.contexts.agent_sessions import (
    CaptureLocalTranscriptHandler,
    LocalTranscriptCapture,
    NativeTranscriptFacts,
    RunIdentity,
)

pytestmark = pytest.mark.unit


async def test_envelope_capture_archives_original_bytes_and_uses_envelope_boundary() -> None:
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        ArchivedTranscript,
    )

    original = b'{ "raw": "opaque native bytes" }\n'
    archive, evidence = AsyncMock(), AsyncMock()
    digest = hashlib.sha256(original).hexdigest()
    archive.put.return_value = ArchivedTranscript(sha256=digest, size=len(original))
    evidence.append.return_value = 1
    extractor = Mock()
    extractor.extract_envelope.return_value = NativeTranscriptFacts(
        native_id="native",
        extractor_version="envelope/1",
        byte_count=len(original),
    )
    catalog = AsyncMock()
    result = await CaptureLocalTranscriptHandler(
        archive, evidence, extractor, catalog=catalog
    ).handle(
        LocalTranscriptCapture(
            run=RunIdentity(source_instance_id="source", execution_id="run"),
            capture_id="capture",
            harness="fake",
            receipt_sequence=1,
            content=original,
            content_format="envelope",
        )
    )
    extractor.extract.assert_not_called()
    extractor.extract_envelope.assert_called_once_with("fake", original)
    archive.put.assert_awaited_once_with(original)
    assert result.archive.sha256 == digest
    recorded = catalog.record.await_args.args[0]
    assert recorded.archive == result.archive
    assert recorded.content_format == "envelope" and recorded.native_id == "native"
    assert evidence.append.await_args.args[0].evidence.captures[0].archived_byte_hash == digest


async def test_archive_failure_never_publishes_present_receipt() -> None:
    archive, evidence = AsyncMock(), AsyncMock()
    archive.put.side_effect = OSError("archive volume unavailable")
    extractor = Mock()
    extractor.extract.return_value = NativeTranscriptFacts(
        native_id="native",
        extractor_version="fake/1",
        byte_count=4,
    )
    handler = CaptureLocalTranscriptHandler(archive, evidence, extractor)
    with pytest.raises(OSError):
        await handler.handle(
            LocalTranscriptCapture(
                run=RunIdentity(source_instance_id="source", execution_id="run"),
                capture_id="capture",
                harness="fake",
                receipt_sequence=1,
                content=b"body",
            )
        )
    evidence.append.assert_not_awaited()


async def test_catalog_failure_keeps_capture_retryable_before_evidence_ack() -> None:
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        ArchivedTranscript,
    )

    archive, evidence, catalog = AsyncMock(), AsyncMock(), AsyncMock()
    archive.put.return_value = ArchivedTranscript(sha256="a" * 64, size=4)
    catalog.record.side_effect = OSError("catalog unavailable")
    extractor = Mock()
    extractor.extract.return_value = NativeTranscriptFacts(
        native_id=None, extractor_version="fake/1", byte_count=4
    )
    handler = CaptureLocalTranscriptHandler(archive, evidence, extractor, catalog=catalog)
    with pytest.raises(OSError):
        await handler.handle(
            LocalTranscriptCapture(
                run=RunIdentity(source_instance_id="source", execution_id="run"),
                capture_id="capture",
                harness="fake",
                receipt_sequence=1,
                content=b"body",
            )
        )
    archive.put.assert_awaited_once()
    catalog.record.assert_awaited_once()
    evidence.append.assert_not_awaited()
