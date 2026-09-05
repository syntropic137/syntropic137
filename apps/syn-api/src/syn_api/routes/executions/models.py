"""Pydantic response models for execution query endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from syn_api.types import PushedWorkInfo
from syn_shared.display import EM_DASH


class PhaseOperationInfo(BaseModel):
    operation_id: str
    operation_type: str
    timestamp: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    success: bool = True
    """Whether this operation's subject went wrong.

    A row whose type IS a failure (`session_error`, `error`,
    `tool_execution_failed`) now reports False, decided once in
    `session_tools_verdict.read_verdict` (#1196). It used to report True here
    for every one of them, because the projection had nothing to say and this
    layer read that silence as a yes.

    True still means "nothing reported a failure", not "it finished and
    succeeded" - a `tool_execution_started` row has no verdict yet. That
    remaining default is a DISPLAY choice, kept because the dashboard renders
    this field as a strict boolean; see `_map_phase_to_response`.
    """
    error_message: str | None = None
    """What went wrong, when something did.

    Never the empty string: an operation that reports a failure and no reason
    is the defect this field exists to close, so the projection substitutes
    `NO_REASON_RECORDED` rather than leaving it blank.
    """


class PhaseExecutionInfo(BaseModel):
    phase_id: str
    name: str
    status: str
    session_id: str | None = None
    artifact_id: str | None = None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_tokens: int
    duration_seconds: float | None = None
    """``None`` means genuinely unknown. A ``running`` phase computes this live
    at read time (``now - started_at``); other phases without a completion
    event to record one have no duration to report.
    """
    cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    model: str | None = None
    cost_by_model: dict[str, str] = Field(default_factory=dict)
    agent_session_ids: list[str] | None = None
    """The agent-native session ids this phase's capture confirmed, in the order
    the store reported them.

    A phase has MANY. ``session_id`` above is the uuid4 syn137 assigns per phase
    run; these are the ids the AGENTS chose for themselves, and one phase yields
    several whenever it delegates - a codex phase handing work to claude, a
    subagent, a resumed thread. The host never passes its id to the agent, so
    the two namespaces are disjoint and this field is the only thing relating
    them: it is what makes an execution's transcripts fetchable (#1185).

    THREE-VALUED, and null is not empty. ``null`` means nothing could tell us -
    a phase that predates the field, an exporter that did not report it, or
    telemetry that was unreachable. ``[]`` means the sweep ran and confirmed
    none. Defaulting the first to the second reports a loss that did not happen
    (#1176).
    """
    pushed_work: list[PushedWorkInfo] | None = None
    """Branches a remote is confirmed to hold for this phase's work (#1200).

    THREE-VALUED, same contract as `agent_session_ids` above: `null` means
    nothing could tell us - the phase did not fail, its workspace was already
    gone, or the execution predates the field - and `[]` means the workspace
    was asked and none of its commits had reached a remote. A client
    distinguishing "the work is recoverable, go and fetch it" from "the work is
    gone" reads this, not the prose in `error_message`.
    """
    operations: list[PhaseOperationInfo] = Field(default_factory=list)


class ExecutionDetailResponse(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    phases: list[PhaseExecutionInfo] = Field(default_factory=list)
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_tokens: int
    total_cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    total_duration_seconds: float | None = None
    """Wall-clock seconds across the execution's phases, including any still
    running. ``None`` means no phase had a resolvable duration -- unknown, not
    zero.
    """
    unknown_duration_phase_count: int = 0
    """Phases whose duration is unknown and so contributed nothing to the total.

    Non-zero means ``total_duration_seconds`` is a LOWER BOUND, not the total
    (same contract as ``unpriced_observation_count`` for cost, #890).
    """
    artifact_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None
    repos: list[str] = Field(default_factory=list)


class ExecutionSummaryResponse(BaseModel):
    """Summary of a workflow execution.

    Display fields (``*_display``) are produced server-side so all clients
    (dashboard, CLI, future UIs) share identical human-readable output. Raw
    fields remain for programmatic consumers; both are always present.

    See: docs/adrs/ADR-064-observability-monitor-ui.md
    """

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    total_tokens: int
    total_tokens_display: str = "0"
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_cost_usd: Decimal = Decimal("0")
    total_cost_display: str = EM_DASH
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    duration_seconds: float | None = None
    duration_display: str = "—"
    tool_call_count: int = 0
    error_message: str | None = None
    repos: list[str] = Field(default_factory=list)
    repos_display: str | None = None


class ExecutionListResponse(BaseModel):
    executions: list[ExecutionSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 50
    status_counts: dict[str, int] = Field(default_factory=dict)
    """Matching executions tallied by status, ignoring the status filter itself.

    Counted over every OTHER filter the request carried, so the chips say what
    selecting a different status would actually return. A tally of the returned
    rows cannot answer that: it only ever knows about the status already
    selected, and only about one page of it.
    """
