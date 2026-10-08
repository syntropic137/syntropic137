"""Pydantic response models for execution query endpoints."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  # Pydantic resolves it at runtime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field

# Runtime import: Pydantic resolves the field annotations below, and
# `PhaseActivityInfo` is also called at runtime as a field default.
from syn_api.execution_budget import StartPath  # noqa: TC001
from syn_api.model_identity import CostModelKey, ObservedModelId  # noqa: TC001
from syn_api.types import (
    BranchObservationInfo,
    ExecutionEvalRunResponse,
    PhaseActivityInfo,
    PhaseProgressInfo,
    PhaseSkillUseInfo,
    PhaseStartConfig,
    PlannedPhaseInfo,
    ReadModelStatus,
    StartPinsStatus,
)
from syn_domain.contexts.orchestration import (
    DelegationFailure,
    FailureClassification,
    QuarantinedRef,
    ReportedFailureReason,
    ResumeStartStatus,  # Pydantic resolves it at runtime
    ReviewVerdict,
    SideEffectStatus,
    StartStatus,
)
from syn_shared.display import EM_DASH
from syn_shared.observed_model import format_observed_model


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
    reported_side_effects: SideEffectStatus | None = None
    """What this phase's agent said happened to its external writes, ``None``
    when it said nothing. A report, never a measurement, and it never decides
    whether the phase completed."""
    failure_classification: FailureClassification | None = None
    """Why this phase failed - ``platform``, ``task``, ``correct_refusal`` or
    ``unclassified`` - and ``None`` exactly when it did not fail. The same fact
    as the execution's ``failure_classification``, at the phase it failed in."""
    reported_failure_reason: ReportedFailureReason | None = None
    """What this phase's agent SAID caused its failure, ``None`` when it said
    nothing. A report beside the classification, never a replacement for it."""
    model: ObservedModelId | None = None
    """The model the harness REPORTED for this phase, or null (ADR-067 D9).

    Never an alias such as ``opus``: that is what the phase asked for, and it
    is ``requested_model``. Null means nothing reported what ran.
    """
    requested_model: str | None
    """The model the phase REQUESTED (often an alias), or null if not recorded."""
    agent_provider: str | None = None
    """The provider of the agent that PRODUCED this phase's result, or null
    (PC-83). Differs from the declared provider when the phase fell back to its
    ``fallback_agent`` on capacity or quota; ``requested_model`` is then the
    fallback's model. Null when nothing recorded it."""
    cost_by_model: dict[CostModelKey, str] = Field(default_factory=dict)
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
    pinned_at_start: PhaseStartConfig | None = None
    """The tools, skills and model this phase had when its execution started.

    Null is never a guess from the workflow as it stands now; `start_pins_status`
    says whether it is null because nothing was recorded or because the start
    event could not be read.
    """
    start_pins_status: StartPinsStatus = "unavailable"
    skill_use: PhaseSkillUseInfo = Field(default_factory=PhaseSkillUseInfo)
    """Which declared skills this phase invoked, and whether that is knowable
    at all: codex phases report ``not_observable``, never zero (#1269)."""
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

    @computed_field(
        description="The model for humans: the reported id verbatim, or "
        "'unknown (requested: <alias>)', or 'unknown' (ADR-067 D9)."
    )
    @property
    def model_display(self) -> str:
        """Derived, never passed in, so it cannot contradict ``model``."""
        return format_observed_model(self.model, self.requested_model)


class ExecutionStartQueueInfo(BaseModel):
    """Where a start stands in the execution budget, before its execution exists (#1557).

    Every start path - direct, trigger and resume - claims one of
    ``SYN_EXECUTION_MAX_CONCURRENT`` slots. A start that finds none free waits
    here, first come first served, and has no execution record yet; this is
    what it shows instead of a 404.
    """

    path: StartPath
    """Which entrance the start came through: ``direct``, ``trigger`` or ``resume``."""
    position: int | None
    """1 is next to start. ``None`` once the start holds a slot and is opening
    its execution, or when no process holds it (see ``held``)."""
    held: bool = True
    """Whether this API process holds the start in its budget. ``False`` for a
    durable direct request no process has picked up yet - after a restart,
    until the request ProcessManager offers it again."""
    start_status: StartStatus | None = None
    """The durable request record's status, for a direct start (#1557):
    ``pending``, ``paused``, ``retryable`` and ``dispatched`` are still owed a
    start; ``failed`` is settled, with ``status_reason``; ``withdrawn`` was
    cancelled before it started (#1650) and never starts."""
    status_reason: str | None = None
    """Why the last attempt at a direct start did not start it, if one failed."""
    running: int
    """Starts holding a slot in this process."""
    waiting: int
    """Starts queued behind the limit in this process."""
    limit: int
    """``SYN_EXECUTION_MAX_CONCURRENT``."""
    queued_at: datetime
    """When the start was accepted and claimed its place."""

    @computed_field(description="Human-readable position, e.g. 'queued 2 of 3 (4/4 running)'.")
    @property
    def position_display(self) -> str:
        if not self.held:
            return (
                f"recorded, {self.start_status or 'pending'} ({self.running}/{self.limit} running)"
            )
        if self.position is None:
            return f"starting ({self.running}/{self.limit} running)"
        return f"queued {self.position} of {self.waiting} ({self.running}/{self.limit} running)"

    @computed_field(
        description="Why it has not started: 'slots full 4/4', 'admission paused', "
        "'starting' or 'awaiting pickup (<status>)' (PC-124)."
    )
    @property
    def reason_display(self) -> str:
        if self.start_status == "paused":
            return "admission paused"
        if not self.held:
            return f"awaiting pickup ({self.start_status or 'pending'})"
        if self.position is None:
            return "starting"
        return f"slots full {self.running}/{self.limit}"


