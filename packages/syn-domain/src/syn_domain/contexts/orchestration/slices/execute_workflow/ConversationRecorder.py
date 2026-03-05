"""Conversation recording helper for workflow execution.

Deduplicates the 3 nearly-identical conversation storage blocks
(success/failure/interrupt) into a single reusable method.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_adapters.conversations import ConversationStoragePort

logger = logging.getLogger(__name__)


class ConversationRecorder:
    """Stores conversation logs to object storage. No-ops if storage is None."""

    def __init__(self, storage: ConversationStoragePort | None) -> None:
        self._storage = storage

    async def store(
        self,
        session_id: str,
        lines: list[str],
        execution_id: str,
        phase_id: str,
        workflow_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        started_at: datetime,
        success: bool,
    ) -> None:
        """Store conversation log. No-op if storage is None or lines empty. Never raises."""
        if self._storage is None or not lines:
            return

        try:
            from syn_adapters.conversations import SessionContext

            context = SessionContext(
                execution_id=execution_id,
                phase_id=phase_id,
                workflow_id=workflow_id,
                model=model,
                event_count=len(lines),
                tool_counts={},
                total_input_tokens=input_tokens,
                total_output_tokens=output_tokens,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                success=success,
            )
            await self._storage.store_session(
                session_id=session_id,
                lines=lines,
                context=context,
            )
            logger.info(
                "Conversation log stored: %s (%d lines, success=%s)",
                session_id,
                len(lines),
                success,
            )
        except Exception as err:
            logger.warning(
                "Failed to store conversation log for %s: %s",
                session_id,
                err,
            )
