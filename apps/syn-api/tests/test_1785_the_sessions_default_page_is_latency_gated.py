"""The page Sessions opens at is held to the list budget (#1785).

Sessions opens at 100 rows (feedback 60d9f990). The E2 latency gate times
``/sessions?page_size=100``, but until this change it timed it ungated: a
100-row Sessions response over 200 ms passed. These tests feed the gate's own
predicate synthetic p95s, so whether the default page is gated is settled in
the unit gate, without the TimescaleDB the measurement itself needs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

pytestmark = pytest.mark.unit

_GATE = Path(__file__).parent / "integration" / "test_list_detail_latency_budget.py"


def _load_gate() -> ModuleType:
    # By path under a unique name: several test trees have an `integration`
    # package, so importing it by package name depends on collection order.
    spec = importlib.util.spec_from_file_location("_e2_latency_gate_1785", _GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _within_budget() -> dict[str, float]:
    return {e.name: e.budget_ms / 2 for e in gate.ENDPOINTS}


def test_every_endpoint_within_budget_passes() -> None:
    assert gate.over_budget(_within_budget()) == []


def test_an_over_budget_sessions_default_page_fails_the_gate() -> None:
    measured = _within_budget()
    measured["/sessions?page_size=100"] = 999.0

    assert gate.over_budget(measured) == ["/sessions?page_size=100"]


def test_the_executions_choice_page_is_timed_but_not_gated() -> None:
    # Executions opens at 50; 100 is the operator's choice, timed for its ratio.
    measured = _within_budget()
    measured["/executions?page_size=100"] = 999.0

    assert gate.over_budget(measured) == []
