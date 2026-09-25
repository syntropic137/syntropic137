"""One exporter outbox per capture, so a deletion can discard queued bytes.

The standard exporter's outbox cannot cancel a queued upload. Syntropic137 owns
the directory it points each exporter invocation at, so it gives every capture
its own directory. Discarding a capture's queued upload is removing that whole
directory; Syntropic137 never reads or edits the exporter's files inside it.
Deletion discards under the exclusive fence; enqueue and drain run under the
shared fence, so no queued copy of withdrawn bytes survives a deletion and no
send of them starts after one.

The pre-1398 shared outbox mixed captures and cannot be partially cancelled. It
is never drained again: ``retire_legacy`` removes it after its undelivered
captures are reset for redelivery through per-capture outboxes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from typing import TYPE_CHECKING, Protocol

from .exporter_transport import ExporterCaptureTransport, ExporterConfig

if TYPE_CHECKING:
    from pathlib import Path

    from apss_session_capture.inventory import QualifiedTranscript
    from pydantic import SecretStr

    from .exporter_transport import CaptureDrain, EnqueueReceipt, ExporterCaptureReceipt


class CaptureUploadTransport(Protocol):
    async def content_hash(self, envelope: bytes) -> str: ...
    async def enqueue(self, identity: QualifiedTranscript, envelope: bytes) -> EnqueueReceipt: ...
    async def receipt(
        self, identity: QualifiedTranscript, envelope: bytes
    ) -> ExporterCaptureReceipt | None: ...
    async def drain(self, limit: int = 1) -> CaptureDrain: ...


class CaptureOutboxPort(Protocol):
    def for_capture(self, producer_id: str, capture_id: str) -> CaptureUploadTransport: ...
    async def discard(self, producer_id: str, capture_id: str) -> None: ...
    async def retire_legacy(self) -> None: ...


def capture_outbox_key(producer_id: str, capture_id: str) -> str:
    """Server-derived directory name; never a caller- or harness-supplied path."""
    encoded = json.dumps(["capture-outbox/1", producer_id, capture_id], separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class ExporterCaptureOutboxes:
    def __init__(
        self,
        *,
        binary: Path,
        root: Path,
        legacy_root: Path,
        store_url: str,
        token: SecretStr,
    ) -> None:
        if not root.is_absolute() or not legacy_root.is_absolute():
            raise ValueError("capture outbox roots must be absolute")
        self._binary, self._root, self._legacy = binary, root, legacy_root
        self._url, self._token = store_url, token

    def _dir(self, producer_id: str, capture_id: str) -> Path:
        return self._root / capture_outbox_key(producer_id, capture_id)

    def for_capture(self, producer_id: str, capture_id: str) -> ExporterCaptureTransport:
        return ExporterCaptureTransport(
            ExporterConfig(
                binary=self._binary,
                outbox_dir=self._dir(producer_id, capture_id),
                store_url=self._url,
                token=self._token,
            )
        )

    async def discard(self, producer_id: str, capture_id: str) -> None:
        await asyncio.to_thread(shutil.rmtree, self._dir(producer_id, capture_id), True)

    async def retire_legacy(self) -> None:
        await asyncio.to_thread(shutil.rmtree, self._legacy, True)
