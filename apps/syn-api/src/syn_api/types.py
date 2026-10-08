"""Result type and shared Pydantic models for the Syn137 API.

Provides a discriminated union Result type for typed error handling,
plus Pydantic response models used across all v1 modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 — needed at runtime for Pydantic
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    computed_field,
    model_serializer,
)

# Runtime imports, not TYPE_CHECKING ones: pydantic resolves these annotations
# at class-construction time.
#
# FailureClassification: the whole point of reusing the DOMAIN enum here is that
# the API and the CLI cannot grow a second spelling of the same vocabulary
# (#1357). Imported from the context's public surface, not its internals
# (ADR-062).
#
# The other three are republished by /health as its own fields, referenced
# rather than restated - the probe that produces a shape is the only place
# allowed to define it (#1380).
from syn_adapters.subscriptions.read_model_lag import ProjectionLag  # noqa: TC001
from syn_adapters.subscriptions.unapplied_starts import UnappliedStart  # noqa: TC001
from syn_api.inventory_types import CaptureRevisionHashes as CaptureRevisionHashes
from syn_api.inventory_types import LocalTranscriptResponse as LocalTranscriptResponse
from syn_api.inventory_types import (
    SessionHistoryBackfillSummary as SessionHistoryBackfillSummary,
)
from syn_api.inventory_types import (
    SessionInventoryBackfillRequest as SessionInventoryBackfillRequest,
)
from syn_api.inventory_types import (
    SessionInventoryBackfillResponse as SessionInventoryBackfillResponse,
)
from syn_api.inventory_types import (
    SessionInventoryCursorError as SessionInventoryCursorError,
)
from syn_api.inventory_types import (
    SessionInventoryCursorErrorResponse as SessionInventoryCursorErrorResponse,
)
from syn_api.inventory_types import (
    SessionInventoryJobResponse as SessionInventoryJobResponse,
)
from syn_api.inventory_types import (
    SessionInventoryNamespace as SessionInventoryNamespace,
)
from syn_api.inventory_types import (
    SessionInventoryNodeResponse as SessionInventoryNodeResponse,
)
from syn_api.inventory_types import (
    SessionInventoryPageResponse as SessionInventoryPageResponse,
)
from syn_api.inventory_types import (
    SessionInventoryRefreshRequest as SessionInventoryRefreshRequest,
)
from syn_api.inventory_types import (
    SessionInventoryRefreshResponse as SessionInventoryRefreshResponse,
)
from syn_api.inventory_types import (
    SessionInventoryResponse as SessionInventoryResponse,
)
from syn_api.inventory_types import (
    SessionInventorySummary as SessionInventorySummary,
)
from syn_api.inventory_types import TranscriptDeletionRequest as TranscriptDeletionRequest
from syn_api.inventory_types import TranscriptDeletionResponse as TranscriptDeletionResponse
from syn_api.inventory_types import TranscriptIdentityRequest as TranscriptIdentityRequest
from syn_api.inventory_types import TranscriptRevocationResponse as TranscriptRevocationResponse
from syn_api.model_identity import CostModelKey, ObservedModelId, ResolvedModelId  # noqa: TC001
from syn_api.services.cpu_throttling import CpuThrottling  # noqa: TC001
from syn_api.services.degraded_reasons import DegradedReason  # noqa: TC001
from syn_domain.contexts.orchestration import (
    DelegationFailure,
    EvalId,
    FailureClassification,
    PhaseProgress,
    PlannedPhase,
    QuarantinedRef,
    ReportedFailureReason,
    ReviewVerdict,
    SideEffectStatus,
    TagSet,
    Verdict,
)

# One import, and no TC001: DEFAULT_PHASE_SANDBOX is a Pydantic field default
# so `syn_shared.agents` is needed at RUNTIME, which makes a type-checking-only
# guard on AliasResolutionBasis both unused and misleading.
from syn_shared.agents import DEFAULT_PHASE_SANDBOX, AliasResolutionBasis
from syn_shared.codex_auth_status import CodexAuthStatus  # noqa: TC001
from syn_shared.display import format_utc_timestamp
from syn_shared.display.formatters import EM_DASH
from syn_shared.observed_model import format_observed_model

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):  # noqa: UP046 — Generic required for @dataclass(slots=True)
    """Success variant of Result."""

    value: T


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):  # noqa: UP046 — Generic required for @dataclass(slots=True)
    """Error variant of Result."""

    error: E
    message: str | None = None


Result = Ok[T] | Err[E]

# ---------------------------------------------------------------------------
# Error enums
# ---------------------------------------------------------------------------


class WorkflowError(StrEnum):
    """Errors returned by workflow operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_ARCHIVED = "already_archived"
    INVALID_INPUT = "invalid_input"
    EXECUTION_FAILED = "execution_failed"
    HAS_ACTIVE_EXECUTIONS = "has_active_executions"
    PACKAGE_MISMATCH = "package_mismatch"
    NOT_IMPLEMENTED = "not_implemented"


class ExecutionError(StrEnum):
    """Errors returned by execution operations."""

    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"
    EXECUTION_FAILED = "execution_failed"
    SIGNAL_FAILED = "signal_failed"
    STORE_UNAVAILABLE = "store_unavailable"
    """The event store could not be read, so the state is UNKNOWN.

    Distinct from NOT_FOUND. `get_state` used to map every load exception to
    NOT_FOUND, and the endpoint then returned 200 with `state="unknown"` - so a
    store outage rendered as a successful answer. "I looked and there is
    nothing" and "I could not look" are different facts and must not share a
    code."""


class MetricsError(StrEnum):
    """Errors returned by metrics operations."""

    QUERY_FAILED = "query_failed"
    NOT_FOUND = "not_found"


class LifecycleError(StrEnum):
    """Errors returned by lifecycle operations."""

    CONNECTION_FAILED = "connection_failed"
    VALIDATION_FAILED = "validation_failed"


class SessionError(StrEnum):
    """Errors returned by session operations."""

    NOT_FOUND = "not_found"
    ALREADY_COMPLETED = "already_completed"
    INVALID_INPUT = "invalid_input"
    NOT_IMPLEMENTED = "not_implemented"


class ArtifactError(StrEnum):
    """Errors returned by artifact operations."""

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    STORAGE_ERROR = "storage_error"
    NOT_IMPLEMENTED = "not_implemented"
    ALREADY_DELETED = "already_deleted"


class GitHubError(StrEnum):
    """Errors returned by GitHub operations."""

    NOT_FOUND = "not_found"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    INVALID_SIGNATURE = "invalid_signature"
    INVALID_PAYLOAD = "invalid_payload"
    PROCESSING_FAILED = "processing_failed"
    NOT_IMPLEMENTED = "not_implemented"


# ---------------------------------------------------------------------------
# GitHub accessible repo models
# ---------------------------------------------------------------------------


class GitHubRepoResponse(BaseModel):
    """A repository accessible to the GitHub App installation."""

    model_config = ConfigDict(from_attributes=True)

    github_id: int
    name: str
    full_name: str
    private: bool
    default_branch: str
    owner: str
    installation_id: str


class GitHubRepoLookup(StrEnum):
    """How much of the GitHub App's access a repo listing actually covers.

    Only ``complete`` makes a repo's absence mean the App cannot reach it. A
    ``partial`` listing still proves access for every repo it contains; an
    ``unavailable`` one proves nothing.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class GitHubRepoListResponse(BaseModel):
    """List of repositories accessible to the GitHub App."""

    repos: list[GitHubRepoResponse] = Field(default_factory=list)
    total: int = 0
    installation_id: str | None = None
    lookup: GitHubRepoLookup


class ObservabilityError(StrEnum):
    """Errors returned by observability operations."""

    NOT_FOUND = "not_found"
    QUERY_FAILED = "query_failed"
    NOT_IMPLEMENTED = "not_implemented"
    #: A session is KNOWN to have started no agent process, so no conversation
    #: log ever existed for it. Requires positive evidence of the negative -
    #: a session we simply know nothing about is NOT_FOUND, which means a log
    #: should exist but could not be located (issues #1047, #1065).
    NEVER_STARTED = "never_started"
    #: The session is still running and has not yet produced a conversation
    #: log - regardless of what is known about its agent process. Distinct
    #: from NEVER_STARTED (no agent process, terminal) and NOT_FOUND
    #: (terminal but unexplained) (issue #1047).
    PENDING = "pending"


class TriggerError(StrEnum):
    """Errors returned by trigger operations."""

    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    ALREADY_PAUSED = "already_paused"
    ALREADY_ACTIVE = "already_active"
    ALREADY_DELETED = "already_deleted"
    PRESET_NOT_FOUND = "preset_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    STORE_UNAVAILABLE = "store_unavailable"
    """The event store could not be read, so existence is UNKNOWN.

    Distinct from WORKFLOW_NOT_FOUND on purpose. `exists()` used to answer
    False when the store was unreachable, so an outage rendered as "that
    workflow does not exist" - a confident wrong answer a caller would act on.
    The store now raises instead, and this code carries the difference through
    to the caller rather than collapsing it back into not-found."""


class OrganizationError(StrEnum):
    """Errors returned by organization operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_DELETED = "already_deleted"
    INVALID_INPUT = "invalid_input"
    HAS_SYSTEMS = "has_systems"
    HAS_REPOS = "has_repos"


class SystemErrorCode(StrEnum):
    """Errors returned by system operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_DELETED = "already_deleted"
    INVALID_INPUT = "invalid_input"
    ORGANIZATION_NOT_FOUND = "organization_not_found"
    HAS_REPOS = "has_repos"


class RepoError(StrEnum):
    """Errors returned by repo operations."""

    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    INVALID_INPUT = "invalid_input"
    ORGANIZATION_NOT_FOUND = "organization_not_found"
    SYSTEM_NOT_FOUND = "system_not_found"
    ALREADY_ASSIGNED = "already_assigned"
    NOT_ASSIGNED = "not_assigned"
    ALREADY_DEREGISTERED = "already_deregistered"
    HAS_ACTIVE_TRIGGERS = "has_active_triggers"
    TRIGGER_CHECK_FAILED = "trigger_check_failed"


class ConfigError(StrEnum):
    """Errors returned by config operations."""

    LOAD_FAILED = "load_failed"


# ---------------------------------------------------------------------------
# Request models — Pydantic schemas for API request bodies
# ---------------------------------------------------------------------------


class CreateOrganizationRequest(BaseModel):
    """Request body for creating a new organization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    slug: str
    created_by: str = "api"


class UpdateOrganizationRequest(BaseModel):
    """Request body for updating an organization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    slug: str | None = None


class RegisterRepoRequest(BaseModel):
    """Request body for registering a new repo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: str = "_unaffiliated"
    full_name: str
    provider: str = "github"
    owner: str = ""
    default_branch: str = "main"
    provider_repo_id: str = ""
    installation_id: str = ""
    is_private: bool = False
    created_by: str = "api"


class UpdateRepoRequest(BaseModel):
    """Request body for updating a repo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_branch: str | None = None
    is_private: bool | None = None
    installation_id: str | None = None
    updated_by: str = "api"


class AssignRepoToSystemRequest(BaseModel):
    """Request body for assigning a repo to a system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_id: str


class CreateSystemRequest(BaseModel):
    """Request body for creating a new system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: str
    name: str
    description: str = ""
    created_by: str = "api"


class UpdateSystemRequest(BaseModel):
    """Request body for updating a system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    description: str | None = None


class TriggerConfigRequest(BaseModel):
    """Safety configuration for a trigger rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = 3
    daily_limit: int = 20
    debounce_seconds: int = 0
    cooldown_seconds: int = 300


class ConditionRequest(BaseModel):
    """A single trigger condition (field operator value)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    operator: str
    value: str


class RegisterTriggerRequest(BaseModel):
    """Request body for registering a new trigger rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    event: str
    repository: str
    workflow_id: str
    conditions: list[ConditionRequest] | None = None
    installation_id: str = ""
    input_mapping: dict[str, str] | None = None
    config: TriggerConfigRequest | None = None
    created_by: str = "api"


class EnablePresetRequest(BaseModel):
    """Request body for enabling a trigger preset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    installation_id: str = ""
    created_by: str = "api"
    workflow_id: str = ""


class UpdateTriggerRequest(BaseModel):
    """Request body for updating (pause/resume) a trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["pause", "resume"]
    reason: str | None = None
    paused_by: str = "api"
    resumed_by: str = "api"


# ---------------------------------------------------------------------------
# Response models — Pydantic schemas for API consumers
# ---------------------------------------------------------------------------


class WorkflowSummary(BaseModel):
    """Summary of a workflow template for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    workflow_type: str
    classification: str
    phase_count: int
    description: str | None = None
    created_at: datetime | None = None
    runs_count: int = 0
    is_archived: bool = False
    requires_repos: bool = True
    tags: list[str] = Field(default_factory=list)
    """The workflow's tags, normalised and sorted (#967). Future runs inherit them."""
    """Whether this workflow requires repository access at execution time (ADR-058 #666)."""


class InputDeclarationResponse(BaseModel):
    """Input declaration within a workflow template."""

    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None


class PhaseRefResponse(BaseModel):
    """A plugin or skill reference. Structured, never a joined string.

    Joining source and name is not reversible: a ref whose source already
    ends in the repo name reparses to a different repository (#1013)."""

    source_url: str | None = None
    name: str | None = None
    version: str | None = None
    name_overridden: bool = False
    raw: str | None = None
    """The shorthand spelling when the stored row held a bare string."""


