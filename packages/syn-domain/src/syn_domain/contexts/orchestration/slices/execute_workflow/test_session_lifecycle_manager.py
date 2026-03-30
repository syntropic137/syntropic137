"""Tests for SessionLifecycleManager."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.orchestration.slices.execute_workflow.SessionLifecycleManager import (
    SessionLifecycleManager,
)


def _make_manager(
    repo: AsyncMock | None = None,
) -> SessionLifecycleManager:
    if repo is None:
        repo = AsyncMock()
    return SessionLifecycleManager(
        repository=repo,
        session_id="sess-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        phase_id="phase-1",
        agent_provider="claude",
        agent_model="claude-sonnet-4-20250514",
    )


class TestStart:
    @pytest.mark.asyncio
    async def test_creates_and_saves_session(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)

        await mgr.start()

        assert mgr.session is not None
        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_when_repo_is_none(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )

        await mgr.start()

        assert mgr.session is None


class TestCompleteSuccess:
    @pytest.mark.asyncio
    async def test_records_tokens_and_completes(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.reset_mock()

        await mgr.complete_success(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            duration_seconds=1.5,
            source="test",
        )

        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_session_aggregate_receives_authoritative_tokens(self) -> None:
        """Regression: session must reflect authoritative CLI result tokens.

        Per-turn assistant events may report input_tokens=0 (cache hits),
        but the CLI result event has the true totals. The processor must
        pass those authoritative values through to session completion.
        See: ISS-405 / hotfix-403.
        """
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()

        # Authoritative values from CLI result event (includes cache tokens)
        await mgr.complete_success(
            input_tokens=6939,
            output_tokens=517,
            total_tokens=7456,
            duration_seconds=303.0,
            source="processor",
        )

        session = mgr.session
        assert session is not None
        # The aggregate should have the authoritative values, not zeros
        assert session._tokens.input_tokens == 6939
        assert session._tokens.output_tokens == 517
        assert session._tokens.total_tokens == 7456

    @pytest.mark.asyncio
    async def test_skips_token_recording_when_zero(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()

        await mgr.complete_success(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            duration_seconds=0.0,
            source="test",
        )

        # Should still complete session (save called for start + complete)
        assert repo.save.await_count == 2

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )

        # Should not raise
        await mgr.complete_success(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            duration_seconds=1.0,
            source="test",
        )


class TestCompleteFailure:
    @pytest.mark.asyncio
    async def test_completes_with_error(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.reset_mock()

        await mgr.complete_failure(error_message="something broke")

        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_secondary_errors(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.side_effect = RuntimeError("db down")

        # Should not raise
        await mgr.complete_failure(error_message="original error")

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )
        await mgr.complete_failure(error_message="err")


class TestCompleteCancelled:
    @pytest.mark.asyncio
    async def test_completes_as_cancelled(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.reset_mock()

        await mgr.complete_cancelled(reason="user interrupt")

        repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_secondary_errors(self) -> None:
        repo = AsyncMock()
        mgr = _make_manager(repo)
        await mgr.start()
        repo.save.side_effect = RuntimeError("db down")

        # Should not raise
        await mgr.complete_cancelled(reason="interrupted")

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        mgr = SessionLifecycleManager(
            repository=None,
            session_id="s",
            workflow_id="w",
            execution_id="e",
            phase_id="p",
            agent_provider="claude",
            agent_model="m",
        )
        await mgr.complete_cancelled(reason="cancelled")
