"""Safety guards for trigger evaluation.

Evaluates safety constraints before firing a trigger.

See ADR-060: Restart-safe trigger deduplication (Guard 4 fix, Guard 7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_domain.contexts.github._shared.trigger_query_store import (
        TriggerQueryStore,
        _IndexedTrigger,
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
    guard_name: str = ""
    retryable: bool = False
    retry_after_seconds: float = 0


async def _check_max_attempts(
    rule: _IndexedTrigger,
    pr_number: int,
    store: TriggerQueryStore,
) -> GuardResult | None:
    """Guard 1: Max attempts per PR + trigger combo."""
    attempts = await store.get_fire_count(trigger_id=rule.trigger_id, pr_number=pr_number)
    if attempts >= rule.config.max_attempts:
        return GuardResult(
            False,
            f"Max attempts ({rule.config.max_attempts}) reached for PR #{pr_number}",
            guard_name="max_attempts",
        )
    return None


async def _check_cooldown(
    rule: _IndexedTrigger,
    pr_number: int,
    store: TriggerQueryStore,
) -> GuardResult | None:
    """Guard 2: Min time since last fire for same PR."""
    if rule.config.cooldown_seconds <= 0:
        return None
    last_fired = await store.get_last_fired_at(trigger_id=rule.trigger_id, pr_number=pr_number)
    if not last_fired:
        return None
    elapsed = (datetime.now(UTC) - last_fired).total_seconds()
    if elapsed < rule.config.cooldown_seconds:
        remaining = rule.config.cooldown_seconds - elapsed
        return GuardResult(
            False,
            f"Cooldown: {remaining:.0f}s remaining",
            guard_name="cooldown",
            retryable=True,
            retry_after_seconds=remaining + RETRY_BUFFER_SECONDS,
        )
    return None


async def _check_daily_limit(rule: _IndexedTrigger, store: TriggerQueryStore) -> GuardResult | None:
    """Guard 3: Daily fire limit."""
    today_count = await store.get_daily_fire_count(rule.trigger_id)
    if today_count >= rule.config.daily_limit:
        return GuardResult(
            False,
            f"Daily limit ({rule.config.daily_limit}) reached",
            guard_name="daily_limit",
        )
    return None


async def _check_idempotency(
    payload: dict[str, Any], store: TriggerQueryStore
) -> GuardResult | None:
    """Guard 4: Don't fire twice for same delivery.

    Uses ``_delivery_id`` (webhook) or ``_dedup_key`` (polled events) as the
    idempotency identifier. Before ADR-060, polled events had empty
    ``_delivery_id`` and silently bypassed this guard.
    """
    delivery_id = payload.get("_delivery_id", "") or payload.get("_dedup_key", "")
    if delivery_id and await store.was_delivery_processed(delivery_id):
        return GuardResult(
            False,
            f"Delivery {delivery_id} already processed",
            guard_name="idempotency",
        )
    return None


async def _check_cross_trigger_cooldown(
    rule: _IndexedTrigger,
    pr_number: int,
    store: TriggerQueryStore,
) -> GuardResult | None:
    """Guard 5: Cross-trigger PR cooldown."""
    last_any = await store.get_last_any_fired_at(pr_number, exclude_trigger_id=rule.trigger_id)
    if not last_any:
        return None
    elapsed = (datetime.now(UTC) - last_any).total_seconds()
    if elapsed < CROSS_TRIGGER_COOLDOWN_SECONDS:
        return GuardResult(
            False,
            f"Another trigger fired on PR #{pr_number} {elapsed:.0f}s ago",
            guard_name="cross_trigger_cooldown",
            retryable=True,
            retry_after_seconds=(CROSS_TRIGGER_COOLDOWN_SECONDS - elapsed) + RETRY_BUFFER_SECONDS,
        )
    return None


async def _check_concurrency(
    rule: _IndexedTrigger,
    pr_number: int | None,
    store: TriggerQueryStore,
) -> GuardResult | None:
    """Guard 6: Block if execution already running for same trigger+PR.

    Coalescing key: (trigger_id, pr_number). Prevents catch-up storms after
    restart — when the poller replays missed events, only one execution runs
    per trigger+PR at a time.

    Lifecycle: record_fire() → marks running, complete_execution() → clears.
    Cleared by TriggerHistoryAdapter on WorkflowCompleted/WorkflowFailed.
    In-memory only — resets on restart (correct: no containers survive).
    """
    if await store.has_running_execution(rule.trigger_id, pr_number):
        return GuardResult(
            False,
            f"Execution already running for trigger {rule.trigger_id}"
            + (f" on PR #{pr_number}" if pr_number is not None else ""),
            guard_name="concurrency",
        )
    return None


class SafetyGuards:
    """Evaluate safety constraints before firing a trigger.

    Guard 7 (ADR-060) uses an in-memory sliding window for global rate limiting.
    This is intentionally in-memory — it's a safety net, not the primary dedup
    mechanism. If it resets on restart, the durable layers (Postgres dedup,
    Guard 4) handle correctness.
    """

    def __init__(
        self,
        dispatch_rate_limit: int = 10,
        dispatch_rate_window_seconds: float = 60.0,
    ) -> None:
        self._dispatch_timestamps: list[float] = []
        self._dispatch_rate_limit = dispatch_rate_limit
        self._dispatch_rate_window = dispatch_rate_window_seconds

    async def check_all(
        self,
        rule: _IndexedTrigger,
        payload: dict[str, Any],
        store: TriggerQueryStore,
    ) -> GuardResult:
        """Run all safety checks. Returns first failure or success."""
        pr_number = _extract_pr_number(payload)

        for result in await self._run_guards(rule, payload, pr_number, store):
            if result is not None:
                return result

        return GuardResult(True, "All guards passed")

    async def _run_guards(
        self,
        rule: _IndexedTrigger,
        payload: dict[str, Any],
        pr_number: int | None,
        store: TriggerQueryStore,
    ) -> list[GuardResult | None]:
        """Evaluate guards in priority order. Short-circuit via caller."""
        guards: list[GuardResult | None] = [
            await _check_concurrency(rule, pr_number, store),
        ]

        if pr_number is not None:
            for check in (_check_max_attempts, _check_cooldown, _check_cross_trigger_cooldown):
                guards.append(await check(rule, pr_number, store))

        guards.append(await _check_daily_limit(rule, store))
        guards.append(await _check_idempotency(payload, store))
        guards.append(self._check_dispatch_rate())
        return guards

    def record_dispatch(self) -> None:
        """Record a successful dispatch timestamp for rate limiting."""
        if self._dispatch_rate_limit <= 0:
            return
        import time

        self._dispatch_timestamps.append(time.monotonic())

    def _check_dispatch_rate(self) -> GuardResult | None:
        """Guard 7: Global dispatch rate limit (ADR-060).

        Caps the number of workflow dispatches in a sliding window.
        Prevents runaway execution storms regardless of upstream failures.
        """
        import time

        if self._dispatch_rate_limit <= 0:
            return None

        now = time.monotonic()
        cutoff = now - self._dispatch_rate_window

        # Prune old timestamps
        self._dispatch_timestamps = [t for t in self._dispatch_timestamps if t > cutoff]

        if len(self._dispatch_timestamps) >= self._dispatch_rate_limit:
            return GuardResult(
                False,
                f"Global dispatch rate limit ({self._dispatch_rate_limit} per "
                f"{self._dispatch_rate_window:.0f}s) exceeded",
                guard_name="dispatch_rate_limit",
                retryable=True,
                retry_after_seconds=self._dispatch_rate_window / 2,
            )
        return None


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
