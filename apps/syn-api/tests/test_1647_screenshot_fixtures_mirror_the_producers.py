"""The dashboard's screenshot fixtures say what the API would say (#1647).

``apps/syn-dashboard-ui/fixtures/screenshot.json`` is what verify phases
screenshot instead of a live API. TypeScript checks its SHAPE against the
generated types; nothing there checks its VALUES, and the first version of it
invented them: progress read "3/3" where the API says "3 of 3", a run with no
start pins claimed its skill use was observed, and the workflow's phase costs
came from one execution of three. A screenshot of a wrong value proves nothing
about the page, so each value derived by a producer is recomputed here by that
producer, from the fixture's own raw fields, and must match.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from syn_api.cache_rate_display import cache_rate_display
from syn_api.cost_by_model_display import model_breakdown_text
from syn_api.routes.executions.phase_skill_use import summarize_skill_use
from syn_api.routes.metrics import _phase_costs
from syn_api.types import ExecutionSkillUseSummary, PhaseProgressInfo
from syn_domain.contexts.orchestration.domain.read_models.execution_cost import ExecutionCost
from syn_domain.contexts.orchestration.domain.read_models.phase_plan import PlannedPhase
from syn_domain.contexts.orchestration.slices.workflow_phase_metrics.phase_entry import (
    PhaseMetricsEntry,
)
from syn_domain.contexts.organization.slices.contribution_heatmap.TimescaleHeatmapQuery import (
    TimescaleHeatmapQuery,
    _DayCost,
    _DayTokens,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[3] / "apps/syn-dashboard-ui/fixtures/screenshot.json"
API = "/api/v1"
WORLD_NOW = datetime(2026, 11, 26, 10, 5, tzinfo=UTC)
"""When the fixture world is read (``WORLD_NOW`` in screenshotFixtures.ts)."""

WORLD = json.loads(FIXTURES.read_text())


def _executions() -> list:
    return [
        body
        for path, body in WORLD.items()
        if path.startswith(f"{API}/executions/") and path.count("/") == 4
    ]


def _sessions() -> list:
    return [body for path, body in WORLD.items() if path.startswith(f"{API}/sessions/")]


def _models_run(phases: list) -> set[str]:
    """``_models_run`` in routes/executions/queries.py, over the fixture's phases."""
    models: set[str] = set()
    for phase in phases:
        if phase["cost_by_model"]:
            models.update(phase["cost_by_model"])
        elif phase.get("model"):
            models.add(phase["model"])
    return models


def test_the_world_has_the_shapes_these_checks_need() -> None:
    statuses = sorted(e["status"] for e in _executions())
    assert statuses == ["completed", "failed", "running"]
    assert any(s["total_cost_usd"] != "0" and not s["cost_by_model"] for s in _sessions())


@pytest.mark.parametrize("execution", _executions(), ids=lambda e: e["status"])
def test_phase_progress_and_plan_are_the_producers(execution) -> None:
    progress = PhaseProgressInfo.without_skips(
        execution["status"], execution["completed_phases"], execution["total_phases"]
    )
    assert execution["phase_progress"] == progress.model_dump()
    for planned in execution["phase_plan"]:
        ran = {p["phase_id"]: p["status"] for p in execution["phases"]}
        status = ran.get(planned["phase_id"], "pending")
        assert planned["status"] == status
        assert planned["status_display"] == PlannedPhase("", "", status).status_display


@pytest.mark.parametrize("execution", _executions(), ids=lambda e: e["status"])
def test_skill_use_without_start_pins_is_unavailable(execution) -> None:
    phase_skill_uses = []
    for phase in execution["phases"]:
        assert phase["start_pins_status"] == "unavailable"
        expected = summarize_skill_use(None, [])
        phase_skill_uses.append(expected)
        assert phase["skill_use"] == expected.model_dump(mode="json")
    expected_summary = ExecutionSkillUseSummary.of(phase_skill_uses).model_dump(mode="json")
    assert execution["skill_use"] == expected_summary


@pytest.mark.parametrize("execution", _executions(), ids=lambda e: e["status"])
def test_execution_cost_and_cache_labels_are_the_producers(execution) -> None:
    breakdown = model_breakdown_text(
        execution["cost_by_model"], Decimal(execution["total_cost_usd"])
    )
    assert execution["cost_by_model_display"] == breakdown.cost_by_model_display
    assert execution["unattributed_cost_display"] == breakdown.unattributed_cost_display
    rates = cache_rate_display(_models_run(execution["phases"]))
    assert execution["cache_read_rate_display"] == rates.cache_read_rate_display
    assert execution["cache_write_rate_display"] == rates.cache_write_rate_display


