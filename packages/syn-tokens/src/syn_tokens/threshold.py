"""Threshold monitoring for budget alerts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_tokens.models import SpendBudget

# Alert thresholds
DEFAULT_WARNING_PCT = 80
DEFAULT_CRITICAL_PCT = 95


@dataclass
class SpendAlert:
    """Alert for budget threshold breach."""

    execution_id: str
    workflow_type: str
    threshold: str  # "warning" or "critical"
    metric: str  # "input_tokens", "cost"
    usage_percent: float
    message: str


class ThresholdMonitor:
    """Pure-logic threshold checker for budget alerts."""

    def __init__(
        self,
        warning_pct: float = DEFAULT_WARNING_PCT,
        critical_pct: float = DEFAULT_CRITICAL_PCT,
    ) -> None:
        self._warning_pct = warning_pct
        self._critical_pct = critical_pct

    def check(self, budget: SpendBudget) -> list[SpendAlert]:
        """Check budget against thresholds and return alerts.

        Args:
            budget: Budget to check

        Returns:
            List of alerts (may be empty)
        """
        alerts: list[SpendAlert] = []

        # Check input token threshold
        self._check_metric(
            alerts,
            budget=budget,
            metric="input_tokens",
            usage_percent=budget.input_usage_percent,
        )

        # Check cost threshold
        self._check_metric(
            alerts,
            budget=budget,
            metric="cost",
            usage_percent=budget.cost_usage_percent,
            message_fmt_warning=f"Cost at {{pct:.1f}}% of budget (${budget.used_cost_usd:.2f})",
            message_fmt_critical=f"Cost at {{pct:.1f}}% of budget (${budget.used_cost_usd:.2f})",
        )

        return alerts

    def _check_metric(
        self,
        alerts: list[SpendAlert],
        *,
        budget: SpendBudget,
        metric: str,
        usage_percent: float,
        message_fmt_warning: str | None = None,
        message_fmt_critical: str | None = None,
    ) -> None:
        """Check a single metric against thresholds."""
        default_msg = f"{metric.replace('_', ' ').title()} at {{pct:.1f}}% of budget"

        if usage_percent >= self._critical_pct:
            msg_fmt = message_fmt_critical or default_msg
            alerts.append(
                SpendAlert(
                    execution_id=budget.execution_id,
                    workflow_type=budget.workflow_type.value,
                    threshold="critical",
                    metric=metric,
                    usage_percent=usage_percent,
                    message=msg_fmt.format(pct=usage_percent),
                )
            )
        elif usage_percent >= self._warning_pct:
            msg_fmt = message_fmt_warning or default_msg
            alerts.append(
                SpendAlert(
                    execution_id=budget.execution_id,
                    workflow_type=budget.workflow_type.value,
                    threshold="warning",
                    metric=metric,
                    usage_percent=usage_percent,
                    message=msg_fmt.format(pct=usage_percent),
                )
            )
