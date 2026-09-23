"""Drain one bounded spool page. Durable acknowledgements precede cursor advance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentic_isolation.harnesses import harness_for_exporter_agent

from syn_domain.contexts.agent_sessions import LocalTranscriptCapture, TranscriptDeletedError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agentic_isolation.session_spool import WorkspaceSpoolReader

    from syn_domain.contexts.agent_sessions import CaptureLocalTranscriptHandler, RunIdentity


@dataclass(frozen=True)
class SpoolDrainProgress:
    watermark: int
    next_after: int | None
    captured: int
    deleted: int = 0


class LocalSpoolDrain:
    def __init__(self, capture: CaptureLocalTranscriptHandler, *, max_captures: int = 50) -> None:
        if not 1 <= max_captures <= 500:
            raise ValueError("Capture page limit must be between 1 and 500")
        self._capture = capture
        self._max_captures = max_captures

    async def page(
        self,
        reader: WorkspaceSpoolReader,
        *,
        run: RunIdentity,
        spool_id: str,
        after: int = 0,
        watermark: int | None = None,
        renew: Callable[[], Awaitable[None]] | None = None,
    ) -> SpoolDrainProgress:
        if not spool_id.strip():
            raise ValueError("A host-assigned durable spool identity is required")
        page = await reader.page(after, watermark)
        producer = "spool:" + hashlib.sha256(spool_id.encode()).hexdigest()
        entries = page.entries[: self._max_captures]
        deleted = 0
        for entry in entries:
            if renew is not None:
                await renew()
            body = await reader.read(entry)
            harness = harness_for_exporter_agent(entry.agent)
            key = json.dumps(
                [
                    run.source_instance_id,
                    run.execution_id,
                    spool_id,
                    entry.sequence,
                    entry.archive_sha256,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            # Durable deletion wins over replay from retained workspace spools.
            try:
                await self._capture.handle(
                    LocalTranscriptCapture(
                        run=run,
                        capture_id=hashlib.sha256(key.encode()).hexdigest(),
                        producer_id=producer,
                        harness=harness.value
                        if harness is not None
                        else f"unsupported:{entry.agent}",
                        receipt_sequence=entry.sequence,
                        content=body,
                        content_format="envelope",
                    )
                )
            except TranscriptDeletedError:
                deleted += 1
        next_after = entries[-1].sequence if len(entries) < len(page.entries) else page.next_after
        return SpoolDrainProgress(page.watermark, next_after, len(entries) - deleted, deleted)