@pytest.mark.parametrize("session", _sessions(), ids=lambda s: s["id"])
def test_session_cost_and_cache_labels_are_the_producers(session) -> None:
    breakdown = model_breakdown_text(session["cost_by_model"], Decimal(session["total_cost_usd"]))
    assert session["cost_by_model_display"] == breakdown.cost_by_model_display
    assert session["unattributed_cost_display"] == breakdown.unattributed_cost_display
    models = set(session["cost_by_model"]) or (
        {session["agent_model"]} if session["agent_model"] else set()
    )
    rates = cache_rate_display(models)
    assert session["cache_read_rate_display"] == rates.cache_read_rate_display
    assert session["cache_write_rate_display"] == rates.cache_write_rate_display


def test_workflow_phase_metrics_aggregate_every_execution() -> None:
    executions = _executions()
    costs = _phase_costs(
        [
            ExecutionCost(
                execution_id=e["workflow_execution_id"],
                cost_by_phase={p["phase_id"]: Decimal(p["cost_usd"]) for p in e["phases"]},
                unpriced_by_phase={
                    p["phase_id"]: p["unpriced_observation_count"] for p in e["phases"]
                },
            )
            for e in executions
        ]
    )
    for metric in WORLD[f"{API}/metrics"]["phases"]:
        runs = sorted(
            (
                (e["workflow_execution_id"], p)
                for e in executions
                for p in e["phases"]
                if p["phase_id"] == metric["phase_id"]
            ),
            key=lambda run: run[1]["started_at"],
        )
        entry = PhaseMetricsEntry(metric["phase_id"], metric["phase_name"])
        for execution_id, p in runs:
            entry = entry.with_run_started(execution_id, p["started_at"])
            if p["status"] != "running":
                entry = entry.with_run_finished(
                    execution_id,
                    status=p["status"],
                    recorded_seconds=p["duration_seconds"],
                    ended_at=p["completed_at"],
                )
            if p["status"] == "completed":
                # on_phase_completed: only a completed run adds its tokens.
                entry = replace(
                    entry,
                    input_tokens=entry.input_tokens + p["input_tokens"],
                    output_tokens=entry.output_tokens + p["output_tokens"],
                    total_tokens=entry.total_tokens + p["total_tokens"],
                )
        cost = costs[metric["phase_id"]]
        assert metric["status"] == entry.status
        assert metric["cost_in_progress"] == bool(entry.active_runs)
        assert Decimal(metric["cost_usd"]) == cost.cost_usd
        assert metric["cost_usd"] == str(cost.cost_usd)
        assert metric["unpriced_observation_count"] == cost.unpriced_observation_count
        assert metric["duration_seconds"] == entry.duration_seconds(now=WORLD_NOW)
        for tokens in ("input_tokens", "output_tokens", "total_tokens"):
            assert metric[tokens] == getattr(entry, tokens), (metric["phase_id"], tokens)


def test_the_heatmap_quotes_the_same_usage_as_the_global_metrics() -> None:
    metrics = WORLD[f"{API}/metrics"]
    heatmap = WORLD[f"{API}/insights/contribution-heatmap"]
    days = heatmap["days"]
    for field in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"):
        assert sum(d["breakdown"][field] for d in days) == metrics[f"total_{field}"], field
    assert sum(Decimal(str(d["breakdown"]["cost_usd"])) for d in days) == Decimal(
        metrics["total_cost_usd"]
    )
    assert heatmap["total_cost_display"] == metrics["total_cost_display"]
    for day in days:
        b = day["breakdown"]
        built = TimescaleHeatmapQuery._build_day_breakdown(
            int(b["sessions"]),
            int(b["executions"]),
            int(b["commits"]),
            _DayTokens(
                int(b["input_tokens"]),
                int(b["output_tokens"]),
                int(b["cache_creation_tokens"]),
                int(b["cache_read_tokens"]),
            ),
            _DayCost(Decimal(str(b["cost_usd"])), int(b["unpriced_tokens"])),
        )
        assert b == built, day["date"]
