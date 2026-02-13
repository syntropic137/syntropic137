"""Evaluate Webhook handler.

Core dispatch logic: evaluates registered trigger rules against incoming webhooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aef_domain.contexts.github.domain.commands.RecordTriggerFiredCommand import (
    RecordTriggerFiredCommand,
)
from aef_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
    evaluate_conditions,
    extract_inputs,
)
from aef_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
    SafetyGuards,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerQueryStore,
    )

logger = logging.getLogger(__name__)


@dataclass
class TriggerMatchResult:
    trigger_id: str
    execution_id: str


class EvaluateWebhookHandler:
    def __init__(
        self,
        store: TriggerQueryStore,
        repository: Any | None = None,
    ) -> None:
        self._store = store
        self._repository = repository
        self._guards = SafetyGuards()

    async def evaluate(
        self,
        event: str,
        repository: str,
        installation_id: str,  # noqa: ARG002
        payload: dict[str, Any],
    ) -> list[TriggerMatchResult]:
        rules = await self._store.list_by_event_and_repo(event, repository)
        if not rules:
            logger.debug(f"No trigger rules for {event} on {repository}")
            return []

        results: list[TriggerMatchResult] = []
        for rule in rules:
            if rule.status != "active":
                continue

            if not evaluate_conditions(rule.conditions, payload):
                logger.debug(f"Trigger {rule.trigger_id} conditions not met for {event}")
                continue

            guard_result = await self._guards.check_all(rule, payload, self._store)
            if not guard_result.passed:
                logger.info(f"Trigger {rule.trigger_id} blocked by guard: {guard_result.reason}")
                continue

            execution_id = f"exec-{uuid4().hex[:12]}"
            delivery_id = payload.get("_delivery_id", "")
            from aef_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
                _extract_pr_number,
            )

            pr_number = _extract_pr_number(payload)

            # Extract workflow inputs from payload
            workflow_inputs = extract_inputs(payload, rule.input_mapping)

            # Record the firing via command on the aggregate
            if self._repository is not None:
                aggregate: TriggerRuleAggregate | None = await self._repository.get_by_id(
                    rule.trigger_id
                )
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

            if delivery_id:
                await self._store.record_delivery(delivery_id, rule.trigger_id)
            await self._store.record_fire(
                trigger_id=rule.trigger_id,
                pr_number=pr_number,
                execution_id=execution_id,
            )

            logger.info(
                f"Trigger {rule.trigger_id} fired for {event} on {repository} "
                f"-> execution {execution_id}"
            )
            results.append(
                TriggerMatchResult(trigger_id=rule.trigger_id, execution_id=execution_id)
            )
        return results


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
    return summary
