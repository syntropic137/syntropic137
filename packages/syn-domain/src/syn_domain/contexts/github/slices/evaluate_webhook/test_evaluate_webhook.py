"""Tests for evaluate_webhook slice."""

from __future__ import annotations

import pytest

from syn_domain.contexts.github._shared.trigger_query_store import (
    InMemoryTriggerQueryStore,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerCondition import (
    TriggerCondition,
)
from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
    TriggerRuleAggregate,
)
from syn_domain.contexts.github.domain.commands.RegisterTriggerCommand import (
    RegisterTriggerCommand,
)
from syn_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
    _check_operator,
    _coerce_bool,
    _coerce_to_list,
    _resolve_array_index,
    _resolve_field,
    _unpack_condition,
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
    async def test_max_attempts_reached(self) -> None:
        """Test that max attempts blocks the trigger."""
        store = InMemoryTriggerQueryStore()
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
            config=(("max_attempts", 2),),
        )
        agg = TriggerRuleAggregate()
        agg.register(cmd)
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
        cmd = RegisterTriggerCommand(
            name="test",
            event="check_run.completed",
            repository="org/repo",
            workflow_id="wf",
        )
        agg = TriggerRuleAggregate()
        agg.register(cmd)
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
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        agg = TriggerRuleAggregate()
        agg.register(cmd)
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
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        agg = TriggerRuleAggregate()
        agg.register(cmd)
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
    async def test_bot_sender_allowed(self) -> None:
        """Test that bot senders are allowed through (no blanket bot filter)."""
        store = InMemoryTriggerQueryStore()
        cmd = RegisterTriggerCommand(
            name="ci-heal",
            event="check_run.completed",
            conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
            repository="org/repo",
            workflow_id="ci-fix-workflow",
        )
        agg = TriggerRuleAggregate()
        agg.register(cmd)
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

        assert len(results) == 1


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
    max_attempts: int = 3,
    debounce_seconds: int = 0,
    cooldown_seconds: int = 300,
) -> None:
    """Register a ci-heal trigger and index it in the store."""
    cmd = RegisterTriggerCommand(
        name="ci-heal",
        event="check_run.completed",
        conditions=({"field": "check_run.conclusion", "operator": "eq", "value": "failure"},),
        repository="org/repo",
        workflow_id="ci-fix-workflow",
        config=(
            ("max_attempts", max_attempts),
            ("debounce_seconds", debounce_seconds),
            ("cooldown_seconds", cooldown_seconds),
        ),
    )
    agg = TriggerRuleAggregate()
    agg.register(cmd)
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
        """Max-attempts guard blocks → no retry scheduled, pending_count == 0."""
        store = InMemoryTriggerQueryStore()
        debouncer = TriggerDebouncer()
        await _register_trigger(store, max_attempts=1)

        rules = await store.list_by_event_and_repo("check_run.completed", "org/repo")
        rule = rules[0]
        await store.record_fire(rule.trigger_id, 1, "exec-old")

        handler = EvaluateWebhookHandler(
            store=store, repository=NullRepository(), debouncer=debouncer
        )
        payload = _make_payload()

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


@pytest.mark.unit
class TestExtractedHelpers:
    """Tests for helpers extracted for complexity reduction."""

    def test_check_operator_eq(self) -> None:
        assert _check_operator("eq", "foo", "foo") is True
        assert _check_operator("eq", "foo", "bar") is False

    def test_check_operator_neq(self) -> None:
        assert _check_operator("neq", "foo", "bar") is True
        assert _check_operator("neq", "foo", "foo") is False

    def test_check_operator_not_empty(self) -> None:
        assert _check_operator("not_empty", "value", None) is True
        assert _check_operator("not_empty", "", None) is False

    def test_check_operator_is_empty(self) -> None:
        assert _check_operator("is_empty", "", None) is True
        assert _check_operator("is_empty", "value", None) is False

    def test_check_operator_in(self) -> None:
        assert _check_operator("in", "a", ["a", "b"]) is True
        assert _check_operator("in", "c", ["a", "b"]) is False

    def test_check_operator_not_in(self) -> None:
        assert _check_operator("not_in", "c", ["a", "b"]) is True
        assert _check_operator("not_in", "a", ["a", "b"]) is False

    def test_check_operator_contains(self) -> None:
        assert _check_operator("contains", "hello world", "world") is True
        assert _check_operator("contains", "hello", "world") is False

    def test_check_operator_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown operator"):
            _check_operator("unknown_op", "a", "b")

    def test_eq_coerces_string_false_to_bool(self) -> None:
        """String 'false' from CLI must match resolved boolean False."""
        assert _check_operator("eq", False, "false") is True
        assert _check_operator("eq", True, "true") is True
        assert _check_operator("eq", True, "false") is False

    def test_in_coerces_comma_separated_string(self) -> None:
        """Comma-separated string 'a,b' from CLI must work as list for 'in'."""
        assert _check_operator("in", "commented", "changes_requested,commented") is True
        assert _check_operator("in", "approved", "changes_requested,commented") is False

    def test_coerce_bool_preserves_native_types(self) -> None:
        assert _coerce_bool(False) is False
        assert _coerce_bool(["a", "b"]) == ["a", "b"]
        assert _coerce_bool(42) == 42

    def test_coerce_bool_converts_strings(self) -> None:
        assert _coerce_bool("true") is True
        assert _coerce_bool("false") is False
        assert _coerce_bool(" False ") is False  # strip whitespace
        assert _coerce_bool("hello") == "hello"

    def test_coerce_to_list_handles_types(self) -> None:
        assert _coerce_to_list(["a", "b"]) == ["a", "b"]
        assert _coerce_to_list(None) == []
        assert _coerce_to_list("a,b") == ["a", "b"]
        assert _coerce_to_list("hello") == ["hello"]
        assert _coerce_to_list(True) == [True]

    def test_eq_does_not_split_commas(self) -> None:
        """eq operator should not split comma-containing strings into lists."""
        assert _check_operator("eq", "foo,bar", "foo,bar") is True
        assert _check_operator("eq", "foo", "foo,bar") is False

    def test_unpack_condition_dict(self) -> None:
        field, op, val = _unpack_condition({"field": "action", "operator": "eq", "value": "opened"})
        assert field == "action"
        assert op == "eq"
        assert val == "opened"

    def test_unpack_condition_typed(self) -> None:
        cond = TriggerCondition(field="action", operator="eq", value="closed")
        field, op, val = _unpack_condition(cond)
        assert field == "action"
        assert op == "eq"
        assert val == "closed"

    def test_resolve_array_index_valid(self) -> None:
        data = {"items": ["a", "b", "c"]}
        assert _resolve_array_index(data, "items", "1") == "b"

    def test_resolve_array_index_out_of_range(self) -> None:
        data = {"items": ["a"]}
        assert _resolve_array_index(data, "items", "5") is None

    def test_resolve_array_index_not_list(self) -> None:
        data = {"items": "not_a_list"}
        assert _resolve_array_index(data, "items", "0") is None

    def test_resolve_array_index_not_dict(self) -> None:
        assert _resolve_array_index("not_dict", "items", "0") is None
