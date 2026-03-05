"""Tests for ThresholdMonitor."""

from decimal import Decimal

import pytest

from syn_tokens.models import SpendBudget, WorkflowType
from syn_tokens.threshold import ThresholdMonitor


def _budget(
    input_used: int = 0,
    input_max: int = 100_000,
    cost_used: Decimal = Decimal("0"),
    cost_max: Decimal = Decimal("10.00"),
) -> SpendBudget:
    """Create a test budget."""
    b = SpendBudget(
        execution_id="exec-1",
        workflow_type=WorkflowType.RESEARCH,
        max_input_tokens=input_max,
        max_output_tokens=50_000,
        max_cost_usd=cost_max,
    )
    b.used_input_tokens = input_used
    b.used_cost_usd = cost_used
    return b


@pytest.mark.unit
class TestThresholdMonitor:
    def test_no_alerts_below_threshold(self) -> None:
        monitor = ThresholdMonitor()
        alerts = monitor.check(_budget(input_used=50_000))
        assert len(alerts) == 0

    def test_warning_at_80_percent(self) -> None:
        monitor = ThresholdMonitor()
        alerts = monitor.check(_budget(input_used=85_000))
        input_alerts = [a for a in alerts if a.metric == "input_tokens"]
        assert len(input_alerts) == 1
        assert input_alerts[0].threshold == "warning"

    def test_critical_at_95_percent(self) -> None:
        monitor = ThresholdMonitor()
        alerts = monitor.check(_budget(input_used=96_000))
        input_alerts = [a for a in alerts if a.metric == "input_tokens"]
        assert len(input_alerts) == 1
        assert input_alerts[0].threshold == "critical"

    def test_cost_threshold_warning(self) -> None:
        monitor = ThresholdMonitor()
        alerts = monitor.check(_budget(cost_used=Decimal("8.50")))
        cost_alerts = [a for a in alerts if a.metric == "cost"]
        assert len(cost_alerts) == 1
        assert cost_alerts[0].threshold == "warning"

    def test_custom_thresholds(self) -> None:
        monitor = ThresholdMonitor(warning_pct=50, critical_pct=75)
        alerts = monitor.check(_budget(input_used=60_000))
        input_alerts = [a for a in alerts if a.metric == "input_tokens"]
        assert len(input_alerts) == 1
        assert input_alerts[0].threshold == "warning"
