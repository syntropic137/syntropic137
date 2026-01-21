"""Port interface for conversation log storage.

Per ADR-035 (Conversation Storage Architecture), full JSONL conversation logs
are stored in object storage (MinIO/S3) for debugging and replay.
"""

from typing import Protocol


class ConversationStoragePort(Protocol):
    """Port for storing full conversation logs in object storage.

    Per ADR-035, conversation logs are:
    - Stored as JSONL files in MinIO/S3
    - Organized by session_id: conversations/{session_id}.jsonl
    - Include full event stream from agent execution
    - Used for debugging, replay, and audit trail

    This complements the observability data in TimescaleDB by providing
    the full, raw conversation history.
    """

    async def store_session(
        self,
        session_id: str,
        lines: list[str],
        context: "SessionContext",
    ) -> None:
        """Store a full conversation log for a session.

        Args:
            session_id: The session ID (used as filename).
            lines: JSONL lines from the event stream (one event per line).
            context: Session metadata (execution_id, phase_id, model, tokens, etc.).

        Example:
            from aef_adapters.conversations import SessionContext

            context = SessionContext(
                execution_id="exec-123",
                phase_id="phase-456",
                workflow_id="workflow-789",
                model="claude-sonnet-4",
                event_count=len(conversation_lines),
                total_input_tokens=1500,
                total_output_tokens=300,
                started_at=phase_started_at,
                completed_at=datetime.now(UTC),
                success=True,
            )

            await conversation_storage.store_session(
                session_id="session-123",
                lines=conversation_lines,  # List of JSONL strings
                context=context,
            )
        """
        ...


