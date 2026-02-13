"""Tests for evaluate_webhook slice."""

from __future__ import annotations

import pytest

from aef_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from aef_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from aef_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
    _resolve_field,
    evaluate_conditions,
)
from aef_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
)
from aef_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
    SafetyGuards,
    _extract_pr_number,
)
from aef_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)
from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
    InMemoryTriggerQueryStore,
)

# --- Condition evaluator tests ---


@pytest.mark.unit
class TestConditionEvaluator:
    """Tests for condition evaluation."""

    def test_eq_operator_match(self) -> None:
        """Test eq operator matches."""
        conditions = [TriggerCondition("action", "eq", "completed")]
        assert evaluate_conditions(conditions, {"action": "completed"}) is True

    def test_eq_operator_no_match(self) -> None:
        """Test eq operator does not match."""
        conditions = [TriggerCondition("action", "eq", "completed")]
        assert evaluate_conditions(conditions, {"action": "started"}) is False

    def test_neq_operator(self) -> None:
        """Test neq operator."""
        conditions = [TriggerCondition("action", "neq", "pending")]
        assert evaluate_conditions(conditions, {"action": "completed"}) is True
        assert evaluate_conditions(conditions, {"action": "pending"}) is False

    def test_not_empty_operator(self) -> None:
        """Test not_empty operator."""
        conditions = [TriggerCondition("items", "not_empty")]
        assert evaluate_conditions(conditions, {"items": [1, 2]}) is True
        assert evaluate_conditions(conditions, {"items": []}) is False
        assert evaluate_conditions(conditions, {"items": None}) is False

    def test_is_empty_operator(self) -> None:
        """Test is_empty operator."""
        conditions = [TriggerCondition("items", "is_empty")]
        assert evaluate_conditions(conditions, {"items": []}) is True
        assert evaluate_conditions(conditions, {"items": [1]}) is False

    def test_in_operator(self) -> None:
        """Test in operator."""
        conditions = [TriggerCondition("state", "in", ["failure", "error"])]
        assert evaluate_conditions(conditions, {"state": "failure"}) is True
        assert evaluate_conditions(conditions, {"state": "success"}) is False

    def test_not_in_operator(self) -> None:
        """Test not_in operator."""
        conditions = [TriggerCondition("state", "not_in", ["success", "pending"])]
        assert evaluate_conditions(conditions, {"state": "failure"}) is True
        assert evaluate_conditions(conditions, {"state": "success"}) is False

    def test_contains_operator(self) -> None:
        """Test contains operator."""
        conditions = [TriggerCondition("message", "contains", "error")]
        assert evaluate_conditions(conditions, {"message": "build error occurred"}) is True
        assert evaluate_conditions(conditions, {"message": "all good"}) is False

    def test_nested_field_resolution(self) -> None:
        """Test dot-notation field resolution."""
        payload = {
            "check_run": {
                "conclusion": "failure",
                "pull_requests": [{"number": 42}],
            }
        }
        conditions = [TriggerCondition("check_run.conclusion", "eq", "failure")]
        assert evaluate_conditions(conditions, payload) is True

    def test_missing_nested_field_returns_none(self) -> None:
        """Test that missing nested field resolves to None."""
        assert _resolve_field({"a": {"b": 1}}, "a.c") is None
        assert _resolve_field({}, "a.b.c") is None

    def test_all_conditions_must_pass(self) -> None:
        """Test that all conditions must pass (AND logic)."""
        conditions = [
            TriggerCondition("check_run.conclusion", "eq", "failure"),
            TriggerCondition("check_run.pull_requests", "not_empty"),
        ]
        # Both true
        payload = {"check_run": {"conclusion": "failure", "pull_requests": [{"number": 1}]}}
        assert evaluate_conditions(conditions, payload) is True

        # First true, second false
        payload = {"check_run": {"conclusion": "failure", "pull_requests": []}}
        assert evaluate_conditions(conditions, payload) is False


# --- Safety guards tests ---


