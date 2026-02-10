"""Evaluate Webhook handler.

Core dispatch logic: evaluates registered trigger rules against incoming webhooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aef_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
    evaluate_conditions,
)
from aef_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
    SafetyGuards,
)

if TYPE_CHECKING:
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerStore,
    )

logger = logging.getLogger(__name__)


@dataclass
class TriggerMatchResult:
    """Result of a trigger match and dispatch."""

    trigger_id: str
    execution_id: str


class EvaluateWebhookHandler:
    """Handler for evaluating webhooks against registered triggers.

    This is the core dispatch logic:
    1. Find all active trigger rules matching this event type + repository
    2. Evaluate conditions for each rule
    3. Run safety guards
    4. Record the trigger firing
    """

    def __init__(self, store: TriggerStore) -> None:
        """Initialize the handler.

        Args:
            store: Trigger storage backend.
        """
        self._store = store
        self._guards = SafetyGuards()

    async def evaluate(
        self,
        event: str,
        repository: str,
        installation_id: str,  # noqa: ARG002
        payload: dict[str, Any],
    ) -> list[TriggerMatchResult]:
        """Evaluate registered trigger rules against an incoming webhook.

        Args:
            event: Full event type (e.g. "check_run.completed").
            repository: Repository that received the webhook (owner/repo).
            installation_id: GitHub App installation ID.
            payload: The webhook payload dict.

        Returns:
            List of TriggerMatchResult for rules that fired.
        """
        # Find active rules matching this event + repo
        rules = await self._store.list_by_event_and_repo(event, repository)
        if not rules:
            logger.debug(f"No trigger rules for {event} on {repository}")
            return []

        results: list[TriggerMatchResult] = []

        for rule in rules:
            # Check if rule can fire (status check)
            if not rule.can_fire():
                continue

            # Evaluate conditions
            if not evaluate_conditions(rule.conditions, payload):
                logger.debug(f"Trigger {rule.trigger_id} conditions not met for {event}")
                continue

            # Run safety guards
            guard_result = await self._guards.check_all(rule, payload, self._store)
            if not guard_result.passed:
                logger.info(f"Trigger {rule.trigger_id} blocked by guard: {guard_result.reason}")
                continue

            # Generate execution ID and record the firing
            execution_id = f"exec-{uuid4().hex[:12]}"
            delivery_id = payload.get("_delivery_id", "")

            # Extract PR number for tracking
            from aef_domain.contexts.github.slices.evaluate_webhook.safety_guards import (
                _extract_pr_number,
            )

            pr_number = _extract_pr_number(payload)

            # Record in aggregate
            rule.record_fired(
                execution_id=execution_id,
                webhook_delivery_id=delivery_id,
                event_type=event,
                repository=repository,
                pr_number=pr_number,
                payload_summary=_build_payload_summary(payload, event),
            )

            # Persist state
            await self._store.save(rule)

            # Record delivery for idempotency
            if delivery_id:
                await self._store.record_delivery(delivery_id, rule.trigger_id)

            # Record fire for tracking
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
                TriggerMatchResult(
                    trigger_id=rule.trigger_id,
                    execution_id=execution_id,
                )
            )

        return results


def _build_payload_summary(payload: dict[str, Any], event: str) -> dict:
    """Build a summary of key payload fields for the audit trail.

    Args:
        payload: The full webhook payload.
        event: The event type.

    Returns:
        Dict with key summary fields.
    """
    summary: dict[str, Any] = {"event": event}

    # Extract common fields
    sender = payload.get("sender", {})
    if sender:
        summary["sender"] = sender.get("login", "")

    repo = payload.get("repository", {})
    if repo:
        summary["repository"] = repo.get("full_name", "")

    # Event-specific fields
    if "check_run" in event:
        check_run = payload.get("check_run", {})
        summary["check_name"] = check_run.get("name", "")
        summary["conclusion"] = check_run.get("conclusion", "")
    elif "pull_request_review" in event:
        review = payload.get("review", {})
        summary["review_state"] = review.get("state", "")
        summary["reviewer"] = review.get("user", {}).get("login", "")

    return summary