class FallbackAgentResponse(BaseModel):
    """The agent a phase is re-run on when its own provider cannot serve it (PC-83)."""

    provider: str
    model: str | None = None


class PhaseDefinitionResponse(BaseModel):
    """Phase definition within a workflow template."""

    phase_id: str
    name: str
    order: int = 0
    description: str | None = None
    agent_type: str = ""
    prompt_template: str | None = None
    timeout_seconds: int = 300
    max_cost_usd: float | None = None
    """The most this phase may spend, in USD, before it is stopped. None is unbounded."""
    allowed_tools: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    model: str | None = None
    """The model as DEFINED: often a platform alias (``opus``, ``gpt-sol``)."""
    resolved_model: ResolvedModelId | None = None
    """The concrete id this phase will run as: the alias target, or the provider
    default when ``model`` is unset or belongs to the other provider (the rule
    execution applies). ``None`` when ``model`` is already concrete or unknown.
    A definition-time expectation, not what a run used: runs report their
    observed model (ADR-067 D9)."""
    resolution_basis: AliasResolutionBasis | None = None
    """``translated``: the platform rewrites the alias itself (codex), so the
    target is what runs. ``expected``: the CLI resolves it (claude), so the
    target is what the pinned CLI is expected to pick. ``None`` with no alias."""
    model_display: str | None = None
    """``model`` plus its resolution, e.g. ``gpt-sol → gpt-6.1-sol``, or
    ``default → gpt-sol → gpt-6.1-sol`` when execution substitutes the
    provider default; the bare model when there is nothing to resolve. Render
    verbatim."""
    provider: str | None = None
    # Stored since #1012, readable since #1013. `allow_delegation` is
    # security-relevant -- it stages both agent auths -- so a caller must be
    # able to see it.
    allow_delegation: bool = False
    # The obligation beside the permission (#894): a phase declaring it fails
    # unless its delegate succeeded.
    require_delegation: bool = False
    # PC-83: re-run once on this agent after capacity outlived the retries, or
    # a spent quota. None when the phase declared no fallback.
    fallback_agent: FallbackAgentResponse | None = None
    clone_repos: bool = True
    delivers_repo_changes: bool = True
    # PC-116: the phase fails when it reports no review_verdict.
    requires_verdict: bool = False
    sandbox: str = DEFAULT_PHASE_SANDBOX
    claude_plugins: list[PhaseRefResponse] = Field(default_factory=list)
    skills: list[PhaseRefResponse] = Field(default_factory=list)
    execution_type: str = "sequential"
    max_tokens: int | None = None
    input_artifact_types: list[str] = Field(default_factory=list)
    output_artifact_types: list[str] = Field(default_factory=list)


