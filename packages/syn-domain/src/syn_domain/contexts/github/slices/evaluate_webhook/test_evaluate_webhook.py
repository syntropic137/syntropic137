"""Tests for evaluate_webhook slice."""

from __future__ import annotations

import pytest

from syn_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from syn_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
    _resolve_field,
    evaluate_conditions,
)
from syn_domain.contexts.github.slices.evaluate_webhook.debouncer import (
    TriggerDebouncer,
)
from syn_domain.contexts.github.slices.evaluate_webhook.EvaluateWebhookHandler import (
    EvaluateWebhookHandler,
    TriggerDeferredResult,
    TriggerMatchResult,
)
from syn_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
    SafetyGuards,
    _extract_pr_number,
)
from syn_domain.contexts.github.slices.register_trigger.RegisterTriggerHandler import (
    RegisterTriggerHandler,
)
from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
    InMemoryTriggerQueryStore,
)


class NullRepository:
    """No-op repository for tests that don't need persistence."""

    async def get_by_id(self, id):
        return None

    async def save(self, aggregate):
        pass


async def _index_aggregate(store: InMemoryTriggerQueryStore, aggregate) -> None:
    """Manually index an aggregate in the query store (simulates projection)."""
    await store.index_trigger(
        trigger_id=aggregate.trigger_id,
        name=aggregate.name,
        event=aggregate.event,
        repository=aggregate.repository,
        workflow_id=aggregate.workflow_id,
        conditions=[
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in aggregate.conditions
        ],
        input_mapping=aggregate.input_mapping,
        config=aggregate.config,
        installation_id=aggregate.installation_id,
        created_by=aggregate.created_by,
        status=aggregate.status.value,
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
        handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = await handler.handle(cmd)
        await _index_aggregate(store, agg)

        guards = SafetyGuards()
        result = await guards.check_all(agg, {"sender": {"login": "syn-engineer-beta[bot]"}}, store)
        assert result.passed is False
        assert "bot" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_human_sender_allowed(self) -> None:
        """Test that human senders pass the bot check."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = await handler.handle(cmd)
        await _index_aggregate(store, agg)

        guards = SafetyGuards()
        result = await guards.check_all(agg, {"sender": {"login": "human-user"}}, store)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_max_attempts_reached(self) -> None:
        """Test that max attempts blocks the trigger."""
        store = InMemoryTriggerQueryStore()
        handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
            config=(("max_attempts", 2),),
        )
        agg = await handler.handle(cmd)
        await _index_aggregate(store, agg)

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
        handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = await handler.handle(cmd)
        await _index_aggregate(store, agg)

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
        reg_handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        agg = await reg_handler.handle(cmd)
        await _index_aggregate(store, agg)

        handler = EvaluateWebhookHandler(store=store, repository=NullRepository())
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
        handler = EvaluateWebhookHandler(store=store, repository=NullRepository())

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
        reg_handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        agg = await reg_handler.handle(cmd)
        await _index_aggregate(store, agg)

        handler = EvaluateWebhookHandler(store=store, repository=NullRepository())
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
        reg_handler = RegisterTriggerHandler(store=store, repository=NullRepository())
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        agg = await reg_handler.handle(cmd)
        await _index_aggregate(store, agg)

        handler = EvaluateWebhookHandler(store=store, repository=NullRepository())
        payload = {
            "sender": {"login": "syn-engineer[bot]"},
            "check_run": {"conclusion": "failure"},
        }

        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert results == []


# --- Debounce and retry tests ---


def _make_payload(pr_number: int = 1, delivery_id: str = "del-1") -> dict:
    """Helper to build a matching check_run failure payload."""
    return {
        "sender": {"login": "human-user"},
        "repository": {"full_name": "org/repo"},
        "check_run": {
            "conclusion": "failure",
            "pull_requests": [{"number": pr_number}],
        },
        "_delivery_id": delivery_id,
    }


async def _register_trigger(
    store: InMemoryTriggerQueryStore,
    *,
    debounce_seconds: int = 0,
    cooldown_seconds: int = 300,
) -> None:
    """Register a ci-heal trigger and index it in the store."""
    reg = RegisterTriggerHandler(store=store, repository=NullRepository())
    cmd = RegisterTriggerCommand(
        name="ci-heal",
        event="check_run.completed",
        conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        repository="org/repo",
        workflow_id="ci-fix-workflow",
        config=(
            ("debounce_seconds", debounce_seconds),
            ("cooldown_seconds", cooldown_seconds),
        ),
    )
    agg = await reg.handle(cmd)
    await _index_aggregate(store, agg)


@pytest.mark.unit
class TestDebounceAndRetry:
    """Tests for debounce and cooldown-retry integration."""

    @pytest.mark.asyncio
    async def test_debounce_defers_when_configured(self) -> None:
        """debounce_seconds > 0 + debouncer → TriggerDeferredResult."""
        store = InMemoryTriggerQueryStore()
        debouncer = TriggerDebouncer()
        await _register_trigger(store, debounce_seconds=60)

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), debouncer=debouncer
        )
        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_make_payload(),
        )

        assert len(results) == 1
        assert isinstance(results[0], TriggerDeferredResult)
        assert results[0].defer_seconds == 60
        assert debouncer.pending_count == 1
        debouncer.cancel_all()

    @pytest.mark.asyncio
    async def test_no_debounce_without_debouncer(self) -> None:
        """No debouncer injected → fires immediately even with debounce_seconds > 0."""
        store = InMemoryTriggerQueryStore()
        await _register_trigger(store, debounce_seconds=60)

        handler = EvaluateWebhookHandler(store=store, repository=NullRepository(), debouncer=None)
        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_make_payload(),
        )

        assert len(results) == 1
        assert isinstance(results[0], TriggerMatchResult)
        assert results[0].execution_id.startswith("exec-")

    @pytest.mark.asyncio
    async def test_cooldown_blocked_schedules_retry(self) -> None:
        """Cooldown blocks + debouncer → TriggerDeferredResult with retry_after > 0."""
        store = InMemoryTriggerQueryStore()
        debouncer = TriggerDebouncer()
        await _register_trigger(store, cooldown_seconds=300)

        # Simulate a recent fire so cooldown blocks
        rules = await store.list_by_event_and_repo("check_run.completed", "org/repo")
        trigger_id = rules[0].trigger_id
        await store.record_fire(trigger_id, 1, "exec-old")

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), debouncer=debouncer
        )
        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_make_payload(),
        )

        assert len(results) == 1
        assert isinstance(results[0], TriggerDeferredResult)
        assert results[0].defer_seconds > 0
        assert debouncer.pending_count == 1
        debouncer.cancel_all()

    @pytest.mark.asyncio
    async def test_permanent_guard_does_not_retry(self) -> None:
        """Bot guard blocks → no retry scheduled, pending_count == 0."""
        store = InMemoryTriggerQueryStore()
        debouncer = TriggerDebouncer()
        await _register_trigger(store)

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), debouncer=debouncer
        )
        payload = _make_payload()
        payload["sender"] = {"login": "syn-engineer[bot]"}

        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=payload,
        )

        assert results == []
        assert debouncer.pending_count == 0
        debouncer.cancel_all()

    @pytest.mark.asyncio
    async def test_debounce_last_write_wins(self) -> None:
        """3 rapid events → only 1 pending timer (previous 2 cancelled)."""
        store = InMemoryTriggerQueryStore()
        debouncer = TriggerDebouncer()
        await _register_trigger(store, debounce_seconds=60)

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), debouncer=debouncer
        )

        for i in range(3):
            await handler.evaluate(
                event="check_run.completed",
                repository="org/repo",
                installation_id="inst-1",
                payload=_make_payload(delivery_id=f"del-{i}"),
            )

        assert debouncer.pending_count == 1
        debouncer.cancel_all()

    @pytest.mark.asyncio
    async def test_cooldown_guard_is_retryable(self) -> None:
        """GuardResult from cooldown has retryable=True and retry_after_seconds > 0."""
        store = InMemoryTriggerQueryStore()
        await _register_trigger(store, cooldown_seconds=300)

        rules = await store.list_by_event_and_repo("check_run.completed", "org/repo")
        rule = rules[0]
        await store.record_fire(rule.trigger_id, 1, "exec-old")

        guards = SafetyGuards()
        result = await guards.check_all(rule, _make_payload(), store)
        assert result.passed is False
        assert result.retryable is True
        assert result.retry_after_seconds > 0

    @pytest.mark.asyncio
    async def test_bot_guard_is_not_retryable(self) -> None:
        """GuardResult from bot guard has retryable=False (default)."""
        store = InMemoryTriggerQueryStore()
        await _register_trigger(store)

        rules = await store.list_by_event_and_repo("check_run.completed", "org/repo")
        rule = rules[0]

        guards = SafetyGuards()
        payload = _make_payload()
        payload["sender"] = {"login": "syn-engineer[bot]"}
        result = await guards.check_all(rule, payload, store)
        assert result.passed is False
        assert result.retryable is False
        assert result.retry_after_seconds == 0

    @pytest.mark.asyncio
    async def test_on_fire_callback_invoked_on_immediate_fire(self) -> None:
        """on_fire callback is called when a trigger fires immediately."""
        store = InMemoryTriggerQueryStore()
        await _register_trigger(store)

        fired_results: list[TriggerMatchResult] = []

        async def mock_on_fire(result: TriggerMatchResult, payload: dict) -> None:
            fired_results.append(result)

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), on_fire=mock_on_fire
        )
        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_make_payload(),
        )

        assert len(results) == 1
        assert isinstance(results[0], TriggerMatchResult)
        assert len(fired_results) == 1
        assert fired_results[0].trigger_id == results[0].trigger_id

    @pytest.mark.asyncio
    async def test_debounce_zero_fires_immediately_with_debouncer(self) -> None:
        """debounce_seconds=0 with debouncer present fires immediately."""
        store = InMemoryTriggerQueryStore()
        debouncer = TriggerDebouncer()
        await _register_trigger(store, debounce_seconds=0)

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), debouncer=debouncer
        )
        results = await handler.evaluate(
            event="check_run.completed",
            repository="org/repo",
            installation_id="inst-1",
            payload=_make_payload(),
        )

        assert len(results) == 1
        assert isinstance(results[0], TriggerMatchResult)
        assert debouncer.pending_count == 0
        debouncer.cancel_all()
