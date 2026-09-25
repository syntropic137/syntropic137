"""Tests for ConversationRecorder."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.ConversationRecorder import (
    ConversationRecorder,
)

if TYPE_CHECKING:
    from syn_adapters.conversations import SessionContext

pytestmark = pytest.mark.unit


class TestConversationRecorder:
    @pytest.mark.asyncio
    async def test_noop_when_no_storage(self) -> None:
        recorder = ConversationRecorder(None)
        # Should not raise
        await recorder.store(
            session_id="s1",
            lines=["line1"],
            execution_id="e1",
            phase_id="p1",
            workflow_id="w1",
            model="claude-opus-5-5",
            requested_model="opus",
            input_tokens=100,
            output_tokens=200,
            started_at=datetime.now(UTC),
            success=True,
        )

    @pytest.mark.asyncio
    async def test_noop_when_no_lines(self) -> None:
        recorder = ConversationRecorder(None)
        await recorder.store(
            session_id="s1",
            lines=[],
            execution_id="e1",
            phase_id="p1",
            workflow_id="w1",
            model="claude-opus-5-5",
            requested_model="opus",
            input_tokens=0,
            output_tokens=0,
            started_at=datetime.now(UTC),
            success=True,
        )

    @pytest.mark.asyncio
    async def test_stores_with_valid_storage(self) -> None:
        stored: list[tuple[str, list[str]]] = []
        contexts: list[SessionContext] = []

        class FakeStorage:
            async def store_session(
                self, session_id: str, lines: list[str], context: SessionContext
            ) -> str:
                stored.append((session_id, lines))
                contexts.append(context)
                return "key"

        recorder = ConversationRecorder(FakeStorage())  # type: ignore[arg-type]
        await recorder.store(
            session_id="s1",
            lines=["line1", "line2"],
            execution_id="e1",
            phase_id="p1",
            workflow_id="w1",
            model="claude-opus-5-5",
            requested_model="opus",
            input_tokens=100,
            output_tokens=200,
            started_at=datetime.now(UTC),
            success=True,
        )
        assert len(stored) == 1
        assert stored[0] == ("s1", ["line1", "line2"])
        # What ran and what was asked for travel apart (ADR-067).
        [context] = contexts
        assert context.model == "claude-opus-5-5"
        assert context.requested_model == "opus"

    @pytest.mark.asyncio
    async def test_never_raises_on_storage_error(self) -> None:
        class BrokenStorage:
            async def store_session(
                self, session_id: str, lines: list[str], context: object
            ) -> str:
                raise RuntimeError("storage down")

        recorder = ConversationRecorder(BrokenStorage())  # type: ignore[arg-type]
        # Should not raise
        await recorder.store(
            session_id="s1",
            lines=["line1"],
            execution_id="e1",
            phase_id="p1",
            workflow_id="w1",
            model="claude-opus-5-5",
            requested_model="opus",
            input_tokens=0,
            output_tokens=0,
            started_at=datetime.now(UTC),
            success=False,
        )