class WorkflowDetail(BaseModel):
    """Detailed workflow template response."""

    id: str
    name: str
    description: str | None = None
    workflow_type: str
    classification: str
    phases: list[PhaseDefinitionResponse] = Field(default_factory=list)
    input_declarations: list[InputDeclarationResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    runs_count: int = 0
    repository_url: str | None = None
    """Template-level repository URL (single-repo workflows)."""
    repos: list[str] = Field(default_factory=list)
    """Default GitHub URLs for multi-repo workspace hydration (ADR-058)."""
    requires_repos: bool = True
    tags: list[str] = Field(default_factory=list)
    """The workflow's tags, normalised and sorted (#967). Future runs inherit them."""
    default_eval_id: str | None = None
    """The eval a launch naming none joins (#967). Future runs only."""
    package_name: str | None = None
    """Package that installed this definition (#1588); None when it was not
    installed from a package or predates install provenance."""


class PhaseProgressInfo(BaseModel):
    """How far through its phases an execution is, skipped phases accounted for.

    ``total_phases`` is what the workflow defines, and a review that certifies
    skips the repair rounds after it (PC-63), so ``completed/total`` read
    "6/10" for a run that finished. Clients render ``display`` and draw
    ``percent``; they never divide the raw counts themselves.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    completed: int
    """Phases that ran to completion."""
    skipped: int
    """Phases a review verdict made unnecessary; they will never run."""
    possible: int
    """The most phases this run can complete: defined, less the skipped."""
    remaining_possible: int
    """Phases that could still run. Zero once the run has ended."""
    percent: int
    """Completed as a share of ``possible``, 0-100. A completed run is 100."""
    display: str
    """E.g. ``6 of 6 (2 phases not needed)``, ``phase 3 of up to 8``."""

    @classmethod
    def of(cls, progress: PhaseProgress) -> PhaseProgressInfo:
        """The response shape of the domain's answer."""
        return cls(
            completed=progress.completed,
            skipped=progress.skipped,
            possible=progress.possible,
            remaining_possible=progress.remaining_possible,
            percent=progress.percent,
            display=progress.display,
        )

    @classmethod
    def without_skips(cls, status: str, completed: int, defined: int) -> PhaseProgressInfo:
        """Progress from a run result, which carries no skips.

        The list and detail reads, built from NextPhaseReady, are where skips
        are counted.
        """
        return cls.of(PhaseProgress(status=status, completed=completed, skipped=0, defined=defined))


class PlannedPhaseInfo(BaseModel):
    """One phase the run declared, and where it stands (feedback cee46909).

    ``ExecutionDetail.phase_plan`` lists every declared phase, so a client
    shows what is left as well as what ran. Clients render ``status_display``
    and style by ``status``; they never work the status out themselves.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    name: str
    status: str
    """``pending``, ``skipped`` (a review made it unnecessary), ``inherited``
    (completed by the run this one resumed), or the status of the phase as it
    ran here: ``running``, ``completed``, ``failed``, ..."""
    status_display: str
    """E.g. ``Pending``, ``Skipped (not needed)``, ``Inherited (completed earlier)``."""

    @classmethod
    def of(cls, phase: PlannedPhase) -> PlannedPhaseInfo:
        """The response shape of the domain's answer."""
        return cls(
            phase_id=phase.phase_id,
            name=phase.name,
            status=phase.status,
            status_display=phase.status_display,
        )


class ExecutionSummary(BaseModel):
    """Summary of a workflow execution run."""

    model_config = ConfigDict(from_attributes=True)

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    completed_phases: int = 0
    total_phases: int = 0
    phase_progress: PhaseProgressInfo
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cost_usd: Decimal | str = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    tool_call_count: int = 0
    error_message: str | None = None
    failure_classification: FailureClassification = FailureClassification.UNCLASSIFIED
    """What kind of failure ended this run, beside `status` (#1357).

    `status` says the run did not deliver; this says WHAT to do about it. The
    machinery broke (`platform`, fix it); or a phase judged the work not
    deliverable and was recorded faithfully (`correct_refusal`, read it and
    close it) - the system working. `unclassified` is a run nobody classified:
    a run that ended before anything recorded the difference, every failure
    predating the field, and a phase that reported it could not tell.
    `task` - the request itself was wrong - is a member nothing produces
    today; see `reported_failure_reason`.

    THIS IS A MEASUREMENT AND NOT A REPORT (#1392), which is the whole reason
    it is a separate field from `reported_failure_reason` beside it. Every
    failure NUMBER is computed from this one, so nothing a phase can write
    about itself decides it: a phase that names its own cause is heard, in the
    other field, and the only thing its word can do to this one is WITHDRAW a
    claim by saying it could not tell.

    Served rather than derived by the caller: the CLI and the dashboard are
    where failure rates are read off, and a consumer left to infer this from
    `error_message` prose is a consumer that will infer it differently from
    every other consumer.
    """
    reported_failure_reason: ReportedFailureReason | None = None
    """The word the failing phase wrote for what caused it, if it wrote one (#1392).

    WHAT THE AGENT SAID, never what the platform found - that is
    `failure_classification` above, and the two are deliberately one field
    apart so a reader can see both at once rather than having to know which
    they are holding. The only corroboration behind anything here is that the
    process exited cleanly and its stream arrived intact, which is evidence
    about the harness and not about whether the task was possible. So it is
    shown to an operator as a quotation - "the agent reported: task" - and no
    failure rate is computed from it.

    `None` means the phase named no cause this reader knows: no key (every
    report written before #1372), a misspelling, or a value of the wrong type.
    Distinct from `unknown`, which is the word a phase writes to say it could
    not tell, and which is the one report that moves the classification - to
    `unclassified`, withdrawing the claim that anything was established.
    """
    repos: list[str]
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""
    tags: list[str] = Field(default_factory=list)
    """The execution's current tags, normalised and sorted (#967)."""


class ExecutionDetail(BaseModel):
    """Detailed workflow execution response."""

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cost_usd: Decimal | str = Decimal("0")
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

    `status` says the run did not deliver; this says WHAT to do about it. The
    machinery broke (`platform`, fix it); or a phase judged the work not
    deliverable and was recorded faithfully (`correct_refusal`, read it and
    close it) - the system working. `unclassified` is a run nobody classified:
    a run that ended before anything recorded the difference, every failure
    predating the field, and a phase that reported it could not tell.
    `task` - the request itself was wrong - is a member nothing produces
    today; see `reported_failure_reason`.

    THIS IS A MEASUREMENT AND NOT A REPORT (#1392), which is the whole reason
    it is a separate field from `reported_failure_reason` beside it. Every
    failure NUMBER is computed from this one, so nothing a phase can write
    about itself decides it: a phase that names its own cause is heard, in the
    other field, and the only thing its word can do to this one is WITHDRAW a
    claim by saying it could not tell.

    Served rather than derived by the caller: the CLI and the dashboard are
    where failure rates are read off, and a consumer left to infer this from
    `error_message` prose is a consumer that will infer it differently from
    every other consumer.
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

    WHAT THE AGENT SAID, never what the platform found - that is
    `failure_classification` above, and the two are deliberately one field
    apart so a reader can see both at once rather than having to know which
    they are holding. The only corroboration behind anything here is that the
    process exited cleanly and its stream arrived intact, which is evidence
    about the harness and not about whether the task was possible. So it is
    shown to an operator as a quotation - "the agent reported: task" - and no
    failure rate is computed from it.

    `None` means the phase named no cause this reader knows: no key (every
    report written before #1372), a misspelling, or a value of the wrong type.
    Distinct from `unknown`, which is the word a phase writes to say it could
    not tell, and which is the one report that moves the classification - to
    `unclassified`, withdrawing the claim that anything was established.
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
    repos: list[str]
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""
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


class SessionSummary(BaseModel):
    """Summary of an agent session."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    #: The session that delegated to this one, when it is a delegate (#895).
    #: Present in the domain read model and previously dropped at this boundary,
    #: so a caller could not tell a delegate from a leader - the linkage existed
    #: and nothing could read it.
    parent_session_id: str | None = None
    #: The top of the delegation chain. Equal to ``id`` for a leader.
    root_session_id: str | None = None
    status: str = ""
    agent_type: str = ""
    repos: list[str] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ArtifactSummary(BaseModel):
    """Summary of an artifact."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str | None = None
    #: Which run produced it (#1306). The row has always carried it; the list
    #: did not report it, so a client that asked for one execution's artifacts
    #: could not tell from the answer whether it had got them. Reported as well
    #: as filtered on, because a filter a client cannot verify is what the
    #: silent drop looked like from outside.
    execution_id: str | None = None
    phase_id: str | None = None
    artifact_type: str = ""
    title: str | None = None
    size_bytes: int = 0
    created_at: datetime | None = None
    #: Who produced it (#1284). Same two facts as on ArtifactDetail, carried on
    #: the row because the list is where "which models ran this execution's
    #: phases" is asked. None on either means not reported, never "as
    #: configured".
    agent_provider: str | None = None
    agent_model: ObservedModelId | None = None


# ---------------------------------------------------------------------------
# Tag edit models (#967)
# ---------------------------------------------------------------------------


class AddTagsRequest(BaseModel):
    """Tags to add to an execution or a workflow. Adds only: never replaces the set."""

    model_config = ConfigDict(extra="forbid")

    tags: TagSet = Field(
        description=(
            "Tags to add. Normalised (trimmed, lowercased, deduped); an invalid tag is "
            "rejected with 422 and nothing is written. Tags already present are a no-op."
        ),
    )


class ExecutionTagsResponse(BaseModel):
    """An execution's tags after an edit, read from the aggregate, not a projection."""

    execution_id: str
    tags: list[str]
    """The execution's current tags, normalised and sorted. What `?tag=` filters on."""
    inherited_tags: list[str]
    """The tags it launched with. A record of the launch: no edit ever changes it."""


class WorkflowTagsResponse(BaseModel):
    """A workflow's tags after an edit, read from the aggregate, not a projection."""

    workflow_id: str
    tags: list[str]
    """The workflow's tags, normalised and sorted. Future runs inherit them."""


class AttachEvalRequest(BaseModel):
    """The eval to attach an execution to (#967)."""

    model_config = ConfigDict(extra="forbid")

    eval_id: EvalId = Field(
        description=(
            "The eval to attach to. It must exist and not be archived. Attaching to the "
            "eval the run already belongs to is a no-op; another eval needs a detach first."
        ),
    )


class ExecutionEvalResponse(BaseModel):
    """An execution's eval membership after an edit, read from the aggregate (#967)."""

    execution_id: str
    eval_id: str | None
    """The eval the run belongs to now, or null if it belongs to none."""
    association_kind: Literal["launched", "attached"] | None
    """How it joined: chosen at launch, or attached afterwards. Null with no eval."""
    launched_eval_id: str | None
    """The eval the launch chose. A record of the launch: a detach never clears it."""


class SetDefaultEvalRequest(BaseModel):
    """The eval a workflow's runs join when the launch names none (#967)."""

    model_config = ConfigDict(extra="forbid")

    eval_id: EvalId | None = Field(
        description=(
            "The default eval, which must exist and not be archived. Null clears it. "
            "Runs already started keep the eval they launched into."
        ),
    )


class WorkflowDefaultEvalResponse(BaseModel):
    """A workflow's default eval after an edit, read from the aggregate (#967)."""

    workflow_id: str
    default_eval_id: str | None


class EvalBaselineRepoRequest(BaseModel):
    """One repository of a new eval's Baseline, before its ref is pinned (#967)."""

    model_config = ConfigDict(extra="forbid")

    repository: str = Field(description="The repository, as an `owner/name` slug.")
    requested_ref: str = Field(
        min_length=1,
        description=(
            "A branch, tag or commit. Resolved once, at create, to a full commit SHA; "
            "every run starts from that SHA even after the branch or tag moves."
        ),
    )


class CreateEvalRequest(BaseModel):
    """A new eval (#967). The server mints its id; see `EvalCreatedResponse`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, description="What the eval sets out to measure.")
    starting_workflow_id: str | None = Field(
        default=None, min_length=1, description="The workflow a run uses when it names none."
    )
    baseline_repos: list[EvalBaselineRepoRequest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EvalBaselineRepoResponse(BaseModel):
    """One repository of an eval's Baseline: the ref asked for and the SHA it pinned to."""

    repository: str
    """The repository, as an `owner/name` slug."""
    requested_ref: str
    commit_sha: str


class EvalCreatedResponse(BaseModel):
    """The receipt for a create, read from the Eval aggregate, never a projection (#967).

    The eval list and `GET /evals/{eval_id}` are read models and may not show
    the eval for a moment after this returns. That is lag, not a failed create:
    `eval_id` is authoritative from here on.
    """

    eval_id: str
    name: str
    goal: str
    starting_workflow_id: str | None
    baseline_repos: list[EvalBaselineRepoResponse]
    """Each ref the request named, with the commit SHA it resolved to."""
    tags: list[str]


class EvalArchivedResponse(BaseModel):
    """The receipt for an archive, read from the Eval aggregate (#967)."""

    eval_id: str
    archived: bool


class EvalRunStatsResponse(BaseModel):
    """How long a set of an eval's runs took and what it cost, over EVERY run in the set.

    Medians, not means: one runaway run should not make a variant look slow.
    """

    median_duration_seconds: float | None
    """Median over the runs whose duration is known and complete. Null when none is.

    A run with a phase of unknown duration has only a lower bound and is left out."""
    median_duration_display: str
    """Says how many runs it left out, e.g. ``"2m 14s (excl. 1 incomplete)"``."""
    incomplete_duration_count: int
    """Runs left out of the median duration: unknown, or only a lower bound."""
    median_cost_usd: Decimal | None
    """Median over the runs whose cost is known and complete. Null when none is.

    A run with unpriced observations has only a lower bound and is left out."""
    median_cost_display: str
    """Says how many runs it left out, e.g. ``"$1.20 (excl. 1 incomplete)"``."""
    incomplete_cost_count: int
    """Runs left out of the median cost: unknown, or only a lower bound."""
    cost_per_pass_usd: Decimal | None
    """Known spend of the SCORED runs (PASS, FAIL and ERROR) over the PASS runs.

    Unscored runs are left out: they have no verdict yet. Null when nothing
    passed or no cost is known."""
    cost_per_pass_display: str
    """Says it is a lower bound when some scored run's cost is unknown or incomplete."""


class EvalVariantResponse(BaseModel):
    """Every run of an eval with the same workflow, workflow version and OBSERVED models.

    (Evals v2.) Two versions of one workflow are two variants: an edit between
    runs is a different treatment, and pooling them would hide its effect.
    """

    workflow_id: str
    workflow_version: str | None = None
    """The installed version (or source digest) the runs launched from. Null if unrecorded."""
    models: list[ObservedModelId]
    """Sorted, unique models the runs' phases reported running. Never an alias."""
    run_count: int
    pass_count: int
    pass_rate: float | None
    """PASS over this variant's PASS + FAIL runs, 0..1 (ERROR excluded). Null when none."""
    pass_rate_display: str
    avg_cost_usd: Decimal | None
    """Mean over the runs whose cost is known and complete. Null when none is."""
    avg_cost_display: str
    last_run_at: str | None
    last_verdict: Verdict | None
    """The verdict of this variant's newest run that has one."""
    stats: EvalRunStatsResponse


class EvalResponse(BaseModel):
    """An eval as the eval read model holds it, with its run tally (#967)."""

    eval_id: str
    name: str
    goal: str
    starting_workflow_id: str | None
    baseline_repos: list[EvalBaselineRepoResponse]
    tags: list[str]
    frozen: bool
    """True once a run was admitted: the goal and Baseline can no longer change."""
    archived: bool
    created_at: str | None
    updated_at: str | None
    run_count: int
    """Executions currently in the eval. A detached run is not counted."""
    run_status_counts: dict[str, int]
    """Those executions tallied by execution status."""
    scored_count: int = 0
    """Runs with a score. ``ERROR`` counts as scored, and is left out of the pass rate."""
    pass_rate: float | None = None
    """PASS over PASS + FAIL runs, 0..1 (ERROR excluded). Null when there are none."""
    pass_rate_display: str = EM_DASH
    last_run_at: str | None = None
    """When the newest run started, ISO 8601 UTC."""
    last_verdict: Verdict | None = None
    """The verdict of the newest run that has one."""
    variants: list[EvalVariantResponse] = Field(default_factory=list)
    """The eval's runs grouped by workflow and the models its phases actually ran."""
    stats: EvalRunStatsResponse
    """Duration and cost over every current run, all variants together."""


class EvalRunModelResponse(BaseModel):
    """The model one phase of a run ACTUALLY ran, as its harness reported it."""

    phase_id: str
    model: ObservedModelId


class EvalRunResponse(BaseModel):
    """One run of an eval: one data point of how the eval changes over time (Evals v2)."""

    execution_id: str
    started_at: str | None
    completed_at: str | None
    status: str
    workflow_id: str
    workflow_version: str | None = None
    """The workflow's installed version (or source digest, when it has no version)
    as the run launched it, recorded on the run's start event. Null for a run
    started before that was recorded, a resume, or a template with neither."""
    models: list[EvalRunModelResponse]
    """Observed per phase; a phase with no reported model is omitted."""
    total_cost_usd: Decimal | None
    total_cost_display: str
    duration_seconds: float | None
    duration_display: str
    verdict: Verdict | None
    score: float | None
    evidence_excerpt: str | None
    """The start of the scorer's markdown evidence; the full text is on the score."""
    scorer: str | None
    scorer_version: str | None
    scored_at: str | None


class EvalRunListResponse(BaseModel):
    """One page of an eval's current runs, newest first (Evals v2)."""

    items: list[EvalRunResponse]
    total: int
    """Every current run of the eval, whatever the page size."""
    page: int
    page_size: int


class EvalRunScoreRequest(BaseModel):
    """A scorer's verdict on one run of an eval. Re-scoring replaces the current score."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: str = ""
    """Markdown."""
    scorer: str = Field(min_length=1)
    scorer_version: str = Field(min_length=1)


class EvalRunScoreResponse(BaseModel):
    """The run's score as recorded (Evals v2)."""

    eval_id: str
    execution_id: str
    verdict: Verdict
    score: float | None
    evidence: str
    scorer: str
    scorer_version: str
    scored_at: str


class ExecutionEvalRunResponse(BaseModel):
    """The eval an execution is a run of, and that run's current verdict (Evals v2).

    Carried on ``GET /executions/{id}`` so an execution page can link to its eval
    and show how the run was judged without a second request.
    """

    eval_id: str
    eval_name: str | None
    """The eval's name. Null only while the eval's own record has not been projected."""
    association_kind: Literal["launched", "attached"]
    """How the run joined: chosen at launch, or attached afterwards."""
    verdict: Verdict | None
    """The run's current verdict. Null until a scorer records one."""
    score: float | None
    scored_at: str | None
    """When the current verdict was recorded, ISO 8601 UTC."""


class ReadModelStatus(BaseModel):
    """Whether one read model is rebuilding, and how far it has got.

    Carried on the list and detail responses a read model serves, so a page can
    say "this list is incomplete because it is being rebuilt" instead of
    looking broken, and listed on ``/health`` for every read model that is
    rebuilding. Judged by ``services.read_model_status``; every number is
    exact (checkpoint position against store head), never estimated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rebuilding: bool = Field(
        description="True while this read model is replaying history: it is more than the "
        "live-lag threshold (500 events) behind the head. A few events of ordinary live lag "
        "is NOT rebuilding, even while another read model replays.",
    )
    projection: str = Field(description="Projection name, as in projection_checkpoints.")
    label_display: str = Field(
        description="What the read model holds, for a sentence, e.g. 'execution history'."
    )
    progress_pct: int | None = Field(
        default=None,
        description="Checkpoint position as a whole percentage of the store head, 0-99 while "
        "rebuilding. Null when not rebuilding.",
    )
    progress_display: str | None = Field(default=None, description="progress_pct as '72%'.")
    events_behind: int = Field(
        default=0, description="Events between the checkpoint and the store head."
    )
    events_behind_display: str | None = Field(
        default=None, description="events_behind as '29,476 events behind'."
    )
    summary_display: str | None = Field(
        default=None,
        description="One sentence for a banner, e.g. 'Rebuilding execution history - 72% "
        "(29,476 events behind).' Null when not rebuilding.",
    )


class EvalDetailResponse(EvalResponse):
    """One eval, as `GET /evals/{eval_id}` returns it.

    The row model plus whether the evals read model is rebuilding, so a
    missing or stale eval can say why. Kept off `EvalResponse` so every list
    row does not repeat the list's own status.
    """

    read_model_status: ReadModelStatus | None = None
    """Whether the evals read model is rebuilding."""


class EvalListResponse(BaseModel):
    """One page of evals, newest first (#967)."""

    evals: list[EvalResponse]
    total: int
    """Evals matching every filter, before paging."""
    page: int
    page_size: int
    status_counts: dict[str, int]
    """Matching evals tallied as `active` / `archived`, ignoring the status filter."""
    read_model_status: ReadModelStatus | None = None
    """Whether the evals read model is rebuilding, so a short list can say why."""


# ---------------------------------------------------------------------------
# Organization models
# ---------------------------------------------------------------------------


class OrganizationSummaryResponse(BaseModel):
    """Summary of an organization for list views."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: str
    name: str
    slug: str
    created_by: str = ""
    created_at: datetime | None = None
    system_count: int = 0
    repo_count: int = 0


class SystemSummaryResponse(BaseModel):
    """Summary of a system for list views."""

    model_config = ConfigDict(from_attributes=True)

    system_id: str
    organization_id: str
    name: str
    description: str = ""
    created_by: str = ""
    created_at: datetime | None = None
    repo_count: int = 0


class RepoSummaryResponse(BaseModel):
    """Summary of a repo for list views."""

    model_config = ConfigDict(from_attributes=True)

    repo_id: str
    organization_id: str
    system_id: str = ""
    provider: str = "github"
    full_name: str = ""
    owner: str = ""
    default_branch: str = "main"
    installation_id: str = ""
    is_private: bool = False
    created_by: str = ""
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Trigger models
# ---------------------------------------------------------------------------


class TriggerSummary(BaseModel):
    """Summary of a trigger rule for list views."""

    model_config = ConfigDict(from_attributes=True)

    trigger_id: str
    name: str
    event: str
    repository: str
    workflow_id: str
    workflow_name: str = ""
    status: str
    fire_count: int = 0
    created_at: datetime | None = None


class TriggerDetail(BaseModel):
    """Detailed trigger rule response."""

    trigger_id: str
    name: str
    event: str
    repository: str
    workflow_id: str
    workflow_name: str = ""
    status: str
    fire_count: int = 0
    created_at: datetime | None = None
    conditions: list[dict] = Field(default_factory=list)
    input_mapping: dict[str, str] = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    installation_id: str = ""
    created_by: str = ""
    last_fired_at: datetime | None = None


class TriggerHistoryEntry(BaseModel):
    """A single entry in a trigger's execution history."""

    trigger_id: str
    execution_id: str
    webhook_delivery_id: str = ""
    github_event_type: str = ""
    repository: str = ""
    pr_number: int | None = None
    fired_at: datetime | None = None
    status: str = "dispatched"
    cost_usd: float | None = None
    guard_name: str = ""
    block_reason: str = ""


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class ConfigSnapshot(BaseModel):
    """Snapshot of the current application configuration."""

    app: dict = Field(default_factory=dict)
    database: dict = Field(default_factory=dict)
    storage: dict = Field(default_factory=dict)


class ConfigIssue(BaseModel):
    """A configuration issue found during validation."""

    level: str  # "error" | "warning" | "info"
    category: str
    message: str


# ---------------------------------------------------------------------------
# Workflow validation model
# ---------------------------------------------------------------------------


class WorkflowValidation(BaseModel):
    """Result of validating a workflow YAML file."""

    valid: bool
    name: str | None = None
    workflow_type: str | None = None
    phase_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    """Notices that never make the file invalid, e.g. a retired key it still carries."""


# ---------------------------------------------------------------------------
# Execution detail models
# ---------------------------------------------------------------------------


class GitEventData(BaseModel):
    """Structured git event data from observability hooks.

    Field names match agentic_events.payloads dataclasses (single source of truth).
    This model is the Pydantic equivalent for API serialization.
    """

    model_config = ConfigDict(extra="forbid")

    operation: str | None = None
    sha: str | None = None
    branch: str | None = None
    repo: str | None = None
    message: str | None = None
    prev_branch: str | None = None
    is_clone: bool | None = None
    remote: str | None = None
    author: str | None = None
    files_changed: int | None = None
    insertions: int | None = None
    deletions: int | None = None
    commits_count: int | None = None
    commit_range: str | None = None
    remote_url: str | None = None
    details: str | None = None
    from_branch: str | None = None
    to_branch: str | None = None
    estimated_tokens_added: int | None = None
    estimated_tokens_removed: int | None = None


class ToolOperation(BaseModel):
    """A single timeline event within a session.

    Covers tool executions, git operations, subagent lifecycle, and other
    observability events. Use operation_type to distinguish categories.
    """

    model_config = ConfigDict(from_attributes=True)

    observation_id: str = ""
    operation_type: str = ""
    timestamp: datetime | None = None
    duration_ms: float | None = None
    success: bool | None = None
    error_message: str | None = None
    """Why this operation's subject went wrong, for the rows that failed.

    Carried from `syn_adapters.projections.session_tools.ToolOperation` by
    `model_validate(from_attributes=True)`; the two names must stay identical
    or it is silently dropped here (#1196).
    """
    # Tool-specific fields
    tool_name: str | None = None
    tool_use_id: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    skill_name: str | None = None
    """The skill a `Skill` call invoked, recorded whole on its start (#1269).

    Carried from `syn_adapters.projections.session_tools.ToolOperation` by
    `model_validate(from_attributes=True)`; the names must stay identical.
    """
    # Structured git data (v2 events - preferred).
    # AliasChoices: JSON clients send "git", from_attributes reads "git_data"
    # from the projection dataclass (which uses git_data to avoid shadowing).
    git: GitEventData | None = Field(
        None,
        validation_alias=AliasChoices("git", "git_data"),
    )
    # Flat git fields (deprecated - use git sub-object instead)
    git_sha: str | None = None
    git_message: str | None = None
    git_branch: str | None = None
    git_repo: str | None = None


class PinnedSkillInfo(BaseModel):
    """One skill a phase was given at start, at the version it was resolved to (#1454)."""

    name: str
    version: str
    """The version as declared - a tag, branch or sha."""
    resolved_sha: str
    """Content hash of the skill tree the workspace was actually given."""
    source_url: str


StartPinsStatus = Literal["recorded", "not_recorded", "unavailable"]
"""Whether a phase's `pinned_at_start` could be answered (#1454).

``recorded``: the start event carried this phase's pins. ``not_recorded``: the
start event was read and carries none - an execution from before #1454.
``unavailable``: the start event could not be read on this request, so nothing
is known either way. Only ``not_recorded`` may be shown as "not recorded"."""


class PhaseStartConfig(BaseModel):
    """What a phase was configured with when its execution STARTED.

    Read from the execution's own start event (`StartPins`, #1454), never from
    the workflow template, which may have been edited since. That is the whole
    point: this answers "what did the agent have", not "what would it get now".
    """

    provider: str
    requested_model: str | None = None
    """The model the phase ASKED for at start, possibly an alias such as
    ``opus`` (ADR-067 D9: a request, not the harness-reported id). None when
    the phase named none."""
    allowed_tools: list[str] = Field(default_factory=list)
    """Empty means the phase declared no restriction, so the harness ran with
    its own default tool set - not that the agent had no tools."""
    skills: list[PinnedSkillInfo] = Field(default_factory=list)


SkillUseStatus = Literal["observed", "not_observable", "unavailable"]
"""Whether a phase's skill USE could be read (#1269).

``observed``: a claude phase whose timeline was read, so ``invoked`` is a
measurement and an empty list means no skill was invoked. ``not_observable``:
the harness has no Skill tool (codex), so skills land as context and their use
leaves no signal - ``invoked`` is empty because nothing CAN be seen, never
because nothing was used. ``unavailable``: the start pins or the timeline could
not be read on this request, so nothing is known either way."""


class InvokedSkillInfo(BaseModel):
    """One skill the agent invoked through the Skill tool, and how often (#1269)."""

    name: str
    count: int
    """Calls, not timeline rows: a call's start and completion fold to one."""


class PhaseSkillUseInfo(BaseModel):
    """Which declared skills this phase actually used (#1269).

    Declaring a skill installs it; only an invocation shows the agent reached
    for it. This is the fact that tells the two apart, per phase.
    """

    status: SkillUseStatus = "unavailable"
    declared: list[str] = Field(default_factory=list)
    """Skill names from `pinned_at_start.skills` - what the execution STARTED
    with, never the template as it stands now."""
    invoked: list[InvokedSkillInfo] = Field(default_factory=list)
    """Meaningful only when `status` is ``observed``. May name a skill that was
    not declared: one installed some other way is still a skill the agent used."""

    @computed_field(
        description="Declared skills with no observed invocation. Empty unless "
        "status is 'observed': an unobservable use is not a non-use."
    )
    @property
    def declared_not_invoked(self) -> list[str]:
        """Derived, never passed in, so it cannot contradict the two lists."""
        if self.status != "observed":
            return []
        used = {s.name for s in self.invoked}
        return [name for name in self.declared if name not in used]


class BranchObservationInfo(BaseModel):
    """One branch of a failed phase's workspace, as git had it (#1200).

    THE ANSWER TO "WHERE DO I LOOK", made machine-readable. A phase can push
    complete work and still fail - most often because it wrote no deliverable,
    which #1167 correctly refuses to pass - and the failure then named no
    branch, so nothing pointed at commits that were merged by hand twice in one
    day once a human found them.

    EVERY FIELD IS A READING, NOT AN ATTRIBUTION. `remote_commit` is what the
    REMOTE ITSELF answered, asked while the workspace was still alive, and
    `remote_commit_at_phase_start` is where this clone's tracking ref pointed
    when the phase was handed that workspace. The two differing means the ref
    moved. It does NOT mean this phase moved it, and no field here says so: a
    push carries no author, so the same evidence is produced by a concurrent
    process or a person. Two earlier versions of this claimed otherwise.

    A RECORD EXISTS ONLY WHERE SOMETHING DIFFERS from how the phase found the
    repository - the ref moved, or commits are sitting on no remote. The FIELD
    is three-valued and the two empty answers must not be merged: absent/null
    means nothing could look, `[]` means the workspace was read and every
    branch is exactly where the phase found it. Only a moved ref can be
    recovered by fetching.
    """

    repo: str
    """The repository this reading is from, by directory name."""

    branch: str
    """The branch the workspace was on: no remote prefix, and the name a PR
    opens from. ``(detached HEAD)`` when it was not on one."""

    remote: str | None
    """The remote this reading is about, e.g. ``origin``. Null when the branch
    has no remote-tracking ref and had none at phase start."""

    remote_commit: str | None
    """Where the REMOTE said ``<branch>`` was when the phase failed, asked of
    it directly. Null means the remote does not have that branch: never
    pushed, or deleted while the phase ran. A remote that could not be reached
    yields no record at all, never a stale one."""

    remote_commit_at_phase_start: str | None
    """Where that same ref pointed when the phase was handed the workspace.
    Null means it did not exist then. Compare it with ``remote_commit`` to see
    whether the branch moved - that comparison is the whole claim being made,
    and it says nothing about who moved it."""

    unpushed_commits: int
    """Commits reachable from the workspace's HEAD that no remote ref holds.

    Non-zero is a DIFFERENT INCIDENT from a moved ref: those commits die with
    the container unless #1184's quarantine caught them, so there is nothing to
    fetch. This is what lets a client tell "this phase left nothing anywhere"
    from "this phase is holding work no remote has"."""


class PhaseActivityInfo(BaseModel):
    """What a phase was DOING when it ended, and against what budget (#1262).

    THE ANSWER TO "was it busy or was it stuck", for the one failure that
    cannot answer it itself. A phase killed on its deadline exits 124, and so
    does a phase that hung; the two need opposite responses - dispatch a
    continuation with a bigger budget, or do not pay for that run a second
    time - and until this model existed nothing in the execution record
    separated them. An operator had to open the transcript, and four runs in
    one day were triaged without one.

    Read as a whole, the fields are the triage:

    * many operations and a push moments before the end - it was working, and
      the budget was too short;
    * a handful of operations and no push for most of an hour - it stalled,
      and a bigger budget buys another stalled hour;
    * ``elapsed_seconds`` at or past ``timeout_seconds`` - it reached its cap,
      as against a 124 reported well inside the budget, which is some other
      death wearing the same exit code.

    Every field is a READING, never a verdict. Nothing here says "stalled":
    that word is a judgement about intent, and these are four measurements
    that let a reader make it.

    AND "WE COULD NOT SEE" IS A THIRD ANSWER, not a quiet fourth measurement.
    The activity readings come from Lane 2, which fails soft, and a lookup that
    raised or found no database once produced zero operations and no push -
    which is precisely the shape of a stall. The feature built to stop an
    operator being told "do not pay for this again" on no evidence was
    manufacturing exactly that signal out of its own outage.
    ``telemetry_available`` says whether the timeline was read at all, and the
    readings taken from it are null when it was not.
    """

    telemetry_available: bool = False
    """Whether this phase's Lane 2 timeline could be read at all.

    False means NOTHING BELOW THAT COMES FROM THE TIMELINE WAS MEASURED - the
    query raised, no database was reachable, or the phase never got a session
    to record against. It is NOT a statement about the phase, which may have
    been busy or stalled; it is a statement about this record.

    It is a field of its own rather than being left to be inferred from a null
    ``operations_count`` because ``last_push_at`` and
    ``seconds_since_last_push`` cannot carry the distinction themselves: null
    already means "no push was observed" there, and that is a real, and the
    most expensive, reading. One flag answers for all three.

    ``elapsed_seconds`` and ``timeout_seconds`` are unaffected - they come from
    the execution record, not from telemetry - so a phase whose timeline is
    unreadable can still be read against its cap. It is busy-versus-stalled
    that is withheld, and only that.

    It defaults to False so that an ``activity`` nobody summarised claims
    nothing, rather than claiming an idle phase.
    """

    operations_count: int | None = None
    """Operations this phase performed, as ``phases[].operations`` records them.

    ``None`` when ``telemetry_available`` is False, and ``0`` only when the
    timeline was read and held nothing. Both are answers and they are different
    answers; the sentinel that would merge them is not worth inventing, because
    zero is already a real one - a phase whose process never got anywhere did
    make no calls, and that says the failure is upstream of the agent.

    NOT ``len(operations)``, and the difference is not cosmetic: a tool call is
    two rows there, a start and a completion, so the list's length is about
    twice the work that happened, and was counted that way until #1061. This
    counts the CALLS, folding both rows of one call together by
    ``ToolOperation.call_identity``.

    Populated on a phase that was killed, which is the only reason it is worth
    serving: it is read per request from the Lane 2 timeline, where every row
    was written as its line arrived, so a phase that made 300 calls and then
    died reports 300. A field written only at a clean teardown would report
    nothing for exactly the runs this exists to triage.
    """

    last_push_at: datetime | None = None
    """When this phase last pushed, as the timeline observed it.

    ``None`` means NO PUSH WAS OBSERVED - including a phase whose work was
    never pushed at all, which is the strongest thing this model can say about
    lost work. It is not "pushed at time zero", and it is not a claim the push
    reached the remote: the observation is written when the push is initiated
    (the pre-push hook, ADR-043), so this is when the phase last TRIED.

    READ IT WITH ``telemetry_available``. The null above is an observation, and
    it is only an observation when something observed: with the flag False
    nothing looked, and no claim about pushing is being made here at all.

    Covers the legacy ``git_push_started``/``git_push_completed`` spellings as
    well as today's ``git_push``. A rule that knew one of the three would
    answer "never pushed" for a session recorded under another, which is the
    expensive direction to be wrong in - it reads as a stall.
    """

    seconds_since_last_push: float | None = None
    """Seconds from ``last_push_at`` to the end of the phase.

    The stall signal stated as the number an operator actually compares. "The
    end" is the same instant ``elapsed_seconds`` measures to: the completion
    for a phase that finished, and the moment of the read for one still
    running, so a live phase's silence grows while a dead one's is frozen.

    ``None`` when nothing was pushed - ``elapsed_seconds`` is then the whole
    answer, because the silence is the entire phase - or when the phase has no
    end to measure to, or when ``telemetry_available`` is False and there was
    no timeline to find a push in.
    """

    elapsed_seconds: float | None = None
    """How long the phase ran. The same measurement ``duration_seconds``
    reports on the phase itself, restated beside the budget it has to be read
    against, and taken from that one value rather than computed again.

    ``None`` is genuinely unknown, never zero.
    """

    timeout_seconds: int | None = None
    """The wall-clock budget the phase was given, from its workflow definition.

    ``None`` means the run stated no phase definitions and nothing knows the
    budget - not that there was none, and not zero.
    """

    deadline: datetime | None = None
    """When this phase is killed on its budget (#1546), in UTC: the moment its
    workspace was ready plus ``timeout_seconds``.

    Not ``started_at`` plus ``timeout_seconds``. The phase starts before its
    workspace is provisioned and its clock only after, so that sum is early by
    the provisioning time - which is why phases appeared to run past their
    limit. This is the deadline the agent is told as ``SYN_PHASE_DEADLINE``,
    to within the moment between the workspace being recorded ready and the
    agent being dispatched. Like that variable it is in whole seconds,
    truncated, so it is never later than the agent's.

    ``None`` until the workspace is ready, when the budget is unknown, or for
    a phase provisioned before this was recorded.
    """


class PhaseExecution(BaseModel):
    """Detailed phase execution with tool operations."""

    phase_id: str
    name: str
    status: str
    session_id: str | None = None
    artifact_id: str | None = None
    # Why a failed phase reports the reason it failed (#891): the projection
    # already writes error_message onto the phase record, and the HTTP model
    # already declares the field. This intermediate model was the one hop that
    # dropped it, so every failed phase surfaced error_message: null.
    error_message: str | None = None
    deliverable_recovered: bool = False
    """True when this phase completed on a deliverable recovered from its
    transcript rather than the file it declared (#1195, #1300).

    A salvaged phase COMPLETES - discarding a finished run over a missing
    report is the cost #1300 measured - so `status` alone cannot distinguish
    it, and this is the only field that can. It is here, on the record the API
    serves, and not only on `PhaseCompletedEvent`, because a fact that reaches
    no read model reaches no reader.
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
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    duration_seconds: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    model: ObservedModelId | None = None
    """The model the harness REPORTED for this phase, or None (ADR-067 D9).

    Never an alias: what the phase asked for is ``requested_model``.
    """
    requested_model: str | None = None
    """The model the phase REQUESTED (often an alias such as ``opus``), or None."""
    agent_provider: str | None = None
    """The provider of the agent that PRODUCED this phase's result, or null
    (PC-83). Differs from the declared provider when the phase fell back to its
    ``fallback_agent`` on capacity or quota; ``requested_model`` is then the
    fallback's model. Null when nothing recorded it."""
    cost_by_model: dict[CostModelKey, Decimal] = Field(default_factory=dict)
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

    The end of the chain the status travels: event -> projection record ->
    read model -> here (#1319). `null` is "nothing observed a status" - which
    includes every phase that did not fail - and is not the claim that it
    exited 0. 124 means the phase reached its time budget and -11 that it was
    killed, which is the distinction a client needs to decide between
    continuing the work and retrying it.
    """
    observed_branches: list[BranchObservationInfo] | None = None
    """Where this failed phase's branches stood when it died (#1200).

    Three-valued exactly as `BranchObservationInfo` describes. Defaulting to
    `[]` here, or anywhere below, would tell an API client that a workspace was
    verifiably unchanged when in truth nothing looked.
    """
    pinned_at_start: PhaseStartConfig | None = None
    """What this phase had at start: tools, skills and model (#1454).

    Null is never filled in from the current template; `start_pins_status`
    says why it is null.
    """
    start_pins_status: StartPinsStatus = "unavailable"
    """Why `pinned_at_start` is or is not set. Defaults to ``unavailable``: a
    constructor that never read the start event must not claim it was empty."""
    skill_use: PhaseSkillUseInfo = Field(default_factory=PhaseSkillUseInfo)
    """Skills declared against skills invoked, for this phase (#1269)."""
    operations: list[ToolOperation] = Field(default_factory=list)
    activity: PhaseActivityInfo = Field(default_factory=PhaseActivityInfo)
    """What this phase was doing when it ended, summarised from `operations`
    and the phase's budget (#1262).

    Summarised HERE, one hop before the response, rather than at the response
    boundary: the count has to fold a call's two rows together by
    `ToolOperation.call_identity`, and that rule lives on the projection's
    dataclass, which is the shape `_map_phase_detail` still holds and this
    model no longer does.
    """

    @computed_field(
        description="The model for humans: the reported id verbatim, or "
        "'unknown (requested: <alias>)', or 'unknown' (ADR-067 D9)."
    )
    @property
    def model_display(self) -> str:
        """Derived, never passed in, so it cannot contradict ``model``."""
        return format_observed_model(self.model, self.requested_model)


class ExecutionDetailFull(BaseModel):
    """Rich execution detail with phases and tool operations."""

    workflow_execution_id: str
    workflow_id: str
    workflow_name: str
    status: str
    phases: list[PhaseExecution] = Field(default_factory=list)
    total_phases: int = 0
    """Phases this run set out to do. Not ``len(phases)``: a run that died in
    phase one carries one phase and a total of 3, and the gap is the phases
    that never started (#1147)."""
    completed_phases: int = 0
    phase_progress: PhaseProgressInfo
    phase_plan: list[PlannedPhaseInfo]
    """Every phase the run declared, in order, with where each stands. Counts
    the same phases ``total_phases`` does; ``phases`` is only the ones that ran."""
    total_tokens: int = 0
    total_cost_usd: Decimal | str = Decimal("0")
    unpriced_observation_count: int = 0
    total_duration_seconds: float | None
    """Wall-clock seconds across the execution's phases, including any still
    running (#969). ``None`` means no phase had a resolvable duration.

    REQUIRED, deliberately. This model is internal, has exactly one construction
    site, and always has a source value. A default here would recreate the class
    of bug this field exists to fix: an omitted argument silently becoming 0.0,
    which pyright cannot see because omitting a defaulted field is legal.
    """
    unknown_duration_phase_count: int = 0
    """Phases whose duration is unknown and so contributed nothing to the total.

    Non-zero means ``total_duration_seconds`` is a LOWER BOUND, not the total
    (same contract as ``unpriced_observation_count`` for cost, #890).
    """
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    error_message: str | None = None
    failure_classification: FailureClassification = FailureClassification.UNCLASSIFIED
    """What kind of failure ended this run, beside `status` (#1357).

    `status` says the run did not deliver; this says WHAT to do about it. The
    machinery broke (`platform`, fix it); or a phase judged the work not
    deliverable and was recorded faithfully (`correct_refusal`, read it and
    close it) - the system working. `unclassified` is a run nobody classified:
    a run that ended before anything recorded the difference, every failure
    predating the field, and a phase that reported it could not tell.
    `task` - the request itself was wrong - is a member nothing produces
    today; see `reported_failure_reason`.

    THIS IS A MEASUREMENT AND NOT A REPORT (#1392), which is the whole reason
    it is a separate field from `reported_failure_reason` beside it. Every
    failure NUMBER is computed from this one, so nothing a phase can write
    about itself decides it: a phase that names its own cause is heard, in the
    other field, and the only thing its word can do to this one is WITHDRAW a
    claim by saying it could not tell.

    Served rather than derived by the caller: the CLI and the dashboard are
    where failure rates are read off, and a consumer left to infer this from
    `error_message` prose is a consumer that will infer it differently from
    every other consumer.
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

    WHAT THE AGENT SAID, never what the platform found - that is
    `failure_classification` above, and the two are deliberately one field
    apart so a reader can see both at once rather than having to know which
    they are holding. The only corroboration behind anything here is that the
    process exited cleanly and its stream arrived intact, which is evidence
    about the harness and not about whether the task was possible. So it is
    shown to an operator as a quotation - "the agent reported: task" - and no
    failure rate is computed from it.

    `None` means the phase named no cause this reader knows: no key (every
    report written before #1372), a misspelling, or a value of the wrong type.
    Distinct from `unknown`, which is the word a phase writes to say it could
    not tell, and which is the one report that moves the classification - to
    `unclassified`, withdrawing the claim that anything was established.
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
    repos: list[str]
    """Full GitHub URLs of repositories cloned for this execution (ADR-058)."""
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


class ControlResult(BaseModel):
    """Result of a control command (pause/resume/cancel/inject)."""

    success: bool
    execution_id: str
    new_state: str
    message: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Session detail model
# ---------------------------------------------------------------------------


class SessionDetail(BaseModel):
    """Detailed session with tool operations and cost data."""

    id: str
    workflow_id: str | None = None
    workflow_name: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    #: The session that delegated to this one, when it is a delegate (#895).
    #: Present in the domain read model and previously dropped at this boundary,
    #: so a caller could not tell a delegate from a leader - the linkage existed
    #: and nothing could read it.
    parent_session_id: str | None = None
    #: The top of the delegation chain. Equal to ``id`` for a leader.
    root_session_id: str | None = None
    agent_type: str = ""
    status: str = ""
    workspace_path: str | None = None
    repos: list[str] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    unpriced_observation_count: int = 0
    """Observations that carried no usable rate and so added nothing to the total.

    Non-zero means the cost is INCOMPLETE, not that the work was free (#890).
    """
    agent_model: ObservedModelId | None = None
    """The model the harness REPORTED doing most of this session's work, or None."""
    requested_model: str | None = None
    """The model the session REQUESTED (often an alias), or None (ADR-067 D9)."""
    cost_by_model: dict[CostModelKey, Decimal] = Field(default_factory=dict)
    operations: list[ToolOperation] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None

    @computed_field(
        description="The model for humans: the reported id verbatim, or "
        "'unknown (requested: <alias>)', or 'unknown' (ADR-067 D9)."
    )
    @property
    def agent_model_display(self) -> str:
        """Derived, never passed in, so it cannot contradict ``agent_model``."""
        return format_observed_model(self.agent_model, self.requested_model)


# ---------------------------------------------------------------------------
# Artifact detail model
# ---------------------------------------------------------------------------


class ArtifactDetail(BaseModel):
    """Detailed artifact with optional content."""

    id: str
    workflow_id: str | None = None
    phase_id: str | None = None
    session_id: str | None = None
    artifact_type: str = ""
    title: str | None = None
    content: str | None = None
    content_type: str | None = None
    content_hash: str | None = None
    size_bytes: int = 0
    created_at: datetime | None = None
    agent_provider: str | None = None
    """Harness that ran the phase which produced this artifact (issue #1284).

    None means no phase produced it, or it predates ArtifactCreated v6.
    """
    agent_model: ObservedModelId | None = None
    """Model that harness ANNOUNCED while running, never the one requested.

    This is the field a cross-model review reads to prove a DIFFERENT model
    checked the work (#1284). None means the harness reported no model - true of
    every codex phase today - and a client MUST render it as "not reported"
    rather than falling back to the phase's configured model, which would look
    like evidence and be none.
    """


# ---------------------------------------------------------------------------
# Metrics + Cost models (merged)
# ---------------------------------------------------------------------------


class DashboardMetrics(BaseModel):
    """Aggregated dashboard metrics."""

    total_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    total_sessions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    total_artifacts: int = 0
    total_artifact_bytes: int = 0


class SessionCostData(BaseModel):
    """Cost data for a single session.

    Every field `SessionCostResponse` declares must appear here, or the
    response advertises it and always serves its default (#1041). The two
    field sets are compared in `test_dto_carries_every_response_field.py`.
    """

    session_id: str
    execution_id: str | None = None
    workflow_id: str | None = None
    phase_id: str | None = None
    workspace_id: str | None = None
    total_cost_usd: Decimal = Decimal("0")
    token_cost_usd: Decimal = Decimal("0")
    compute_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    """Sum of input, output, cache creation and cache read tokens (issue #873).

    Means the same thing as ``total_tokens`` on the executions read model.
    Excluding the cache components undercounted this by up to ~68x while
    cost stayed correct, because pricing reads the cache fields directly.
    """
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    duration_ms: int = 0
    cost_by_model: dict[CostModelKey, Decimal] = Field(default_factory=dict)
    cost_by_tool: dict = Field(default_factory=dict)
    tokens_by_tool: dict[str, int] = Field(default_factory=dict)
    cost_by_tool_tokens: dict[str, Decimal] = Field(default_factory=dict)
    unpriced_observation_count: int = 0
    """Observations whose model had no rate; non-zero means cost is INCOMPLETE."""
    unmeasured_fields: list[str] = Field(default_factory=list)
    """Names of fields ON THIS MODEL whose value was never measured.

    A field listed here holds its default, not a reading. Today that is always
    ``compute_cost_usd``, ``tokens_by_tool`` and ``cost_by_tool_tokens``: no
    read path can derive them from ``agent_events``.

    It is a list of names rather than nulls on the fields themselves because a
    null is as falsy as a zero, and a client writing ``x ?? 0`` erases the
    distinction exactly the way #1041 erased these fields for a month. A
    non-empty list is truthy and has to be read.
    """
    is_finalized: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExecutionCostData(BaseModel):
    """Cost data for an execution."""

    execution_id: str
    workflow_id: str | None = None
    session_count: int = 0
    session_ids: list[str] = Field(default_factory=list)
    total_cost_usd: Decimal = Decimal("0")
    token_cost_usd: Decimal = Decimal("0")
    compute_cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    """Sum of input, output, cache creation and cache read tokens (issue #873).

    Must equal ``total_tokens`` on ``/api/v1/executions/{id}`` for the same
    execution.
    """
    # These four were absent from this DTO, so the query service computed them
    # correctly and the mapping silently dropped them - the response then fell
    # back to its `= 0` defaults. An execution reported 0 cache reads and 0 tool
    # calls while its own sessions reported 144,640 and 11.
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    duration_ms: float = 0.0
    cost_by_phase: dict = Field(default_factory=dict)
    unpriced_by_phase: dict = Field(default_factory=dict)
    """Per-phase count of observations that could not be priced.

    A phase absent from ``cost_by_phase`` but present here cost an unknown
    amount; a phase in neither genuinely had no spend (#890).
    """
    cost_by_model: dict[CostModelKey, Decimal] = Field(default_factory=dict)
    cost_by_tool: dict = Field(default_factory=dict)
    is_complete: bool = False
    unpriced_observation_count: int = 0
    """Observations whose model had no rate, so they contributed no cost.

    Non-zero means the reported cost is INCOMPLETE, not that work was free.
    Surfaced so a client can render "unpriced" rather than "$0.00" (ADR-067 D5).
    """
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ModelCostEntry(BaseModel):
    """One model's share of a cost total."""

    model: CostModelKey
    """A reported model id, or ``unattributed-model``. Never an alias."""
    cost_usd: Decimal = Decimal("0")


class CostSummary(BaseModel):
    """Overall cost summary across all executions."""

    total_cost_usd: Decimal = Decimal("0")
    total_sessions: int = 0
    total_executions: int = 0
    total_tokens: int = 0
    """Sum of all four token components across executions (issue #873)."""
    total_tool_calls: int = 0
    top_models: list[ModelCostEntry] = Field(default_factory=list)
    top_sessions: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Events / Observability models
# ---------------------------------------------------------------------------


class EventRecord(BaseModel):
    """A single event from the event store."""

    time: datetime | None = None
    event_type: str = ""
    session_id: str | None = None
    execution_id: str | None = None
    phase_id: str | None = None
    data: dict = Field(default_factory=dict)


class TimelineEntry(BaseModel):
    """A timeline entry for session tool usage."""

    time: datetime | None = None
    event_type: str = ""
    tool_name: str | None = None
    duration_ms: float | None = None
    success: bool | None = None


class ToolUsageSummary(BaseModel):
    """Summary of tool usage across a session."""

    tool_name: str
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Conversation models
# ---------------------------------------------------------------------------


class ConversationLine(BaseModel):
    """A single line from a conversation log."""

    line_number: int
    raw: str
    event_type: str | None = None
    tool_name: str | None = None
    content_preview: str | None = None


class ConversationLog(BaseModel):
    """Full conversation log for a session."""

    session_id: str
    lines: list[ConversationLine] = Field(default_factory=list)
    total_lines: int = 0
    metadata: dict | None = None


class ConversationMeta(BaseModel):
    """Conversation metadata without full log content."""

    session_id: str
    event_count: int = 0
    model: ObservedModelId | None = None
    """The model the harness REPORTED for this conversation, or None."""
    requested_model: str | None = None
    """The model the phase REQUESTED (often an alias), or None (ADR-067 D9)."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    tool_counts: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    size_bytes: int | None = None
    execution_id: str | None = None
    workflow_id: str | None = None
    phase_id: str | None = None
    success: bool | None = None

    @computed_field(
        description="The model for humans: the reported id verbatim, or "
        "'unknown (requested: <alias>)', or 'unknown' (ADR-067 D9)."
    )
    @property
    def model_display(self) -> str:
        """Derived, never passed in, so it cannot contradict ``model``."""
        return format_observed_model(self.model, self.requested_model)


# ---------------------------------------------------------------------------
# GitHub webhook model
# ---------------------------------------------------------------------------


class WebhookResult(BaseModel):
    """Result of processing a GitHub webhook."""

    status: str
    event: str
    triggers_fired: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Realtime model
# ---------------------------------------------------------------------------


class RealtimeHealth(BaseModel):
    """Health status of the realtime projection."""

    active_executions: int = 0
    active_connections: int = 0


# ---------------------------------------------------------------------------
# Build identity (#1380)
# ---------------------------------------------------------------------------


class _NamesTheRunningRelease(BaseModel):
    """A response that reports which release of syn-api answered it.

    MORE THAN ONE ENDPOINT HAS TO SAY THIS, so the pair that says it lives here
    once. ``/health`` reports it inside ``build``; ``/`` reports it flat beside
    the API's name. They are two views of one fact, and #1380 is what happens
    when a fact about the running release gets a second home: ``main.py``'s
    ``"0.5.1"`` and the installed package disagreed for twenty releases and
    nobody noticed, because nothing required them to be derived from one place.

    Subclass this to gain the pair; do not restate it. What a subclass adds is
    whatever ELSE that endpoint reports — the image stamps, the links — never a
    second opinion on the release or on whether it is readable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str | None = Field(
        description="Installed release of the syn-api distribution, as reported by "
        "importlib.metadata. This is the same string pyproject.toml ships, so it "
        "identifies the build exactly — including beta suffixes (e.g. '0.29.1b3'). "
        "Null when the distribution's metadata cannot be read, because there is no "
        "honest release to report then and a plausible one would mislead; read "
        "version_status to tell that case apart without inspecting the null.",
    )

    @computed_field(
        description="Whether the running release could be read at all. 'installed' means "
        "version names the distribution this process was installed from; 'unavailable' "
        "means the distribution's metadata could not be read, version is null, and "
        "nothing has been invented to fill it.",
    )
    @property
    def version_status(self) -> Literal["installed", "unavailable"]:
        """Derived, never passed in, so it cannot contradict ``version``.

        The pair would otherwise be a second place to get the same fact wrong —
        ``version: null`` beside ``version_status: "installed"`` is exactly the
        kind of self-disagreement #1380 is about. It exists as a field anyway
        because a caller should not have to infer meaning from a null: on
        ``BuildInfo`` the neighbouring nulls mean "the image did not stamp
        itself", which is a different fact, and only a named state says which
        absence a reader is looking at.
        """
        return "unavailable" if self.version is None else "installed"


class BuildInfo(_NamesTheRunningRelease):
    """Which build is answering. Populated by ``syn_api.build_info``.

    Reported in three places from that one source: this block on ``GET /health``,
    the flat pair on ``GET /``, and ``openapi.json``'s ``info.version``. All
    three used to be, or were derived from, a hardcoded literal that had drifted
    twenty releases behind the installed package.

    The release and its status come from ``_NamesTheRunningRelease``. What this
    model adds is the two build-time stamps, which only an image can supply,
    and when this process went live, which only the process can.
    """

    image_tag: str | None = Field(
        default=None,
        description="Container image tag this process was built from, stamped at image "
        "build time. Null when the build did not stamp one — which is a different "
        "fact from an unknown tag, and is reported as such.",
    )
    commit: str | None = Field(
        default=None,
        description="Git commit the image was built from, stamped at image build time. "
        "Null when the build did not stamp one.",
    )
    started_at: datetime = Field(
        description="When this API process started (UTC, ISO 8601): the moment the "
        "running deployment went live. Captured once per process, so it changes only "
        "when the process is replaced, which is what a redeploy does.",
    )

    @computed_field(
        description="started_at as an absolute UTC label, e.g. '2026-10-04 06:47 UTC'. "
        "Relative and local-time renderings are the client's to make from started_at.",
    )
    @property
    def started_at_display(self) -> str:
        """Derived, never passed in, so it cannot contradict ``started_at``."""
        return format_utc_timestamp(self.started_at)


class RootResponse(_NamesTheRunningRelease):
    """Payload of ``GET /`` — what this API is, and which build is serving it.

    THE VERSION HERE IS NULLABLE AND COMES WITH A STATUS, like /health's. It was
    a flat ``dict[str, str]`` whose version slot held the literal ``"unknown"``
    when metadata could not be read: a string in a version field, indistinguish-
    able to a client from a release actually called that, and exactly the defect
    #1380 was filed to remove — just at the endpoint nobody re-read. A typed
    response makes the absence a declared state instead of a word.

    ``openapi.json``'s ``info.version`` remains the one place a sentinel is
    unavoidable; see the comment at that call in ``main.py``.
    """

    name: str = Field(description="Human-readable name of this API.")
    docs: str = Field(description="Path to the interactive API documentation.")
    health: str = Field(
        description="Path to the health endpoint, which reports the full "
        "build block plus read-path status."
    )


class _OmitsAbsentFields(BaseModel):
    """A response model whose ``None`` fields are omitted rather than sent as null.

    /health's optional blocks have always been ABSENT when they could not be
    filled in, and callers read them that way: `syn health` branches on whether
    ``subscription`` is there at all, and "no lag measurement" has to stay
    distinguishable from ``lag: 0``, which is a measurement saying "at the head".

    A model-level serializer rather than ``response_model_exclude_none``,
    because that flag is recursive and would also delete ``build.image_tag`` and
    ``build.commit`` — whose ``null`` is a deliberate answer meaning "this image
    did not stamp itself", not an absence. Omission is correct for the models
    that inherit this and wrong one level down, so it is spelled where it is
    correct.
    """

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler):
        """Deliberately unannotated. Pydantic builds the SERIALIZATION schema from
        a model serializer's return type, so writing ``-> dict[str, JsonValue]``
        here replaces every declared property in ``openapi.json`` with
        ``additionalProperties: {$ref: JsonValue}`` — re-opening the contract
        this change exists to close, by the same mechanism and less visibly.
        Left off, pydantic keeps the model's own schema. ``test_health_contract``
        asserts the schema stays closed and named, which is what would catch an
        annotation being helpfully added back.
        """
        return {key: value for key, value in handler(self).items() if value is not None}


#: Every value ``subscription.status`` can take. The first four are
#: ``read_path_health._ReadPathStatus``, which owns that vocabulary; "unknown"
#: is added here because only /health can produce it — it is what the probe
#: reports when it failed and has no verdict to publish.
#: ``test_health_contract.py`` fails if those four ever stop being a subset.
SubscriptionHealthStatus = Literal[
    "healthy",
    "degraded",
    "halted",
    "dropped_events",
    "held",
    "stalled",
    "catching_up",
    "unknown",
]


class HeldProjectionHealth(BaseModel):
    """A projection held below an event it failed to apply (ESP #391).

    It is retried there with backoff and never checkpointed past it, so it is
    behind and stays behind until the handler is fixed or the projection is
    rebuilt. Every other projection keeps consuming.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: str = Field(description="Projection name, as in projection_checkpoints.")
    event_type: str = Field(description="Type of the event it failed to apply.")
    global_nonce: int = Field(description="Global nonce of the event it is held at.")


class SubscriptionHealth(_OmitsAbsentFields):
    """The read-path block of ``GET /health``: is the subscription up, and is it behind.

    FLAT, not nested, because that is the wire shape `syn health` and the deploy
    runbook already read. The fields from ``running`` down are
    ``CoordinatorSubscriptionService.get_status()``; the ones from
    ``is_catching_up`` down are ``ReadModelLag``, spread into the same object by
    ``lifecycle._describe_subscription_health`` (rendered by ``subscription_health``).

    EVERY FIELD BUT ``status`` IS OPTIONAL, and each absence is a distinct fact
    rather than a default: ``lag is None`` means the coordinator is not up yet,
    so there is nothing whose progress could be measured — which is not the same
    as "not behind", and must not serialize as ``lag: 0``. When the lag or
    dropped-start probe fails, the lag fields are absent but what the
    coordinator itself knows (``running``, ``held_projections``, ``halted_at``)
    is still published, and still sets ``status``: a halt at an undecodable
    head event is exactly when the lag probe fails too. ``status`` is "unknown"
    only when none of those fires.

    ``ReadModelLag``'s fields are restated here because the block is flat on the
    wire and a generated client has to be able to see them. That restatement is
    the one place this model can drift from its producer, so
    ``test_health_contract.py`` asserts the two field sets still match.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: SubscriptionHealthStatus = Field(
        description="Verdict on the read path: 'healthy', 'catching_up' during a replay "
        "that ends by itself, 'stalled' for a projection that does not, 'degraded' "
        "for a coordinator that is not running, 'halted' when the subscription stopped "
        "at a stored event it cannot decode, 'dropped_events' when a read model "
        "passed an event without applying it, 'held' when a projection failed to apply "
        "an event and is retried below it, or 'unknown' when the probe failed.",
    )
    running: bool | None = Field(
        default=None,
        description="Whether the subscription coordinator is running. Null when the probe "
        "failed and could not ask.",
    )
    projection_count: int | None = Field(
        default=None, description="How many projections the coordinator is driving."
    )
    realtime_enabled: bool | None = Field(
        default=None, description="Whether a realtime (SSE) projection is attached."
    )
    held_projections: list[HeldProjectionHealth] | None = Field(
        default=None,
        description="Projections held below an event they failed to apply (ESP #391). "
        "Non-empty sets status 'held'; the cause is in the API log as the handler's "
        "exception. Null when the probe failed.",
    )
    halted_at: int | None = Field(
        default=None,
        description="Global nonce of the undecodable stored event the subscription is "
        "halted at (ESP ADR-026); status is then 'halted'. Re-checked every minute; "
        "repair per the ESP ADR-026 recovery steps in the API log. Null when not halted.",
    )
    is_catching_up: bool | None = Field(
        default=None,
        description="True while the coordinator is replaying history and some projection has "
        "not reached the head. Reads may 404 for recently written aggregates. Ends "
        "by itself. Null when the subscription is not up yet and lag is unmeasurable.",
    )
    is_stalled: bool | None = Field(
        default=None,
        description="True when a projection is behind the head and its checkpoint has stopped "
        "moving. Does NOT resolve on its own. Null when lag is unmeasurable.",
    )
    lag: int | None = Field(
        default=None,
        description="Distance of the furthest-behind projection from the store head, in "
        "lag_unit. 0 means at the head; null means not measurable.",
    )
    lag_unit: Literal["events"] | None = Field(
        default=None, description="Unit of lag: event-store global-nonce positions, not seconds."
    )
    head_position: int | None = Field(
        default=None, description="Global nonce of the newest event in the store."
    )
    lagging_projections: list[ProjectionLag] | None = Field(
        default=None,
        description="Every projection short of the head, furthest behind first. Empty when "
        "all are at the head; null when lag is unmeasurable.",
    )
    rebuilding_read_models: list[ReadModelStatus] | None = Field(
        default=None,
        description="Every read model that is rebuilding, furthest behind first, with display "
        "strings for a banner. Ordinary live lag is excluded. Null when lag is unmeasurable.",
    )
    unapplied_starts: list[UnappliedStart] | None = Field(
        default=None,
        description="Executions whose WorkflowExecutionStarted an execution read model's "
        "checkpoint passed without applying (#1545). Lag cannot show these: the read model "
        "is at the head and wrong. Non-empty sets status 'dropped_events'; repair per "
        "docs/runbooks/repair-dropped-execution-start.md. Null when not measured.",
    )


class DiskSpaceHealth(BaseModel):
    """Free space on the workspace volume, as /health reports it (#1560)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(description="Directory whose filesystem was measured.")
    state: Literal["ok", "unmeasurable", "low", "critical"] = Field(
        description="'low' degrades /health; 'critical' also refuses new executions."
    )
    free_percent: float | None = Field(description="Percent free; null when unmeasurable.")
    free_bytes: int | None = Field(description="Bytes available; null when unmeasurable.")
    degraded_below_percent: float = Field(description="SYN_DISK_DEGRADED_BELOW_PERCENT.")
    refuse_admission_below_percent: float = Field(
        description="SYN_DISK_REFUSE_ADMISSION_BELOW_PERCENT."
    )


class DbPoolHealth(BaseModel):
    """One Postgres connection pool in this API process, at the moment of asking (#1583).

    ``waiting`` greater than zero, or ``in_use`` equal to ``max_size``, means
    requests are queueing for a connection rather than for the database itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="What the pool serves, e.g. 'projections' or 'agent_events'.")
    size: int = Field(description="Connections currently open.")
    max_size: int = Field(description="Most connections the pool will open.")
    in_use: int = Field(description="Connections checked out right now.")
    waiting: int = Field(description="Callers blocked waiting for a connection right now.")

    @classmethod
    def snapshot(cls) -> list[DbPoolHealth]:
        """Every open pool, read from in-process counters only.

        Costs nothing and cannot hang on the database it describes, so /health
        can always report it.
        """
        from syn_adapters.postgres_pool import pool_stats

        return [cls.model_validate(stats, from_attributes=True) for stats in pool_stats()]


class HealthResponse(_OmitsAbsentFields):
    """Payload of ``GET /health``.

    EVERY FIELD IS DECLARED AND EXTRAS ARE FORBIDDEN. An earlier cut of #1380
    typed only ``build`` and left ``extra="allow"`` for the probe blocks, which
    put ``additionalProperties: true`` in ``openapi.json`` and an
    ``[key: string]: unknown`` index signature in the generated CLI types: the
    fields `syn health` actually reads were invisible to every generated
    consumer, and a probe could change shape without the drift check noticing.
    The probes own the shapes — ``CodexAuthStatus`` and ``ProjectionLag`` are
    declared at their source and referenced, not copied — but the fact that
    /health publishes them is this model's to state.

    ABSENT OPTIONAL BLOCKS ARE OMITTED, not sent as null; see
    ``_OmitsAbsentFields``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = Field(
        description="'healthy' while the process is alive and accepting writes; 'starting' "
        "while it is alive but startup (a long migration, say) has not finished, when every "
        "route but /health and /version answers 503; 'failed' when startup failed after serving "
        "began and the process is exiting; 'unhealthy' when the probe failed.",
    )
    mode: str = Field(description="'full', or 'degraded' when some subsystem is impaired.")
    build: BuildInfo = Field(description="Which build is answering (#1380).")
    degraded_reasons: list[DegradedReason] | None = Field(
        default=None,
        description="Every way this instance is up but not fully serving. Omitted entirely "
        "when there are none, which is how a reader tells 'nothing is wrong' from "
        "'something is and it is not listed here'.",
    )
    subscription: SubscriptionHealth | None = Field(
        default=None,
        description="Read-path health. Omitted when no subscription service is wired up at "
        "all, e.g. in offline mode.",
    )
    codex_auth: CodexAuthStatus | None = Field(
        default=None,
        description="Freshness of this instance's codex credential. Omitted when the probe "
        "could not run — a credential hint must never be able to take /health down.",
    )
    warnings: list[str] | None = Field(
        default=None,
        description="Human-readable notes that need attention but do not degrade the "
        "instance. Omitted when there are none.",
    )
    disk: DiskSpaceHealth | None = Field(
        default=None,
        description="Free space on the workspace volume (#1560). Omitted only when "
        "the probe itself could not be built.",
    )
    db_pools: list[DbPoolHealth] | None = Field(
        default=None,
        description="Every open Postgres pool in this process, by name. Omitted when none "
        "is open, e.g. in offline mode.",
    )
    cpu_throttling: CpuThrottling | None = Field(
        default=None,
        description="How often the API container hit its CPU limit (#1600). Always present "
        "once the gate is ready, with status 'unknown' when the cgroup does not say; "
        "omitted only while the gate is withholding the API.",
    )


# ---------------------------------------------------------------------------
# Shared base response models
# ---------------------------------------------------------------------------


class StatusActionResponse(BaseModel):
    """Generic response for create/update/delete actions."""

    entity_id: str
    status: str


class PaginatedResponse(BaseModel):
    """Base for paginated list responses. Subclass and add typed items field."""

    total: int


# ---------------------------------------------------------------------------
# Repo response models
# ---------------------------------------------------------------------------


class RepoCreatedResponse(BaseModel):
    """Response after registering a new repo."""

    repo_id: str
    full_name: str


class RepoActionResponse(BaseModel):
    """Response for repo mutation actions (update, deregister, assign, unassign)."""

    repo_id: str
    status: str
    system_id: str | None = None


class RepoListResponse(BaseModel):
    """Paginated list of repos."""

    repos: list[RepoSummaryResponse] = Field(default_factory=list)
    total: int = 0


class RepoHealthResponse(BaseModel):
    """Per-repo health snapshot with success rate, trend, and accumulated costs.

    Note: ``recent_cost_usd`` is accumulated from WorkflowCompleted/Failed events
    since the projection was last reset — it is not a fixed time window and may
    differ from ``RepoCostResponse.total_cost_usd`` which is a TimescaleDB total.
    """

    repo_id: str = ""
    repo_full_name: str = ""
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    success_rate: float = 0.0
    trend: str = "stable"
    recent_cost_usd: str = "0"
    window_tokens: int = 0
    last_execution_at: str = ""


class RepoCostResponse(BaseModel):
    """Per-repo cost breakdown by workflow and model."""

    repo_id: str = ""
    repo_full_name: str = ""
    total_cost_usd: str = "0"
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_workflow: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[CostModelKey, str] = Field(default_factory=dict)
    execution_count: int = 0


class RepoActivityEntryResponse(BaseModel):
    """Single entry in a repo's execution timeline."""

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    status: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    """Seconds this execution has run, or ``None`` when nothing knows.

    Nullable for the reason every other duration on this API is: 0.0 is a
    measurement. This field reported it for every running execution on the
    repo, system-activity and system-history timelines.
    """
    trigger_source: str = ""


class RepoActivityResponse(BaseModel):
    """Paginated list of repo activity entries."""

    entries: list[RepoActivityEntryResponse] = Field(default_factory=list)
    total: int = 0


class RepoFailureEntryResponse(BaseModel):
    """A failed execution record for a repository."""

    execution_id: str
    workflow_id: str = ""
    workflow_name: str = ""
    failed_at: datetime | None = None
    error_message: str = ""
    error_type: str = ""
    phase_name: str = ""
    conversation_tail: list[str] = Field(default_factory=list)


class RepoFailuresResponse(BaseModel):
    """Paginated list of repo failure entries."""

    failures: list[RepoFailureEntryResponse] = Field(default_factory=list)
    total: int = 0


class RepoSessionEntryResponse(BaseModel):
    """Lightweight session record for repo insight views."""

    id: str
    execution_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    agent_type: str = ""
    total_tokens: int = 0
    total_cost_usd: str = "0"


class RepoSessionsResponse(BaseModel):
    """Paginated list of repo session entries."""

    sessions: list[RepoSessionEntryResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# System response models
# ---------------------------------------------------------------------------


class SystemCreatedResponse(BaseModel):
    """Response after creating a new system."""

    system_id: str
    name: str


class SystemActionResponse(BaseModel):
    """Response for system mutation actions (update, delete)."""

    system_id: str
    status: str


class SystemListResponse(BaseModel):
    """Paginated list of systems."""

    systems: list[SystemSummaryResponse] = Field(default_factory=list)
    total: int = 0


class RepoStatusEntryResponse(BaseModel):
    """Health status for a single repo within a system."""

    repo_id: str = ""
    repo_full_name: str = ""
    status: str = "inactive"
    success_rate: float = 0.0
    active_executions: int = 0
    last_execution_at: str = ""


class SystemStatusResponse(BaseModel):
    """Cross-repo health overview within a system."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    overall_status: str = "healthy"
    total_repos: int = 0
    healthy_repos: int = 0
    degraded_repos: int = 0
    failing_repos: int = 0
    repos: list[RepoStatusEntryResponse] = Field(default_factory=list)


class SystemCostResponse(BaseModel):
    """System-wide cost breakdown by repo, workflow, and model."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    total_cost_usd: str = "0"
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_repo: dict[str, str] = Field(default_factory=dict)
    cost_by_workflow: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[CostModelKey, str] = Field(default_factory=dict)
    execution_count: int = 0


class SystemActivityResponse(BaseModel):
    """Paginated list of system activity entries."""

    entries: list[RepoActivityEntryResponse] = Field(default_factory=list)
    total: int = 0


class FailurePatternResponse(BaseModel):
    """A recurring failure pattern within a system."""

    error_type: str = ""
    error_message: str = ""
    occurrence_count: int = 0
    affected_repos: list[str] = Field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""


class CostOutlierResponse(BaseModel):
    """An execution with unusually high cost."""

    execution_id: str = ""
    repo_full_name: str = ""
    workflow_name: str = ""
    cost_usd: str = "0"
    median_cost_usd: str = "0"
    deviation_factor: float = 0.0
    executed_at: str = ""


class SystemPatternsResponse(BaseModel):
    """Recurring failure and cost patterns within a system."""

    system_id: str = ""
    system_name: str = ""
    failure_patterns: list[FailurePatternResponse] = Field(default_factory=list)
    cost_outliers: list[CostOutlierResponse] = Field(default_factory=list)
    analysis_window_hours: int = 168


class SystemHistoryResponse(BaseModel):
    """Paginated list of system history entries."""

    entries: list[RepoActivityEntryResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Trigger response models
# ---------------------------------------------------------------------------


class TriggerActionResponse(BaseModel):
    """Response for trigger create/update/delete actions."""

    trigger_id: str
    name: str | None = None
    status: str
    preset: str | None = None
    action: str | None = None


class TriggerListResponse(PaginatedResponse):
    """Paginated list of trigger summaries."""

    triggers: list[TriggerSummary] = Field(default_factory=list)


class TriggerHistoryListEntry(BaseModel):
    """Entry in a cross-trigger history listing."""

    trigger_id: str
    fired_at: str | None = None
    execution_id: str = ""
    event_type: str = ""
    pr_number: int | None = None
    status: str = "dispatched"
    guard_name: str = ""
    block_reason: str = ""


class TriggerHistoryListResponse(PaginatedResponse):
    """Paginated list of trigger history entries (global)."""

    entries: list[TriggerHistoryListEntry] = Field(default_factory=list)


class TriggerHistoryEntryResponse(BaseModel):
    """Single entry in a trigger-specific history response."""

    fired_at: str | None = None
    execution_id: str = ""
    webhook_delivery_id: str = ""
    event_type: str = ""
    pr_number: int | None = None
    status: str = "dispatched"
    cost_usd: float | None = None
    guard_name: str = ""
    block_reason: str = ""


class TriggerHistoryResponse(BaseModel):
    """History entries for a specific trigger."""

    trigger_id: str
    entries: list[TriggerHistoryEntryResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Organization response models
# ---------------------------------------------------------------------------


class OrganizationActionResponse(BaseModel):
    """Response for organization create/update/delete actions."""

    organization_id: str
    name: str | None = None
    slug: str | None = None
    status: str


class OrganizationListResponse(PaginatedResponse):
    """Paginated list of organizations."""

    organizations: list[OrganizationSummaryResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Insight response models
# ---------------------------------------------------------------------------


class SystemOverviewEntryResponse(BaseModel):
    """Summary of a single system for global overview."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    organization_name: str = ""
    repo_count: int = 0
    overall_status: str = "healthy"
    active_executions: int = 0
    total_cost_usd: str = "0"


class GlobalOverviewResponse(BaseModel):
    """Global overview of all systems and repos."""

    total_systems: int = 0
    total_repos: int = 0
    unassigned_repos: int = 0
    total_active_executions: int = 0
    total_cost_usd: str = "0"
    systems: list[SystemOverviewEntryResponse] = Field(default_factory=list)


class GlobalCostResponse(BaseModel):
    """Global cost breakdown across all repos."""

    system_id: str = ""
    system_name: str = ""
    organization_id: str = ""
    total_cost_usd: str = "0"
    total_tokens: int = 0
    """Sum of input, output, cache creation and cache read tokens (issue #873)."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    cost_by_repo: dict[str, str] = Field(default_factory=dict)
    cost_by_workflow: dict[str, str] = Field(default_factory=dict)
    cost_by_model: dict[CostModelKey, str] = Field(default_factory=dict)
    execution_count: int = 0


class HeatmapDayBucketResponse(BaseModel):
    """Single day's aggregated activity."""

    date: str
    count: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)


class ContributionHeatmapResponse(BaseModel):
    """Contribution heatmap data."""

    metric: str
    start_date: str
    end_date: str
    total: float = 0.0
    days: list[HeatmapDayBucketResponse] = Field(default_factory=list)
    filter: dict[str, str | None] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Observability response models
# ---------------------------------------------------------------------------


class ToolTimelineEntry(BaseModel):
    """Single entry in a tool execution timeline."""

    observation_id: str = ""
    operation_type: str = ""
    tool_name: str | None = None
    timestamp: datetime | None = None
    duration_ms: float | None = None
    success: bool | None = None
    error_message: str | None = None


class ToolTimelineResponse(BaseModel):
    """Tool execution timeline for a session."""

    session_id: str
    total_executions: int = 0
    executions: list[ToolTimelineEntry] = Field(default_factory=list)


class CaptureStatusEntry(BaseModel):
    """One recorded session-capture verdict.

    Mirrors the observation the workspace adapter writes on the observability
    lane. The observed fields are None exactly when something went wrong, which
    is when a backfill needs them most - so the expected values are carried
    alongside rather than in place of them.
    """

    session_id: str
    execution_id: str | None = None
    phase_id: str | None = None
    workspace_id: str | None = None
    recorded_at: datetime | None = None

    state: str
    """captured, incomplete, failed, unknown or disabled.

    Lowercase, matching the recorded CaptureState values. Anything this build
    cannot recognise is reported as "unknown" rather than echoed back.
    """

    needs_backfill: bool
    """Derived from the state, never read from the stored flag.

    True for anything except a settled verdict, so a state that cannot be
    trusted asks for a retry. A re-sent transcript is a no-op (the store dedups
    on content hash); a skipped one is lost permanently.
    """

    partition: str | None = None
    """The spool partition this execution wrote to: what a retry needs to find
    the transcripts again."""

    expected_deployment: str | None = None
    origin_deployment: str | None = None

    agent_session_ids: list[str] | None = None
    """The agent-native session ids the store confirmed for this phase.

    A phase has MANY. `session_id` above is the uuid4 syn137 assigns per phase
    run; these are the ids the AGENTS chose for themselves, and one phase yields
    several whenever it delegates - a codex phase handing work to claude, a
    subagent, a resumed thread. The host never passes its id to the agent, so
    the two namespaces are disjoint and this field is the only thing relating
    them.

    Use it to fetch a phase's transcripts from the session store, which keys on
    the agent-native id.

    null means the exporter did not report them (its result schema predates the
    `sessions` array), which is NOT the same as [] meaning it confirmed none.
    """


class CaptureStatusResponse(BaseModel):
    """Recorded capture verdicts, newest first."""

    total: int = 0
    """How many entries this response contains, after any filter."""

    needs_backfill_count: int = 0
    """How many of the scanned verdicts need a backfill, before any filter."""

    unattributable_count: int = 0
    """Scanned verdicts with no session id, which cannot be acted on.

    Reported rather than dropped: a response that omitted them could read as
    all-clear while a failure sat unattributable in the store.
    """

    scanned: int = 0
    """How many stored verdicts were examined to build this response."""

    truncated: bool = False
    """True when the scan filled its limit, so older verdicts may exist.

    The limit is applied by the database BEFORE the needs_backfill filter, so
    an empty backlog on a truncated scan does NOT mean there is no backlog.
    """

    entries: list[CaptureStatusEntry] = Field(default_factory=list)


class SessionTokenMetrics(BaseModel):
    """Token usage metrics for a session."""

    session_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: str = "0"
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


# ---------------------------------------------------------------------------
# Artifact action response models
# ---------------------------------------------------------------------------


class ArtifactActionResponse(BaseModel):
    """Response for artifact update/delete actions."""

    artifact_id: str
    status: str


# ---------------------------------------------------------------------------
# SSE health response model
# ---------------------------------------------------------------------------


class SSEHealthResponse(BaseModel):
    """Health status of the SSE subsystem."""

    status: str
    active_executions: int | None = None
    active_connections: int | None = None


# ---------------------------------------------------------------------------
# Claude plugin response models (issue #726)
# ---------------------------------------------------------------------------


class AddGlobalClaudePluginRequest(BaseModel):
    """Request body for ``POST /claude-plugins/global`` (Phase A redesign).

    Takes the display name plus version of an already-registered plugin. The
    handler looks the entry up in the lock projection and refuses to add
    anything that has not been registered first via
    ``POST /claude-plugins/registrations``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)


class ClaudePluginFileEntry(BaseModel):
    """One file in the uploaded plugin tree (``POST /claude-plugins/registrations``).

    ``content_b64`` is the base64-encoded byte content; the API decodes it back
    into raw bytes before hashing/uploading. base64 keeps binary-safe payloads
    inside the JSON envelope without forcing the caller to choose an encoding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rel_path: str = Field(..., min_length=1)
    content_b64: str


class RegisterClaudePluginRequest(BaseModel):
    """Request body for ``POST /claude-plugins/registrations`` (Phase A).

    The CLI uploads the entire plugin tree inline alongside the parsed manifest;
    the API hashes the normalized tree, stores it via the storage port, and
    persists the registration aggregate. Idempotent on existing
    ``(source_url, version, name)`` (re-uploading is a safe no-op).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_url: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    name: str | None = Field(
        default=None,
        description=("Display name override; when omitted the manifest's ``name`` is used."),
    )
    manifest: dict[str, object] = Field(
        ..., description="Pre-parsed contents of .claude-plugin/plugin.json."
    )
    files: list[ClaudePluginFileEntry] = Field(
        ..., min_length=1, description="Every file in the plugin tree (base64-encoded)."
    )


class RegisterClaudePluginResponse(BaseModel):
    """Response payload for ``POST /claude-plugins/registrations``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    sha256: str = Field(..., description="Content-addressed sha of the normalized tree.")


class GlobalClaudePluginResponse(BaseModel):
    """A single entry in the global claude plugin registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source_url: str
    version: str
    resolved_sha: str
    added_at: datetime | None = None


class GlobalClaudePluginListResponse(BaseModel):
    """List of currently-registered global claude plugins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugins: list[GlobalClaudePluginResponse] = Field(default_factory=list)
    total: int = 0


class ClaudePluginLockResponse(BaseModel):
    """A single lock entry (one ``(source_url, version)`` pair)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source_url: str
    version: str
    resolved_sha: str
    tree_storage_prefix: str
    registered_at: datetime | None = None


class ClaudePluginLockListResponse(BaseModel):
    """List of every entry currently in the claude plugin lock projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugins: list[ClaudePluginLockResponse] = Field(default_factory=list)
    total: int = 0


class RemoveGlobalClaudePluginResponse(BaseModel):
    """Confirmation payload for ``DELETE /claude-plugins/global/{name}``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    status: str


# ---------------------------------------------------------------------------
# Skill response models (issue #772)
# ---------------------------------------------------------------------------


class SkillFilePayload(BaseModel):
    """One file in the uploaded skill tree (``POST /skills/registrations``).

    Mirrors ``ClaudePluginFileEntry``. ``content_base64`` is the base64-encoded
    byte content; the API decodes it back into raw bytes before hashing and
    uploading.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rel_path: str = Field(..., min_length=1, max_length=1024)
    # WHY 96_000_000: comfortably above the legitimate per-tree decoded-size
    # cap (MAX_SKILL_TREE_BYTES = 50 MiB in routes/skills.py) once base64
    # expansion (~4/3) is accounted for, so the decoded-size check in
    # `_decode_files` stays the meaningful gate -- this field bound only
    # stops a client from forcing pydantic to hold an unbounded string
    # before that check ever runs.
    content_base64: str = Field(..., max_length=96_000_000)


class RegisterSkillRequest(BaseModel):
    """Request body for ``POST /skills/registrations`` (issue #772).

    The CLI uploads the entire skill tree inline; the API hashes the
    normalized tree, stores it via the storage port, and persists the
    registration aggregate. Idempotent on existing
    ``(source_url, version, skill_name)``. Unlike claude plugins, there is no
    caller-supplied manifest: the SKILL.md frontmatter at the tree root is the
    manifest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_url: str = Field(..., min_length=1, max_length=2048)
    version: str = Field(..., min_length=1, max_length=256)
    skill_name: str | None = Field(
        default=None,
        max_length=256,
        description=(
            "Display name override; when omitted the SKILL.md frontmatter's 'name' is used."
        ),
    )
    # WHY max_length=10_000: matches MAX_SKILL_TREE_FILES in routes/skills.py
    # -- the route already rejects a longer list at runtime (413), but a
    # matching model bound rejects it at validation time (422) before the
    # request body is even fully materialized into domain objects.
    files: list[SkillFilePayload] = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Every file in the skill tree (base64-encoded).",
    )


class SkillRegistrationResponse(BaseModel):
    """Response payload for ``POST /skills/registrations``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str
    source_url: str
    version: str
    resolved_sha: str = Field(..., description="Content-addressed sha of the normalized tree.")
    tree_storage_prefix: str


class SkillRegistrationLookupResponse(BaseModel):
    """Whether a (source_url, version, skill_name) triple is already registered.

    Lets the CLI skip uploading a skill tree it has already stored. The sha is
    the cache key: identical content always resolves to the same hash, so a hit
    here means zero network work for the caller.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    resolved_sha: str | None = None


class SkillRegistrationSummary(BaseModel):
    """One registered skill, as the lock projection holds it.

    Carries the full identity triple plus the content hash, because that is
    exactly what makes a ``SkillNotRegistered`` failure actionable: the caller
    can see which of the three fields does not match what a workflow declared.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str
    source_url: str
    version: str
    resolved_sha: str = Field(..., description="Content-addressed sha of the normalized tree.")
    resolved_sha_display: str = Field(
        ...,
        description="First 12 characters of resolved_sha, for display in narrow columns.",
    )
    tree_storage_prefix: str
    registered_at: datetime = Field(..., description="UTC; clients format for their locale.")


class SkillListResponse(BaseModel):
    """Every registered skill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skills: list[SkillRegistrationSummary] = Field(default_factory=list)
    total: int = 0


class SkillDetailResponse(BaseModel):
    """Every registration sharing one skill name.

    A name is not unique: the same skill can be pinned at several versions, and
    two sources can publish the same name. All of them are returned so the
    caller can tell which pin a workflow actually resolves to.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str
    registrations: list[SkillRegistrationSummary] = Field(default_factory=list)


class SkillStorageStatsResponse(BaseModel):
    """Size of the content-addressed skill store.

    Skill storage grows monotonically: registration is keyed by content hash
    and nothing removes old trees (skills-distribution spec D6, eviction is
    deliberately not implemented). This endpoint exists so that decision stays
    a measured one rather than an assumption.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_count: int = 0
    total_bytes: int = 0
    skill_count: int = Field(default=0, description="Distinct skill trees, not files.")
    truncated: bool = Field(
        default=False,
        description="True if the backend returned a partial listing, so the counts are floors.",
    )


class MaintenanceModeResponse(BaseModel):
    """Whether new workflow executions are being admitted (#1387).

    ``active`` is the gate: while it is true every admission path refuses and
    the deploy script may swap containers knowing nothing new can start.
    Executions already running are unaffected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active: bool = Field(
        default=False,
        description="True when new execution admission is refused.",
    )
    reason: str = Field(default="", description="Operator-supplied reason for the pause.")
    since: datetime | None = Field(
        default=None,
        description="When admission was paused. Null while admission is open.",
    )
    actor: str = Field(default="", description="Who set the current state.")


class SetMaintenanceModeRequest(BaseModel):
    """Set or clear maintenance mode (#1387).

    The response is not sent until the state is durably persisted, so a caller
    that has seen a 200 knows no further execution can be admitted.
    """

    model_config = ConfigDict(extra="forbid")

    active: bool = Field(description="True to refuse new executions, false to resume admitting.")
    reason: str = Field(
        default="",
        max_length=500,
        description="Why admission is paused; echoed back to every refused caller.",
    )
    actor: str = Field(
        default="",
        max_length=200,
        description="Who is pausing. Free text - the deploy script sends its own name.",
    )


# ---------------------------------------------------------------------------
# Runtime feature flags (#105, ADR-016)
# ---------------------------------------------------------------------------


class FeaturesResponse(BaseModel):
    """Which optional features this deployment has switched on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ui_feedback: bool = Field(
        default=False,
        description=(
            "In-app feedback widget and /feedback routes (SYN_UI_FEEDBACK_ENABLED). "
            "When false the routes answer 404 and the dashboard never loads the widget."
        ),
    )


class FeatureDisabledDetail(BaseModel):
    """Why a flag-gated route refuses to run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str = Field(description="The feature flag that governs this route.")
    reason: str = Field(description="Human-readable explanation.")
    enable_with: str | None = Field(
        default=None,
        description="The setting that enables the feature, when one exists.",
    )


class FeatureDisabledResponse(BaseModel):
    """Response from an installed route while its feature is disabled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: FeatureDisabledDetail
