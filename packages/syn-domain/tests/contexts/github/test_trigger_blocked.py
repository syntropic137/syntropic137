"""Tests for trigger blocked observability (#578).

Tests cover:
- TriggerBlockedEvent domain event
- RecordTriggerBlockedCommand aggregate handler
- Concurrency guard (Guard 6)
- Safety guard guard_name field
- TriggerHistoryProjection handle_trigger_blocked
- EvaluateWebhookHandler blocked result flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from syn_domain.contexts.github._shared.trigger_evaluation_types import (
    TriggerBlockedResult,
    TriggerMatchResult,
)
from syn_domain.contexts.github._shared.trigger_query_store import (
    InMemoryTriggerQueryStore,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerConfig import (
    TriggerConfig,
)
from syn_domain.contexts.github.domain.events.TriggerBlockedEvent import (
    TriggerBlockedEvent,
)
from syn_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
    GuardResult,
    SafetyGuards,
    _check_concurrency,
    _extract_pr_number,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rule(
    trigger_id: str = "tr-abc123",
    event: str = "check_run.completed",
    repository: str = "owner/repo",
    workflow_id: str = "wf-1",
    config: TriggerConfig | None = None,
    status: str = "active",
) -> SimpleNamespace:
    """Create a lightweight rule-like object for testing."""
    return SimpleNamespace(
        trigger_id=trigger_id,
        event=event,
        repository=repository,
        workflow_id=workflow_id,
        config=config or TriggerConfig(),
        status=status,
        conditions=[],
        input_mapping={},
        installation_id="inst-1",
    )


def _make_payload(
    pr_number: int | None = 42,
    delivery_id: str = "delivery-1",
    event: str = "check_run.completed",
) -> dict:
    """Create a webhook payload for testing."""
    payload: dict = {"_delivery_id": delivery_id, "action": "completed"}
    if pr_number is not None:
        if "check_run" in event:
            payload["check_run"] = {
                "pull_requests": [{"number": pr_number}],
                "conclusion": "failure",
            }
        else:
            payload["pull_request"] = {"number": pr_number}
    return payload


# ---------------------------------------------------------------------------
# TriggerBlockedEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriggerBlockedEvent:
    def test_create_event(self) -> None:
        event = TriggerBlockedEvent(
            trigger_id="tr-abc",
            guard_name="max_attempts",
            reason="Max attempts (3) reached for PR #42",
            repository="owner/repo",
            pr_number=42,
        )
        assert event.trigger_id == "tr-abc"
        assert event.guard_name == "max_attempts"
        assert event.pr_number == 42

    def test_trigger_id_required(self) -> None:
        with pytest.raises(ValueError, match="trigger_id is required"):
            TriggerBlockedEvent(trigger_id="", guard_name="test")

    def test_guard_name_required(self) -> None:
        with pytest.raises(ValueError, match="guard_name is required"):
            TriggerBlockedEvent(trigger_id="tr-abc", guard_name="")

    def test_event_type(self) -> None:
        event = TriggerBlockedEvent(trigger_id="tr-abc", guard_name="concurrency")
        assert event.event_type == "github.TriggerBlocked"


# ---------------------------------------------------------------------------
# Concurrency Guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_no_running_execution_passes(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        result = await _check_concurrency(rule, 42, store)
        assert result is None  # No block

    @pytest.mark.asyncio
    async def test_running_execution_blocks(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        # Simulate a running execution
        await store.record_fire("tr-abc123", 42, "exec-running")
        result = await _check_concurrency(rule, 42, store)
        assert result is not None
        assert result.passed is False
        assert result.guard_name == "concurrency"
        assert "already running" in result.reason

    @pytest.mark.asyncio
    async def test_completed_execution_allows(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        await store.record_fire("tr-abc123", 42, "exec-done")
        await store.complete_execution("exec-done")
        result = await _check_concurrency(rule, 42, store)
        assert result is None  # No block

    @pytest.mark.asyncio
    async def test_different_pr_not_blocked(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        await store.record_fire("tr-abc123", 42, "exec-running")
        result = await _check_concurrency(rule, 99, store)
        assert result is None  # Different PR, not blocked

    @pytest.mark.asyncio
    async def test_none_pr_blocks_none_pr(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        await store.record_fire("tr-abc123", None, "exec-running")
        result = await _check_concurrency(rule, None, store)
        assert result is not None
        assert result.passed is False


# ---------------------------------------------------------------------------
# Guard guard_name field
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGuardName:
    @pytest.mark.asyncio
    async def test_max_attempts_guard_name(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule(config=TriggerConfig(max_attempts=1))
        await store.record_fire("tr-abc123", 42, "exec-1")
        await store.complete_execution("exec-1")
        guards = SafetyGuards()
        payload = _make_payload(pr_number=42)
        result = await guards.check_all(rule, payload, store)
        assert result.passed is False
        assert result.guard_name == "max_attempts"

    @pytest.mark.asyncio
    async def test_daily_limit_guard_name(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule(config=TriggerConfig(daily_limit=1, max_attempts=999))
        await store.record_fire("tr-abc123", 99, "exec-1")
        await store.complete_execution("exec-1")
        guards = SafetyGuards()
        payload = _make_payload(pr_number=42, delivery_id="new-delivery")
        result = await guards.check_all(rule, payload, store)
        assert result.passed is False
        assert result.guard_name == "daily_limit"

    @pytest.mark.asyncio
    async def test_idempotency_guard_name(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule(config=TriggerConfig(max_attempts=999, daily_limit=999))
        await store.record_delivery("delivery-1", "tr-abc123")
        guards = SafetyGuards()
        payload = _make_payload(pr_number=42, delivery_id="delivery-1")
        result = await guards.check_all(rule, payload, store)
        assert result.passed is False
        assert result.guard_name == "idempotency"

    @pytest.mark.asyncio
    async def test_concurrency_runs_first(self) -> None:
        """Concurrency guard should fire before other guards."""
        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        await store.record_fire("tr-abc123", 42, "exec-running")
        guards = SafetyGuards()
        payload = _make_payload(pr_number=42)
        result = await guards.check_all(rule, payload, store)
        assert result.passed is False
        assert result.guard_name == "concurrency"

    @pytest.mark.asyncio
    async def test_all_passed_has_empty_guard_name(self) -> None:
        store = InMemoryTriggerQueryStore()
        rule = _make_rule(config=TriggerConfig(max_attempts=999, daily_limit=999))
        guards = SafetyGuards()
        payload = _make_payload(pr_number=42)
        result = await guards.check_all(rule, payload, store)
        assert result.passed is True
        assert result.guard_name == ""


# ---------------------------------------------------------------------------
# TriggerHistoryProjection — handle_trigger_blocked
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriggerHistoryProjectionBlocked:
    @pytest.mark.asyncio
    async def test_handle_trigger_blocked(self) -> None:
        from syn_domain.contexts.github.slices.trigger_history.projection import (
            TriggerHistoryProjection,
        )

        mock_store = AsyncMock()
        projection = TriggerHistoryProjection(store=mock_store)

        event = SimpleNamespace(
            trigger_id="tr-abc",
            guard_name="concurrency",
            reason="Execution already running",
            webhook_delivery_id="del-1",
            github_event_type="check_run.completed",
            repository="owner/repo",
            pr_number=42,
            payload_summary={"event": "check_run.completed"},
        )

        entry = await projection.handle_trigger_blocked(event)

        assert entry.trigger_id == "tr-abc"
        assert entry.execution_id == ""
        assert entry.status == "blocked"
        assert entry.guard_name == "concurrency"
        assert entry.block_reason == "Execution already running"
        assert entry.pr_number == 42

        mock_store.save.assert_called_once()
        call_args = mock_store.save.call_args
        saved_data = call_args[0][2]
        assert saved_data["status"] == "blocked"
        assert saved_data["guard_name"] == "concurrency"


# ---------------------------------------------------------------------------
# EvaluateWebhookHandler — blocked results
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateWebhookHandlerBlocked:
    @pytest.mark.asyncio
    async def test_guard_block_returns_blocked_result(self) -> None:
        from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
            EvaluateWebhookHandler,
        )

        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        # Index the trigger
        await store.index_trigger(
            trigger_id=rule.trigger_id,
            name="test-trigger",
            event=rule.event,
            repository=rule.repository,
            workflow_id=rule.workflow_id,
            conditions=[],
            input_mapping={},
            config=rule.config,
            installation_id=rule.installation_id,
            created_by="test",
            status="active",
        )
        # Create a running execution to trigger concurrency guard
        await store.record_fire(rule.trigger_id, 42, "exec-running")

        # Mock the aggregate repository
        mock_repo = AsyncMock()
        mock_aggregate = AsyncMock()
        mock_repo.get_by_id.return_value = mock_aggregate

        handler = EvaluateWebhookHandler(store=store, repository=mock_repo)
        payload = _make_payload(pr_number=42, delivery_id="del-new")
        results = await handler.evaluate(
            event=rule.event,
            repository=rule.repository,
            installation_id="inst-1",
            payload=payload,
        )

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, TriggerBlockedResult)
        assert result.guard_name == "concurrency"

    @pytest.mark.asyncio
    async def test_conditions_not_met_returns_blocked_result(self) -> None:
        from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
            EvaluateWebhookHandler,
        )

        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        # Index with a condition that won't match
        await store.index_trigger(
            trigger_id=rule.trigger_id,
            name="test-trigger",
            event=rule.event,
            repository=rule.repository,
            workflow_id=rule.workflow_id,
            conditions=[{"field": "action", "operator": "eq", "value": "nonexistent"}],
            input_mapping={},
            config=rule.config,
            installation_id=rule.installation_id,
            created_by="test",
            status="active",
        )

        mock_repo = AsyncMock()
        mock_aggregate = AsyncMock()
        mock_repo.get_by_id.return_value = mock_aggregate

        handler = EvaluateWebhookHandler(store=store, repository=mock_repo)
        payload = _make_payload(pr_number=42)
        results = await handler.evaluate(
            event=rule.event,
            repository=rule.repository,
            installation_id="inst-1",
            payload=payload,
        )

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, TriggerBlockedResult)
        assert result.guard_name == "conditions_not_met"

    @pytest.mark.asyncio
    async def test_successful_fire_still_works(self) -> None:
        from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
            EvaluateWebhookHandler,
        )

        store = InMemoryTriggerQueryStore()
        rule = _make_rule()
        await store.index_trigger(
            trigger_id=rule.trigger_id,
            name="test-trigger",
            event=rule.event,
            repository=rule.repository,
            workflow_id=rule.workflow_id,
            conditions=[],
            input_mapping={},
            config=rule.config,
            installation_id=rule.installation_id,
            created_by="test",
            status="active",
        )

        mock_repo = AsyncMock()
        mock_aggregate = AsyncMock()
        mock_repo.get_by_id.return_value = mock_aggregate

        handler = EvaluateWebhookHandler(store=store, repository=mock_repo)
        payload = _make_payload(pr_number=42)
        results = await handler.evaluate(
            event=rule.event,
            repository=rule.repository,
            installation_id="inst-1",
            payload=payload,
        )

        assert len(results) == 1
        assert isinstance(results[0], TriggerMatchResult)
