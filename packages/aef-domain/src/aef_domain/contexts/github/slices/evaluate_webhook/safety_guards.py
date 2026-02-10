"""Safety guards for trigger evaluation.

Evaluates safety constraints before firing a trigger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aef_domain.contexts.github.domain.aggregate_trigger.TriggerRuleAggregate import (
        TriggerRuleAggregate,
    )
    from aef_domain.contexts.github.slices.register_trigger.trigger_store import (
        TriggerStore,
    )

logger = logging.getLogger(__name__)


@dataclass
class GuardResult:
    """Result of a safety guard check."""

    passed: bool
    reason: str


class SafetyGuards:
    """Evaluate safety constraints before firing a trigger."""

    async def check_all(
        self,
        rule: TriggerRuleAggregate,
        payload: dict[str, Any],
        store: TriggerStore,
    ) -> GuardResult:
        """Run all safety checks. Returns first failure or success.

        Args:
            rule: The trigger rule to check.
            payload: The webhook payload.
            store: Trigger store for querying fire history.

        Returns:
            GuardResult with passed=True if all guards pass.
        """
        # 1. Loop prevention - don't trigger on bot's own actions
        if rule.config.skip_if_sender_is_bot:
            sender = payload.get("sender", {}).get("login", "")
            if sender.endswith("[bot]"):
                return GuardResult(False, "Sender is a bot (loop prevention)")

        # 2. Max attempts per PR + trigger combo
        pr_number = _extract_pr_number(payload)
        if pr_number is not None:
            attempts = await store.get_fire_count(
                trigger_id=rule.trigger_id,
                pr_number=pr_number,
            )
            if attempts >= rule.config.max_attempts:
                return GuardResult(
                    False,
                    f"Max attempts ({rule.config.max_attempts}) reached for PR #{pr_number}",
                )

        # 3. Cooldown - min time since last fire for same PR
        if pr_number is not None and rule.config.cooldown_seconds > 0:
            last_fired = await store.get_last_fired_at(
                trigger_id=rule.trigger_id,
                pr_number=pr_number,
            )
            if last_fired:
                elapsed = (datetime.now(UTC) - last_fired).total_seconds()
                if elapsed < rule.config.cooldown_seconds:
                    remaining = rule.config.cooldown_seconds - elapsed
                    return GuardResult(False, f"Cooldown: {remaining:.0f}s remaining")

        # 4. Daily limit
        today_count = await store.get_daily_fire_count(rule.trigger_id)
        if today_count >= rule.config.daily_limit:
            return GuardResult(False, f"Daily limit ({rule.config.daily_limit}) reached")

        # 5. Idempotency - don't fire twice for same delivery
        delivery_id = payload.get("_delivery_id", "")
        if delivery_id:
            already_processed = await store.was_delivery_processed(delivery_id)
            if already_processed:
                return GuardResult(False, f"Delivery {delivery_id} already processed")

        return GuardResult(True, "All guards passed")


def _extract_pr_number(payload: dict[str, Any]) -> int | None:
    """Extract PR number from a webhook payload.

    Handles various payload shapes:
    - check_run.pull_requests[0].number
    - pull_request.number
    - issue.number (for PR-related issue events)

    Args:
        payload: The webhook payload.

    Returns:
        PR number if found, None otherwise.
    """
    # Direct PR events
    pr = payload.get("pull_request", {})
    if pr and pr.get("number"):
        return pr["number"]

    # Check run events
    check_run = payload.get("check_run", {})
    prs = check_run.get("pull_requests", [])
    if prs:
        return prs[0].get("number")

    # Review events
    review = payload.get("review", {})
    if review:
        pr = payload.get("pull_request", {})
        if pr and pr.get("number"):
            return pr["number"]

    return None
