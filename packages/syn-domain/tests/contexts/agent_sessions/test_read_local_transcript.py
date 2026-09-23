"""Historical bodies require current whole-object permission before any byte read."""

from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.agent_sessions import ArchivedTranscript, CataloguedCapture, RunIdentity
from syn_domain.contexts.agent_sessions.ports.QualifiedSessionStorePort import (
    QualifiedSessionIdentity,
)
from syn_domain.contexts.agent_sessions.slices.read_local_transcript.ReadLocalTranscriptHandler import (
    ReadLocalTranscriptHandler,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "outcome",
    ["present", "missing", "expired", "not_captured", "denied", "too_large", "unavailable"],
)
async def test_exact_revision_access_and_storage_outcomes(outcome: str) -> None:
    run = RunIdentity(source_instance_id="source", execution_id="run")
    identity = QualifiedSessionIdentity(
        kind="transcript", source_instance_id="source", harness="codex", local_id="native"
    )
    capture = CataloguedCapture(
        run=run,
        producer_id="producer",
        capture_id="capture",
        harness="codex",
        native_id="native",
        content_format="native",
        archive=ArchivedTranscript(sha256="a" * 64, size=5),
    )
    catalog, archive, access = AsyncMock(), AsyncMock(), AsyncMock()
    catalog.get_revision.return_value = None if outcome == "not_captured" else capture
    archive.get.return_value = None if outcome in ("missing", "expired") else b"exact"
    archive.is_deleted.return_value = outcome == "expired"
    order: list[str] = []

    async def authorize(value: CataloguedCapture) -> None:
        assert value == capture
        order.append("authorize")
        if outcome == "denied":
            raise PermissionError("whole revision withheld")

    async def read(value: ArchivedTranscript) -> bytes | None:
        assert value == capture.archive
        assert order == ["authorize"]
        order.append("read")
        if outcome == "unavailable":
            raise OSError("archive unavailable")
        return None if outcome in ("missing", "expired") else b"exact"

    access.require_read.side_effect = authorize
    archive.get.side_effect = read
    handler = ReadLocalTranscriptHandler(
        catalog, archive, access, max_bytes=4 if outcome == "too_large" else 5
    )
    if outcome in ("denied", "unavailable"):
        with pytest.raises(PermissionError if outcome == "denied" else OSError):
            await handler.handle(run, identity, "a" * 64)
    else:
        result = await handler.handle(run, identity, "a" * 64)
        assert result.status == outcome
        assert result.body == (b"exact" if outcome == "present" else None)
        assert "exact" not in repr(result)
    catalog.get_revision.assert_awaited_once_with(run, identity, "a" * 64)
    if outcome in ("denied", "not_captured", "too_large"):
        archive.get.assert_not_awaited()
        archive.is_deleted.assert_not_awaited()
    if outcome == "not_captured":
        access.require_read.assert_not_awaited()
