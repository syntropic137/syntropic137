"""Evaluate Webhook handler.

Core dispatch logic: evaluates registered trigger rules against incoming webhooks.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from syn_domain.contexts.github.domain.commands.RecordTriggerFiredCommand import (
    RecordTriggerFiredCommand,
)
from syn_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
    evaluate_conditions,
    extract_inputs,
)
from syn_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
    SafetyGuards,
    _extract_pr_number,
)

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import (
        TriggerQueryStore,
    )
    from syn_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )
    from syn_domain.contexts.github.slices.evaluate_webhook.debouncer import (
        TriggerDebouncer,
    )

logger = logging.getLogger(__name__)


@dataclass
class TriggerMatchResult:
    trigger_id: str
    execution_id: str


@dataclass
class TriggerDeferredResult:
    trigger_id: str
    reason: str
    defer_seconds: float


OnFireCallback = Callable[[Any, dict[str, Any]], Coroutine[Any, Any, None]]
"""Called when a trigger fires: (result: TriggerMatchResult, payload: dict)."""


class EvaluateWebhookHandler:
    def __init__(
        self,
        store: TriggerQueryStore,
        repository: Any,
        debouncer: TriggerDebouncer | None = None,
        on_fire: OnFireCallback | None = None,
    ) -> None:
        self._store = store
        self._repository = repository
        self._debouncer = debouncer
        self._on_fire = on_fire
        self._guards = SafetyGuards()

    async def evaluate(
        self,
        event: str,
        repository: str,
        installation_id: str,
        payload: dict[str, Any],
    ) -> list[TriggerMatchResult | TriggerDeferredResult]:
        rules = await self._store.list_by_event_and_repo(event, repository)
        if not rules:
            logger.debug(f"No trigger rules for {event} on {repository}")
            return []

        results: list[TriggerMatchResult | TriggerDeferredResult] = []
        for rule in rules:
            result = await self._evaluate_rule(rule, event, repository, installation_id, payload)
            if result is not None:
                results.append(result)
        return results

    async def _evaluate_rule(
        self,
        rule: Any,
        event: str,
        repository: str,
        installation_id: str,
        payload: dict[str, Any],
    ) -> TriggerMatchResult | TriggerDeferredResult | None:
        """Evaluate a single rule against the payload. Returns None if skipped."""
        if rule.status != "active":
            return None
        if not evaluate_conditions(rule.conditions, payload):
            logger.debug(f"Trigger {rule.trigger_id} conditions not met for {event}")
            return None

        guard_result = await self._guards.check_all(rule, payload, self._store)
        if not guard_result.passed:
            return await self._handle_guard_block(
                rule,
                guard_result,
                event,
                repository,
                installation_id,
                payload,
            )

        if rule.config.debounce_seconds > 0 and self._debouncer is not None:
            return await self._schedule_deferred(
                rule=rule,
                event=event,
                repository=repository,
                installation_id=installation_id,
                payload=payload,
                delay=rule.config.debounce_seconds,
                reason=f"Debouncing for {rule.config.debounce_seconds}s",
                key_suffix="",
            )

        return await self._fire_trigger(rule, event, repository, payload)

    async def _handle_guard_block(
        self,
        rule: Any,
        guard_result: Any,
        event: str,
        repository: str,
        installation_id: str,
        payload: dict[str, Any],
    ) -> TriggerDeferredResult | None:
        """Handle a guard block — schedule retry if retryable, otherwise log."""
        if guard_result.retryable and self._debouncer is not None:
            return await self._schedule_deferred(
                rule=rule,
                event=event,
                repository=repository,
                installation_id=installation_id,
                payload=payload,
                delay=guard_result.retry_after_seconds,
                reason=guard_result.reason,
                key_suffix=":retry",
            )
        logger.info(f"Trigger {rule.trigger_id} blocked by guard: {guard_result.reason}")
        return None

    async def _fire_trigger(
        self,
        rule: Any,
        event: str,
        repository: str,
        payload: dict[str, Any],
    ) -> TriggerMatchResult:
        """Execute a trigger firing: record command + return result."""
        execution_id = f"exec-{uuid4().hex[:12]}"
        delivery_id = payload.get("_delivery_id", "")
        pr_number = _extract_pr_number(payload)
        workflow_inputs = extract_inputs(payload, rule.input_mapping)

        aggregate: TriggerRuleAggregate | None = await self._repository.get_by_id(rule.trigger_id)
        if aggregate is not None:
            cmd = RecordTriggerFiredCommand(
                trigger_id=rule.trigger_id,
                execution_id=execution_id,
                webhook_delivery_id=delivery_id,
                event_type=event,
                repository=repository,
                workflow_id=rule.workflow_id,
                workflow_inputs=workflow_inputs,
                pr_number=pr_number,
                payload_summary=_build_payload_summary(payload, event),
            )
            aggregate.record_fired(cmd)
            await self._repository.save(aggregate)

        result = TriggerMatchResult(trigger_id=rule.trigger_id, execution_id=execution_id)
        logger.info(
            f"Trigger {rule.trigger_id} fired for {event} on {repository} "
            f"-> execution {execution_id}"
        )
        if self._on_fire is not None:
            await self._on_fire(result, payload)
        return result

    async def _schedule_deferred(
        self,
        rule: Any,
        event: str,
        repository: str,
        installation_id: str,
        payload: dict[str, Any],
        delay: float,
        reason: str,
        key_suffix: str,
    ) -> TriggerDeferredResult:
        """Schedule a deferred evaluation via the debouncer."""
        if self._debouncer is None:
            raise RuntimeError("_schedule_deferred called without debouncer")

        pr_number = _extract_pr_number(payload)
        key = rule.trigger_id
        if pr_number is not None:
            key = f"{key}:pr-{pr_number}"
        key = f"{key}{key_suffix}"

        # Deep-copy payload for last-write-wins semantics (nested dicts are shared refs otherwise)
        captured_payload = copy.deepcopy(payload)
        store = self._store
        repo = self._repository
        on_fire = self._on_fire

        async def _on_timer() -> None:
            # Re-evaluate without debouncer to prevent infinite loops
            handler = EvaluateWebhookHandler(
                store=store,
                repository=repo,
                debouncer=None,
                on_fire=on_fire,
            )
            await handler.evaluate(
                event=event,
                repository=repository,
                installation_id=installation_id,
                payload=captured_payload,
            )

        await self._debouncer.debounce(key, delay, _on_timer)
        logger.info(f"Trigger {rule.trigger_id} deferred ({reason}), key={key}, delay={delay:.0f}s")
        return TriggerDeferredResult(
            trigger_id=rule.trigger_id,
            reason=reason,
            defer_seconds=delay,
        )


def _build_payload_summary(payload: dict[str, Any], event: str) -> dict:
    summary: dict[str, Any] = {"event": event}
    sender = payload.get("sender", {})
    if sender:
        summary["sender"] = sender.get("login", "")
    repo = payload.get("repository", {})
    if repo:
        summary["repository"] = repo.get("full_name", "")
    if "check_run" in event:
        check_run = payload.get("check_run", {})
        summary["check_name"] = check_run.get("name", "")
        summary["conclusion"] = check_run.get("conclusion", "")
    elif "pull_request_review" in event:
        review = payload.get("review", {})
        summary["review_state"] = review.get("state", "")
        summary["reviewer"] = review.get("user", {}).get("login", "")
    elif "issue_comment" in event:
        comment = payload.get("comment", {})
        summary["comment_id"] = comment.get("id")
        summary["author"] = comment.get("user", {}).get("login", "")
        body = comment.get("body", "")
        summary["body_preview"] = body[:200] if body else ""
    return summary
