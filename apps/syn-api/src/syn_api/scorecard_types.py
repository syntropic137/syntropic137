"""Response models for ``GET /insights/scorecard``.

Re-exported from ``syn_api.types``, the single source of the API contract.
Every count says what it counts in ``scope``; every figure a person reads has a
``*_display`` twin rendered by the shared formatters, so the dashboard and the
CLI show the same text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

TargetStatusValue = Literal["on_track", "off_track", "no_data"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScorecardOutcomeCountsResponse(_Frozen):
    """Finished resume chains by final outcome. A resumed run is counted once, as its chain."""

    total: int
    completed: int
    failed_platform: int
    failed_task: int
    failed_correct_refusal: int
    failed_unclassified: int
    cancelled: int
    completed_platform_failure_free: int
    platform_failure_free_rate: float | None
    platform_failure_free_rate_display: str


class ScorecardPhaseTypeResponse(_Frozen):
    phase_type: str
    phase_count: int
    median_tokens: float | None
    median_tokens_display: str
    p90_tokens: float | None
    p90_tokens_display: str
    cache_read_share: float | None
    cache_read_share_display: str
    median_tool_calls: float | None
    median_tool_calls_display: str
    tokens_per_tool_call: float | None
    tokens_per_tool_call_display: str
    phases_with_tool_counts: int
    median_cost_usd: str | None
    median_cost_display: str
    p90_cost_usd: str | None
    p90_cost_display: str
    phases_with_cost: int


class ScorecardOutcomeRowResponse(_Frozen):
    key: str
    counts: ScorecardOutcomeCountsResponse
    phases: list[ScorecardPhaseTypeResponse]


class ScorecardDailyPointResponse(_Frozen):
    day: str
    counts: ScorecardOutcomeCountsResponse
    cost_usd: str
    cost_display: str
    median_verify_tokens: float | None
    median_verify_tokens_display: str
    median_verify_cost_usd: str | None
    median_verify_cost_display: str
    peak_concurrency: int


class ScorecardThroughputResponse(_Frozen):
    average_concurrency: float
    average_concurrency_display: str
    peak_concurrency: int
    median_queue_wait_seconds: float | None
    median_queue_wait_display: str
    p90_queue_wait_seconds: float | None
    p90_queue_wait_display: str
    queue_waits_measured: int
    scope: str


class ScorecardDeliveryResponse(_Frozen):
    """Merged PRs and cost per merged PR. ``None`` until a run's PR is recorded."""

    merged_prs: int | None
    cost_per_merged_pr_usd: str | None
    cost_per_merged_pr_display: str
    scope: str


class ScorecardTargetResponse(_Frozen):
    name: str
    actual: float | None
    actual_display: str
    target: float
    target_display: str
    higher_is_better: bool
    status: TargetStatusValue


class ScorecardResponse(_Frozen):
    """The platform's return on investment over a window of UTC days."""

    window: str
    window_start: str
    window_end: str
    scope: str
    counts: ScorecardOutcomeCountsResponse
    by_workflow: list[ScorecardOutcomeRowResponse]
    by_model: list[ScorecardOutcomeRowResponse]
    phases: list[ScorecardPhaseTypeResponse]
    phases_scope: str
    daily: list[ScorecardDailyPointResponse]
    throughput: ScorecardThroughputResponse
    total_cost_usd: str
    total_cost_display: str
    cost_scope: str
    delivery: ScorecardDeliveryResponse
    targets: list[ScorecardTargetResponse]
    eval_quality_scope: str