class ResumeStartInfo(BaseModel):
    """How starting the child of this execution's resume is going (#1480).

    A resume is admitted with a 200 and its child is started afterwards, in a
    background task. When that start fails, this is the only place an operator
    can see it: the child execution never appears, so there is nothing else to
    look at.
    """

    status: ResumeStartStatus
    """``pending``, ``paused``, ``retryable`` and ``dispatched`` are still owed a
    start and will be offered again; ``started`` and ``failed`` are settled."""
    status_reason: str | None = None
    """Why the last attempt did not start the child, if one failed."""
    attempts: int = 0
    """Failed attempts counted so far. A hold for maintenance is not one."""
    max_attempts: int
    """The ceiling: ``attempts`` reaching it settles the start as ``failed``."""
    recorded_at: datetime
    """When the resume was put on the to-do list."""
    dispatched_at: datetime | None = None
    """When the start in flight was handed to a background task.

    Set only while ``status`` is ``dispatched``; a failed attempt writes its
    outcome over the record it was dispatched from, which had none."""
    start_queue: ExecutionStartQueueInfo | None = None
    """Where the child's start stands in the execution budget, while it waits
    for a slot or opens its execution in this process (#1557). A ``dispatched``
    start with this set is queued, not lost, and is not re-offered."""


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
    phase_progress: PhaseProgressInfo
    """Progress with skipped repair rounds accounted for; what clients render."""
    phase_plan: list[PlannedPhaseInfo]
    """Every phase the run declared, in order, with where each stands: ran here,
    ``pending``, ``skipped`` or ``inherited`` (feedback cee46909).

    Read off the same start event as ``total_phases``, so a run with declared
    phases lists exactly that many. Draw the timeline from this, not from
    ``phases``, which holds only the phases that started.
    """
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
    cache_read_rate_display: str | None = None
    """How cache READS are billed relative to fresh input, e.g. ``"0.05x rate"``.

    Derived from the price table for every model this scope ran. ``None`` when
    no single multiplier is true: models that disagree (Opus 5.5 reads at 0.05x,
    GPT-6-Sol at 0.1x), a model with no rate, or no model recorded yet. A
    client must not substitute a constant; that is the bug this field replaced.
    """
    cache_write_rate_display: str | None = None
    """How cache WRITES are billed relative to fresh input, e.g. ``"1.25x rate"``.

    Same derivation and ``None`` contract as ``cache_read_rate_display``.
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
    delegation_failure: DelegationFailure | None = None
    """Which required delegate did not happen, and why (#894); `None` for every
    other failure. `reason` is `not_attempted`, `failed` or `unverifiable`, and
    `attempts` names each delegate the platform observed - its id, target
    harness, outcome, exit code and launch-failure reason - so a client never
    parses `error_message` for them. Observed by the platform, never the
    agent's word."""
    reported_failure_reason: ReportedFailureReason | None = None
    """The word the failing phase wrote for what caused it, if it wrote one (#1392).

    Same field, same meaning, as on `syn_api.types.ExecutionDetail`: what the
    AGENT SAID, beside the `failure_classification` the PLATFORM measured and
    never folded into it. This is the model the HTTP route actually returns,
    so a report that stops short of here never reaches a client - and a
    dashboard with nothing to quote falls back to showing the measurement
    alone, which is the state #1392 was opened about.
    """
    quarantined_refs: list[QuarantinedRef] = Field(default_factory=list)
    """Where the failed phase's unpushed work was saved, one per repository (#1547).

    Each names the `refs/syn/lost/<execution>/<phase>` ref and the commit it
    holds, so a client can recover the work without parsing `error_message`.
    """
    deliverable_produced: bool = False
    """True when any phase stored an artifact, whatever `status` says.

    A run can fail after its deliverable exists, and complete while a phase's
    write-back was refused; this is the one field that answers "is there work
    to read" without inferring it from `artifact_ids`. Scoped, like every
    per-phase field here, to the phases this execution ran: a resumed run's
    inherited phases are on its parent.
    """
    review_verdict: ReviewVerdict | None = None
    """The last review verdict the run reported (PC-63). On a `completed` run,
    `blocked` means it completed with unresolved findings, not certified."""
    reported_side_effects: SideEffectStatus | None = None
    """The most severe side-effect status any phase reported, ``None`` if none did.

    What the AGENTS SAID about their external writes (a PR comment, a push):
    ``denied`` beside a completed run means the deliverable is finished and a
    write-back was refused - grant the permission, do not re-run the work.
    """
    repos: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    """The execution's current tags, normalised and sorted (#967)."""
    task: str | None = None
    """What this run was asked to do -- the ``$ARGUMENTS`` it was dispatched
    with, or ``None`` if the workflow takes none (#1307)."""
    inputs: dict[str, str] = Field(default_factory=dict)
    """The full input set the run was dispatched with, including ``task`` and
    the ``repos`` string the other fields are derived from.

    Enough to re-dispatch the run: a caller retrying one that died on the
    platform posts these back rather than reconstructing them from its own
    notes (#1307)."""
    eval: ExecutionEvalRunResponse | None = None
    """The eval this execution is a current run of, with its verdict. Null in no eval."""
    resume_start: ResumeStartInfo | None = None
    """The start of the child this execution admitted when it was resumed.

    ``None`` when this execution has not been resumed. Read from the PARENT,
    because the record is keyed by the parent and a child that failed to start
    has no execution of its own to show it on (#1480).
    """
    start_queue: ExecutionStartQueueInfo | None = None
    """Set, with ``status`` ``queued`` or ``starting``, for an execution that has
    been accepted but not yet opened, because it is waiting for a slot in the
    execution budget (#1557). ``None`` for every execution that exists."""
    read_model_status: ReadModelStatus | None = None
    """Whether the execution detail read model is rebuilding, so a page missing
    recent phases can say why instead of looking broken."""


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
    phase_progress: PhaseProgressInfo
    """Progress with skipped repair rounds accounted for; what clients render."""
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
    tags: list[str] = Field(default_factory=list)
    """The execution's current tags, normalised and sorted (#967)."""
    repos_display: str | None = None
    eval: ExecutionEvalRunResponse | None = None
    """The eval this execution is a current run of, with its verdict. Null in no eval.

    The same shape ``GET /executions/{id}`` carries, so a list row and the
    execution page cannot describe the run differently."""
    start_queue: ExecutionStartQueueInfo | None = None
    """Set exactly when ``status`` is ``queued``: an accepted start with no
    execution yet, and where it stands (PC-124). Same block as on the detail."""


class ExecutionBudgetInfo(BaseModel):
    """How full the execution budget is right now, for the app bar (PC-124).

    ``running`` and ``limit`` are this API process's budget. ``queued`` is
    every start the list reports as ``queued``: waiting here for a slot, or
    recorded durably and not yet picked up by any process.
    """

    running: int
    queued: int
    limit: int
    """``SYN_EXECUTION_MAX_CONCURRENT``."""
    admission_paused: bool | None
    """Maintenance mode is on: new starts are accepted and held, not started.
    ``None`` when the flag could not be read, which is not a statement either way."""

    @computed_field(description="e.g. '2 running / 3 queued / cap 4'.")
    @property
    def display(self) -> str:
        text = f"{self.running} running / {self.queued} queued / cap {self.limit}"
        if self.admission_paused is None:
            return f"{text} (admission state unknown)"
        return f"{text} (admission paused)" if self.admission_paused else text


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
    budget: ExecutionBudgetInfo | None = None
    """The execution budget's occupancy (PC-124). Not filtered by the request."""
    status_counts: dict[str, int] = Field(default_factory=dict)
    """Matching executions tallied by status, ignoring the status filter itself.

    Counted over every OTHER filter the request carried, so the chips say what
    selecting a different status would actually return. A tally of the returned
    rows cannot answer that: it only ever knows about the status already
    selected, and only about one page of it.
    """
    read_model_status: ReadModelStatus | None = None
    """Whether the execution list read model is rebuilding. While it is, this
    page is a partial view of history and the newest runs may be missing."""