@pytest.mark.unit
class TestSafetyGuards:
    """Tests for safety guards."""

    @pytest.mark.asyncio
    async def test_bot_sender_blocked(self) -> None:
        """Test that bot senders are blocked."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = await handler.handle(cmd)

        guards = SafetyGuards()
        result = await guards.check_all(agg, {"sender": {"login": "aef-engineer-beta[bot]"}}, store)
        assert result.passed is False
        assert "bot" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_human_sender_allowed(self) -> None:
        """Test that human senders pass the bot check."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = await handler.handle(cmd)

        guards = SafetyGuards()
        result = await guards.check_all(agg, {"sender": {"login": "human-user"}}, store)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_max_attempts_reached(self) -> None:
        """Test that max attempts blocks the trigger."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
            config=(("max_attempts", 2),),
        )
        agg = await handler.handle(cmd)

        # Record 2 fires for PR #42
        await store.record_fire(agg.trigger_id, 42, "exec-1")
        await store.record_fire(agg.trigger_id, 42, "exec-2")

        guards = SafetyGuards()
        payload = {
            "sender": {"login": "human"},
            "pull_request": {"number": 42},
        }
        result = await guards.check_all(agg, payload, store)
        assert result.passed is False
        assert "Max attempts" in result.reason

    @pytest.mark.asyncio
    async def test_idempotency_blocks_duplicate_delivery(self) -> None:
        """Test that duplicate delivery IDs are blocked."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = await handler.handle(cmd)

        await store.record_delivery("del-123", agg.trigger_id)

        guards = SafetyGuards()
        payload = {
            "sender": {"login": "human"},
            "_delivery_id": "del-123",
        }
        result = await guards.check_all(agg, payload, store)
        assert result.passed is False
        assert "already processed" in result.reason

    def test_extract_pr_number_from_pull_request(self) -> None:
        """Test extracting PR number from pull_request payload."""
        assert _extract_pr_number({"pull_request": {"number": 42}}) == 42

    def test_extract_pr_number_from_check_run(self) -> None:
        """Test extracting PR number from check_run payload."""
        payload = {"check_run": {"pull_requests": [{"number": 99}]}}
        assert _extract_pr_number(payload) == 99

    def test_extract_pr_number_missing(self) -> None:
        """Test that missing PR number returns None."""
        assert _extract_pr_number({}) is None


# --- Handler integration tests ---


@pytest.mark.unit
class TestEvaluateWebhookHandler:
    """Tests for EvaluateWebhookHandler."""

    @pytest.mark.asyncio
    async def test_matching_trigger_fires(self) -> None:
        """Test that a matching trigger fires and returns result."""
        store = InMemoryTriggerQueryStore()
        reg_handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        await reg_handler.handle(cmd)

        handler = EvaluateWebhookHandler(store=store)
        payload = {
            "sender": {"login": "human-user"},
            "repository": {"full_name": "org/repo"},
            "check_run": {
                "conclusion": "failure",
                "pull_requests": [{"number": 1}],
            },
            "_delivery_id": "del-abc",
        }

        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert len(results) == 1
        assert results[0].execution_id.startswith("exec-")

    @pytest.mark.asyncio
    async def test_no_matching_rules_returns_empty(self) -> None:
        """Test that no matching rules returns empty list."""
        store = InMemoryTriggerQueryStore()
        handler = EvaluateWebhookHandler(store=store)

        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload={},
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_conditions_not_met_skips(self) -> None:
        """Test that conditions not met skips the trigger."""
        store = InMemoryTriggerQueryStore()
        reg_handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        await reg_handler.handle(cmd)

        handler = EvaluateWebhookHandler(store=store)
        payload = {
            "sender": {"login": "human"},
            "check_run": {"conclusion": "success"},
        }

        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_bot_sender_blocked_by_guard(self) -> None:
        """Test that bot senders are blocked by safety guard."""
        store = InMemoryTriggerQueryStore()
        reg_handler = RegisterTriggerHandler(store=store)
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        await reg_handler.handle(cmd)

        handler = EvaluateWebhookHandler(store=store)
        payload = {
            "sender": {"login": "aef-engineer[bot]"},
            "check_run": {"conclusion": "failure"},
        }

        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert results == []
