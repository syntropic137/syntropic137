"""Pydantic response models for execution query endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# Runtime import: Pydantic resolves the field annotations below, and
# `PhaseActivityInfo` is also called at runtime as a field default.
from syn_api.types import BranchObservationInfo, PhaseActivityInfo
from syn_domain.contexts.orchestration import FailureClassification, ReportedFailureReason
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
    deliverable_recovered: bool = False
    """True when this phase's deliverable was recovered from its transcript
    rather than read off the file it declared (#1195, #1300).

    The end of the chain the flag travels: event -> projection record -> read
    model -> here. A client auditing which runs stood on a salvage reads this;
    `status` says `completed` either way.
    """
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
    exit_code: int | None = None
    """What this phase's process exited with, or null if nothing observed one.

    THE STATUS, NOT A SUMMARY OF IT (#1319). `status: failed` says the phase
    did not succeed; this says how, and the three common answers need opposite
    handling - 0 finished, 124 reached its time budget and the work should be
    continued, a negative value was killed by that signal and should be
    retried. Before this field the number existed only inside the prose of
    `error_message`, and only while the read model was queryable at all.

    THREE-VALUED, same contract as the fields around it: `null` means nothing
    observed a status - every phase that did not fail, a phase stranded by an
    API restart, a failure with no process behind it, an execution predating
    the field - and is not the same claim as 0. A phase that SUCCEEDED says so
    in `status`; this field is for the runs where that is not the answer.
    """
    observed_branches: list[BranchObservationInfo] | None = None
    """Where this phase's branches stood when it failed (#1200).

    THREE-VALUED, same contract as `agent_session_ids` above: `null` means
    nothing could tell us - the phase did not fail, its workspace was already
    gone, or the execution predates the field - and `[]` means the workspace
    was read and no branch differs from how the phase found it. A client
    distinguishing "a branch moved, go and fetch it" from "nothing here
    changed" reads this, not the prose in `error_message`.

    Only branches that DIFFER from the phase's starting point appear. The
    branch it was handed is normally already on a remote, so recording every
    branch would hand every failed phase a location and make the two incidents
    identical again. What no record claims is who moved a ref: git does not
    carry that, so this reports the two readings and stops.
    """
    operations: list[PhaseOperationInfo] = Field(default_factory=list)
    activity: PhaseActivityInfo = Field(default_factory=PhaseActivityInfo)
    """What this phase was doing when it ended, and against what budget (#1262).

    The four readings that tell a phase killed on its deadline from one that
    hung - both exit 124, and they need opposite responses. `PhaseActivityInfo`
    states what each one means and what its nulls do not mean.

    Served so that an operator, or the agent triaging the run, can decide
    without opening a transcript. `operations` below carries the same activity
    row by row; this is the summary of it, and `operations_count` is
    deliberately not that list's length.
    """


class ExecutionDetailResponse(BaseModel):
    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    phases: list[PhaseExecutionInfo] = Field(default_factory=list)
    total_phases: int = 0
    """Phases this run set out to do, from its WorkflowExecutionStarted event.

    ``len(phases)`` is not this number and never was: it counts the phases that
    have started, so a three-phase run that died in phase one renders as a
    one-phase execution to any client that measures the list (#1147). The two
    phases that never ran are only visible as the gap between these.
    """
    completed_phases: int = 0
    """Phases that finished. Same field, same meaning, as on the list view."""
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
    failure_classification: FailureClassification = FailureClassification.UNCLASSIFIED
    """What kind of failure ended this run, beside `status` (#1357).

    Same field, same meaning, as on `syn_api.types.ExecutionDetail`: `platform` for
    the machinery breaking, `correct_refusal` for a phase that reported
    `success=false` and was recorded faithfully, `unclassified` for a run that
    ended before anything recorded the difference. This is the model the HTTP
    route actually returns, so a value that stops short of here never reaches
    a client.
    """
    reported_failure_reason: ReportedFailureReason | None = None
    """The word the failing phase wrote for what caused it, if it wrote one (#1392).

    Same field, same meaning, as on `syn_api.types.ExecutionDetail`: what the
    AGENT SAID, beside the `failure_classification` the PLATFORM measured and
    never folded into it. This is the model the HTTP route actually returns,
    so a report that stops short of here never reaches a client - and a
    dashboard with nothing to quote falls back to showing the measurement
    alone, which is the state #1392 was opened about.
    """
    repos: list[str] = Field(default_factory=list)
    task: str | None = None
    """What this run was asked to do -- the ``$ARGUMENTS`` it was dispatched
    with, or ``None`` if the workflow takes none (#1307)."""
    inputs: dict[str, str] = Field(default_factory=dict)
    """The full input set the run was dispatched with, including ``task`` and
    the ``repos`` string the other fields are derived from.

    Enough to re-dispatch the run: a caller retrying one that died on the
    platform posts these back rather than reconstructing them from its own
    notes (#1307)."""


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
    failure_classification: FailureClassification = FailureClassification.UNCLASSIFIED
    """What kind of failure ended this run, beside `status` (#1357).

    Same field, same meaning, as on `syn_api.types.ExecutionSummary`: `platform` for
    the machinery breaking, `correct_refusal` for a phase that reported
    `success=false` and was recorded faithfully, `unclassified` for a run that
    ended before anything recorded the difference. This is the model the HTTP
    route actually returns, so a value that stops short of here never reaches
    a client.
    """
    reported_failure_reason: ReportedFailureReason | None = None
    """The word the failing phase wrote for what caused it, if it wrote one (#1392).

    Same field, same meaning, as on `syn_api.types.ExecutionDetail`: what the
    AGENT SAID, beside the `failure_classification` the PLATFORM measured and
    never folded into it. This is the model the HTTP route actually returns,
    so a report that stops short of here never reaches a client - and a
    dashboard with nothing to quote falls back to showing the measurement
    alone, which is the state #1392 was opened about.
    """
    repos: list[str] = Field(default_factory=list)
    repos_display: str | None = None


class ExecutionListResponse(BaseModel):
    executions: list[ExecutionSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 50
    excluded_undated: int = 0
    """Executions dropped from this window because they carry no date at all.

    ``total`` cannot say why a row is missing: "older than the bound" and
    "undated" leave it looking identical, so narrowing a window showed an
    unexplained gap (#1215). With this the reader gets "755 of 1037, 274
    undated" instead.

    Zero when the request gave no window - an unbounded query evaluates every
    row and returns the undated ones. Non-zero means rows exist that this
    filter could not judge, NOT that they failed it.
    """
    status_counts: dict[str, int] = Field(default_factory=dict)
    """Matching executions tallied by status, ignoring the status filter itself.

    Counted over every OTHER filter the request carried, so the chips say what
    selecting a different status would actually return. A tally of the returned
    rows cannot answer that: it only ever knows about the status already
    selected, and only about one page of it.
    """
