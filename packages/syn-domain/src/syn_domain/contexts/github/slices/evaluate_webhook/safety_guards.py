"""Safety guards for trigger evaluation.

Evaluates safety constraints before firing a trigger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import (
        TriggerQueryStore,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guard policy constants — centralised here for visibility and tuning.
# ---------------------------------------------------------------------------

# Extra seconds added when scheduling a retry after a cooldown/cross-trigger
# block. Gives a buffer so the retry doesn't land right on the boundary.
RETRY_BUFFER_SECONDS: float = 5

# Window (seconds) during which a fire from *any* trigger on the same PR
# blocks other triggers from firing (prevents concurrent workflows).
# NOTE: Disabled — cooldown is now per-trigger via guard #3 (repo+PR+trigger_id).
# Different trigger types (self-heal vs review-fix) should not block each other.
# See: https://github.com/syntropic137/syntropic137/issues/101
CROSS_TRIGGER_COOLDOWN_SECONDS: float = 0


@dataclass
class GuardResult:
    """Result of a safety guard check."""

    passed: bool
    reason: str
    retryable: bool = False
    retry_after_seconds: float = 0


class SafetyGuards:
    """Evaluate safety constraints before firing a trigger."""

    async def check_all(
        self,
        rule: Any,
        payload: dict[str, Any],
        store: TriggerQueryStore,
    ) -> GuardResult:
        """Run all safety checks. Returns first failure or success.

        Args:
            rule: The trigger rule to check.
            payload: The webhook payload.
            store: Trigger store for querying fire history.

        Returns:
            GuardResult with passed=True if all guards pass.
        """
        # 1. Max attempts per PR + trigger combo
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

        # 2. Cooldown - min time since last fire for same PR
        if pr_number is not None and rule.config.cooldown_seconds > 0:
            last_fired = await store.get_last_fired_at(
                trigger_id=rule.trigger_id,
                pr_number=pr_number,
            )
            if last_fired:
                elapsed = (datetime.now(UTC) - last_fired).total_seconds()
                if elapsed < rule.config.cooldown_seconds:
                    remaining = rule.config.cooldown_seconds - elapsed
                    return GuardResult(
                        False,
                        f"Cooldown: {remaining:.0f}s remaining",
                        retryable=True,
                        retry_after_seconds=remaining + RETRY_BUFFER_SECONDS,
                    )

        # 3. Daily limit
        today_count = await store.get_daily_fire_count(rule.trigger_id)
        if today_count >= rule.config.daily_limit:
            return GuardResult(False, f"Daily limit ({rule.config.daily_limit}) reached")

        # 4. Idempotency - don't fire twice for same delivery
        delivery_id = payload.get("_delivery_id", "")
        if delivery_id:
            already_processed = await store.was_delivery_processed(delivery_id)
            if already_processed:
                return GuardResult(False, f"Delivery {delivery_id} already processed")

        # 5. Cross-trigger PR cooldown — prevent concurrent workflows on same PR
        if pr_number is not None:
            last_any = await store.get_last_any_fired_at(
                pr_number, exclude_trigger_id=rule.trigger_id
            )
            if last_any:
                elapsed = (datetime.now(UTC) - last_any).total_seconds()
                if elapsed < CROSS_TRIGGER_COOLDOWN_SECONDS:
                    return GuardResult(
                        False,
                        f"Another trigger fired on PR #{pr_number} {elapsed:.0f}s ago",
                        retryable=True,
                        retry_after_seconds=(CROSS_TRIGGER_COOLDOWN_SECONDS - elapsed)
                        + RETRY_BUFFER_SECONDS,
                    )

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
