"""Value objects for workflow execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed at runtime for dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
    ResolvedClaudePlugin,  # noqa: TC001 - needed at runtime for dataclass field default
)
from syn_domain.contexts.orchestration._shared.resolved_skill import (
    ResolvedSkill,  # noqa: TC001 - needed at runtime for dataclass field default
)
from syn_shared.agents import (
    DEFAULT_PHASE_SANDBOX,
    AgentProvider,
    resolve_phase_model,
)

logger = logging.getLogger(__name__)


class ExecutionStatus(StrEnum):
    """Status of workflow execution."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class FailureClassification(StrEnum):
    """Why a failed execution ended: the machinery, the request, or the work.

    THE NUMBER THIS EXISTS TO FIX (#1357). Every failure was `status = failed`
    and nothing else, so a phase that did three phases of real work, found a
    genuine defect and correctly declined to ship it sat in the same bucket as
    a segfault. Of 221 recorded failures an unknown fraction were the platform
    working exactly as designed, which made every failure rate and every
    lost-spend figure computed from `failed` an upper bound of unknown
    tightness - and made the product look broken to the operator least able to
    check.

    THE EVIDENCE WAS ALREADY IN THE RECORD, it simply had nowhere to go: a
    phase that ends on its own agent's `TASK_RESULT success=false` report is a
    different fact from one that ends on an exit status, a timeout or a parse
    failure, and `AgentVerdict` already knows which happened at the moment the
    run is failed. This is where that fact is written down.

    THE VOCABULARY is `workflows/sdlc/retrospective-v1/phases/classify.md`,
    which is what analysts already sort failures into by hand.

    WHY `task` IS A MEMBER, AND WHAT HAD TO ARRIVE BEFORE IT COULD BE (#1372).
    classify.md's third class - "the request was wrong, too big for a phase, or
    impossible" - is a judgement about the REQUEST, and the stored record did
    not support it: the same exit code, the same error text and the same refusal
    arise from a bad request and from a good one the platform mishandled.
    Deriving it from any of those would be a guess, so the member was left out
    with the note that whoever added it had to bring the evidence with them.

    The evidence was asked for - `TASK_RESULT` carries a typed `failure_reason`
    beside `success`, and the prompt every phase is sent says which word to
    write - AND ASKING WAS NOT ENOUGH (#1392). The answer is the run's own
    word about itself, and the only thing standing behind it is that the
    process exited cleanly, which is evidence about the harness. So a phase
    that had given up could write `task`, be believed, and leave the platform's
    failure count by saying so. Nothing now reaches this member from a report:
    the agent's word is recorded as `ReportedFailureReason`, beside the
    classification and never as it, and this member waits for a source of
    evidence that is not the run being measured.

    THE DIRECTION OF DOUBT IS DELIBERATE and it is the one property to keep
    when changing anything here: every member but `PLATFORM` is a POSITIVE
    claim, made only where the agent's own readable report is what ended the
    run and only from the field that states it. Everything else - including a
    report nobody could read - is `PLATFORM`. So a path that forgets to
    classify itself lands on the answer the system already gave, the failure
    tally stays the upper bound it has always been, and no omission can ever
    manufacture evidence that the system was working.

    OMISSION IS NOT A SIGNAL. A phase that reports failure and names no reason
    classifies exactly as it did before the field existed - `CORRECT_REFUSAL`
    - because that is the answer the system already gave, a silent agent has
    said nothing new to move it, and every report already in the store was
    written by an agent that had no key to omit.
    """

    PLATFORM = "platform"
    """The machinery failed, or nothing said otherwise: setup, gates,
    collection, parsing, budget, a non-zero exit with no readable report."""

    TASK = "task"
    """The request was wrong, too big for one phase, or impossible.

    An operator reading this rewrites the brief; re-dispatching an unchanged
    one spends a second whole run to arrive back here, which is why it may
    never be confused with the two members either side of it.

    NOTHING PRODUCES IT TODAY, and that is the honest state rather than an
    oversight (#1392). It needs a judgement about the REQUEST, and the only
    witness the system has is the run being judged: a phase writing
    `failure_reason: "task"` is reporting, not measuring, and that report is
    carried as `ReportedFailureReason.TASK` where an operator can read it. The
    member stays because the question is real and because rows written by any
    reader of this enum must still load; what it waits for is corroboration
    from something other than the run itself.
    """

    CORRECT_REFUSAL = "correct_refusal"
    """The agent reported failure and the platform recorded it faithfully.

    This is the system WORKING, and it carries that label so nobody optimises
    it away or counts it as a defect.
    """

    UNCLASSIFIED = "unclassified"
    """Nothing recorded a classification for this run, so nobody can say.

    Three runs read this way, and `status` plus the reported reason tell them
    apart exactly, which is why none of them needs a member of its own: a run
    that has NOT failed - running, completed, cancelled - has no failure to
    classify; a run that failed before this field existed predates the
    question; and, since #1392, a run whose phase said in as many words that
    it could not tell which of the three causes applied
    (`ReportedFailureReason.UNKNOWN`). The third is the only one that means
    "we looked and could not tell", and it is the only thing a phase can do to
    this record: WITHDRAW a claim it would otherwise have supported. It can
    never add one.

    Kept distinct from `PLATFORM` because folding it in would assert about
    history exactly the thing that could not be known about it - and would
    make every completed run claim a platform failure.
    """

    @classmethod
    def from_stored(cls, value: object) -> FailureClassification:
        """What a stored row or event payload says, `UNCLASSIFIED` when it says nothing.

        THE ONE COERCION POINT, and the reason the replay requirement is met
        rather than asserted. Events and projection rows written before this
        field existed carry no key at all, and a row written by a newer
        version than the reader carries a member this one has never heard of.
        Both arrive here, neither raises, and both read as `UNCLASSIFIED` -
        which is the honest answer for each. A `ValueError` escaping a
        projection replay would take down the read model for every execution
        in the store, historical ones included, to report one unknown string.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            return cls.UNCLASSIFIED


class ReportedFailureReason(StrEnum):
    """What a phase says CAUSED the failure it is reporting (#1372).

    THE QUESTION THIS ANSWERS, and why it had to be asked rather than worked
    out. A readable ``success=false`` says THAT a phase failed and nothing
    more, so every reported failure was recorded as a correct refusal - the
    system working - including the one whose agent had just written "GH_TOKEN
    is not set", which is the system not working, and the one that said the
    task was impossible, which is neither. Those three take opposite responses:
    retry, fix the platform, rewrite the brief. An operator re-dispatching off
    a record that cannot tell them apart spends a whole run to find out.

    THE SPELLINGS ARE classify.md's, which is the vocabulary analysts already
    sort failures into by hand and the one `FailureClassification` was built
    from. Three words, closed, written here and nowhere else - a closed set in
    one place is what separates a contract from the habit of adding one more
    string every time a run is lost, and it is the definition the negative
    tests are written against.

    IT IS THE AGENT'S OWN WORD, NEVER AN INFERENCE. Nothing reads ``comments``,
    an exception message or an exit status to reach a member of this; the only
    way into one is a phase that wrote it.

    AND BECAUSE IT IS THE AGENT'S OWN WORD, IT IS A REPORT AND NOT A
    MEASUREMENT (#1392). This is the whole of what the type means, and the
    reason it is spelled `reported_failure_reason` everywhere it is carried:
    the platform's only corroboration of anything written here is that the
    process exited cleanly and its stream arrived intact, which is evidence
    about the HARNESS and not about whether the task was possible. A run that
    named itself ``task`` established nothing about the request; it said
    something about it. So the word travels the whole way to the operator - who
    wants to know what the agent said - and `FailureClassification`, which is
    what failure NUMBERS are computed from, is never decided by it. The one
    thing a phase can do to that record is WITHDRAW a claim; see
    `_corroborated_classification`, which holds the whole rule.

    AND IT CANNOT CHANGE WHETHER A PHASE COMPLETES - the property to keep when
    editing anything here. This decides a LABEL on a failure already decided by
    ``success``. A word nobody recognises, a sentence, a number, or no key at
    all all read as "no reason given" and leave the verdict exactly as it was.
    Making a misspelling fatal would let a tally field refuse a finished run,
    which is #1324's defect bought back in exchange for nothing.
    """

    TASK = "task"
    """The request was the problem: wrong, impossible, or too big for a phase."""

    PLATFORM = "platform"
    """The machinery was the problem: a missing credential, a tool that
    crashed, a workspace that was not what it claimed."""

    REFUSED = "refused"
    """Neither: the phase could have done the work and judged it should not."""

    UNKNOWN = "unknown"
    """None of the three: the phase could not tell which of them it was (#1392).

    WRITTEN BECAUSE THE PROMPT ALREADY ASKED FOR IT and nothing could hear it.
    Agents were told that leaving the key out would be read as "could not
    tell"; it was not, and could not be - an ABSENT key is also what every
    phase wrote before the key existed, so absence has to keep meaning what it
    meant then. An honest agent following that instruction therefore produced
    the one answer that is the opposite of what it meant: `CORRECT_REFUSAL`,
    which says the system worked.

    So "I could not tell" is a word an agent WRITES, distinguishable from
    silence because the agent chose it, and it lands on `UNCLASSIFIED` - nobody
    can say - which is the only honest record of a failure nobody classified.
    """

    @classmethod
    def from_stored(cls, value: object) -> ReportedFailureReason | None:
        """The reason a stored row or event payload names, None when it names none.

        Total over every value storage can hold, and it never raises:
        `FailureClassification.from_stored`'s contract, for the same reason it
        has one. An event written by a newer version carries a member this
        reader has never heard of, and a `ValueError` escaping a projection
        replay would take down the read model for every execution in the store
        to report one unknown string. "No reason this reader knows" and "no
        reason given" are the same fact downstream, so both read as None.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            return None

    @classmethod
    def from_reported(cls, value: object) -> ReportedFailureReason | None:
        """The reason a block named, or None when it named none this knows.

        Total over every JSON value an agent can write, and it never raises -
        `from_stored`'s rule applied one boundary earlier, and for the same
        reason: the value crosses a trust boundary, so the reader has to
        survive whatever is on the other side of it.

        Anything unreadable is LOGGED rather than absorbed, because a reason
        nobody can see being dropped is how a key quietly stops working. A
        report with no key at all is not "unreadable" and says nothing worth
        logging - it is every phase that ran before the key existed.
        """
        if value is None:
            return None
        matched = cls.from_stored(value)
        if matched is None:
            logger.warning(
                "TASK_RESULT block named a failure_reason this reader does not know (%r). "
                "It must be exactly one of %s, and not a sentence - that is what comments "
                "is for. The failure is recorded as though no reason were given (#1372).",
                value,
                [member.value for member in cls],
            )
        return matched


class PhaseStatus(StrEnum):
    """Status of a single phase execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StrandedDeliverable:
    """A phase whose agent finished and whose output nobody ever collected.

    The window between `AgentExecutionCompleted` and
    `ArtifactsCollectedForPhase` is where a restart destroys a finished run:
    the work is done - branch pushed, verdict reached - and the only record of
    what the phase concluded is what its agent said on the way out. Everything
    needed to turn that into the phase's deliverable is here, so a caller can
    salvage it without reading the event stream itself or knowing which events
    open and close the window.

    Produced only when there IS something to salvage: a phase whose agent said
    nothing leaves nothing behind and is not stranded, it is simply lost.

    It carries the execution and workflow ids too, so that a caller holding one
    of these needs nothing else from the aggregate. That is not convenience: an
    aggregate that has never been hydrated has no id, and resolving that here
    keeps "does this execution exist" from becoming the salvage's problem.
    """

    execution_id: str
    workflow_id: str
    phase_id: str
    phase_name: str
    session_id: str
    last_agent_message: str


@dataclass(frozen=True)
class FinishedAgentRun:
    """What a phase's agent left behind when its run ended.

    Held per phase until that phase's artifacts are collected. One record
    rather than three parallel maps keyed by phase, so a phase cannot end up
    with a message under one key and a session under another.
    """

    phase_id: str
    phase_name: str
    session_id: str
    last_agent_message: str


@dataclass(frozen=True)
class PhaseDefinition:
    """Immutable definition of a phase for aggregate-level sequencing.

    Used by the aggregate to know phase ordering and decide "what's next"
    after artifacts are collected. The aggregate owns sequencing decisions.
    """

    phase_id: str
    name: str
    order: int
    timeout_seconds: int = 300


@dataclass(frozen=True)
class AgentConfiguration:
    """Agent configuration for executing a phase.

    Immutable to ensure configuration integrity.

    NOTE: 'mock' provider is ONLY valid in test environments (APP_ENVIRONMENT=test).
    Production/development MUST use 'claude' or 'codex'
    (or 'openai') with valid API keys/auth.

    Model Aliases (CLI-compatible, recommended):
        - "sonnet" -> latest Claude Sonnet
        - "opus" -> latest Claude Opus
        - "haiku" -> latest Claude Haiku

    'codex' selects the programmatic codex harness on the same docker path
    as 'claude'.
    """

    provider: str = AgentProvider.CLAUDE  # + codex, openai (mock in tests)
    # Declared default is None = "caller named no model". __post_init__ then
    # resolves it PER PROVIDER: Claude gets DEFAULT_CLAUDE_MODEL, codex stays
    # None because codex does not report its own model on the wire and a
    # synthesized value would price every codex run as Haiku (issue #788).
    # Resolution lives here, not in a caller, so EVERY construction path gets
    # it - a caller-side default only covered phases built from YAML.
    model: str | None = None  # CLI alias - auto-resolves to latest version
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 300
    allowed_tools: tuple[str, ...] = ()  # Tools allowed during execution
    # How much authority this phase's agent process gets. Steers codex only;
    # claude scopes through allowed_tools. The command builder maps it to the
    # harness flag. Defaults to DEFAULT_PHASE_SANDBOX, currently the MOST
    # permissive level as a stopgap - see PhaseSandbox (#1157, #1161, #1167).
    sandbox: str = DEFAULT_PHASE_SANDBOX
    # When true, both agent auths are staged so this phase's primary agent may
    # delegate one-shot to the other CLI. Default false = single-provider isolation.
    allow_delegation: bool = False

    def __post_init__(self) -> None:
        """Resolve the per-provider model default.

        Mirrors ``_shared.ExecutionValueObjects.AgentConfiguration`` - keep
        both in sync.
        """
        resolved_model = resolve_phase_model(self.provider, self.model)
        if resolved_model != self.model:
            object.__setattr__(self, "model", resolved_model)


@dataclass(frozen=True)
class PhaseInput:
    """Input specification for a phase.

    Can be from initial workflow inputs or from a previous phase's artifact.
    """

    name: str
    value: str | None = None  # Direct value
    from_phase: str | None = None  # Reference to previous phase output


@dataclass(frozen=True)
class PhaseUsage:
    """What a phase spent, frozen at the moment something asked.

    THE ANSWER FOR A PHASE THAT DID NOT FINISH, which is the only reason this
    is a type rather than five arguments. A phase that completes reports its
    counts on ``PhaseCompleted`` and always has; a phase that was killed at its
    timeout reports on the failure path instead, and that path carried no token
    counts at all - so a run that burned 735 tokens against a 1200s budget and
    a run that burned 300k both arrived as exit 124 with zeros beside them.
    They need opposite responses - a bigger budget, or stop paying for this
    retry - and nothing in the record separated them (#1262).

    ZERO IS A MEASUREMENT HERE, not "unknown", which is why there is no
    three-valued variant of this and no ``None``. A phase whose agent never
    launched spent nothing, and that is the honest report; the distinction
    ``duration_seconds`` has to keep - never started versus started and took no
    time - has no analogue for tokens, because a phase cannot accumulate
    tokens before it exists. Removing that case rather than handling it is what
    keeps this off every call site.

    RESOLVED, NOT ACCUMULATED. These are whatever ``FinalUsage.resolve`` settled
    on for the run: the harness's own terminal totals when it reported them, and
    the deltas observed while it ran when it died before reporting. A killed
    phase only ever has the second, which is the case this exists for.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """The four summed, derived here so no caller sums them again.

        Every sink that carries a total carried its own addition before this
        existed, and an addition repeated at four call sites is four chances to
        leave one term out.
        """
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass(frozen=True)
class PhaseResult:
    """Result of a single phase execution.

    Immutable record of what happened during phase execution.
    Tokens are domain truth (Lane 1); cost is Lane 2 telemetry and does not
    live on this value object.
    """

    phase_id: str
    status: PhaseStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    artifact_id: str | None = None
    session_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    error_message: str | None = None
    exit_code: int | None = None
    """What killed this phase, when a process status said so (#1319).

    None means nothing observed a status, and that includes every phase that
    did NOT fail - the same contract `observed_branches` keeps on the events
    below. A phase that succeeded has its 0 recorded durably already, on the
    `AgentExecutionCompleted` event written on the zero-exit branch; restating
    it here would be a second source for one fact, derived rather than read.

    What had no record at all was the other direction. 124 (the phase reached
    its time budget) and -11 (it was killed) each call for a different
    response, and neither reached any durable store, because the exception
    raised for a non-zero exit stops the run before that event is ever written.
    """
    metadata: dict[str, Any] = field(default_factory=dict)


class BranchObservation(BaseModel):
    """One remote branch of a failing phase's workspace, as git had it (#1200).

    WHERE TO LOOK, WITHOUT SAYING WHO PUT IT THERE. A phase can commit, push,
    and still fail - most often on the #1167 output-artifact contract - and
    when it does no PR is opened and no surface names the branch. The work is
    complete, reviewed by nobody, and findable only by someone who thinks to
    go through the remote's refs. Twice in one day that someone was a human
    doing it by hand; both rescues merged.

    EVERY FIELD IS SOMETHING GIT WAS ASKED AND ANSWERED, and nothing here is
    an attribution. An earlier version of this recorded "work THIS PHASE
    pushed", derived by snapshotting the refs at phase start and treating
    whatever was new as the phase's own. That signature is produced just as
    well by a concurrent push or a human's, because a ref that moved between
    two readings does not record who moved it: git carries no author of a
    push. So the comparison is still taken and still reported - as the
    comparison it is, two SHAs and the reader's own eyes - and no field claims
    the phase caused it.

    That is enough for the operator the record exists for. "Where do I look"
    is answered by a branch name and a commit; it never required knowing who
    pushed.

    A Pydantic model rather than a dataclass because it travels on
    ``WorkflowFailedEvent`` and must serialise as event data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    """The repository directory's name, as the workspace had it cloned."""

    branch: str
    """The branch the workspace was on, without any remote prefix - the name
    to fetch, and the name a PR would be opened from. ``(detached HEAD)`` when
    it was not on one."""

    remote: str | None
    """The remote this observation is about, e.g. ``origin``. ``None`` when
    the branch has no remote-tracking ref and had none at phase start, so
    there is no remote branch to describe. One observation per remote that
    carries the branch, rather than one per repository picking a remote by
    some rule nobody can see."""

    remote_commit: str | None
    """What ``<remote>/<branch>`` points at NOW, asked of the remote itself
    while the workspace was still alive. ``None`` means the remote does not
    have that branch - never pushed, or deleted while the phase ran.

    Read from the remote and not from `refs/remotes`, which is only what this
    clone was last told: a phase that never fetched would report a commit that
    predates whatever it is being compared against. A remote that could not be
    reached produces no record at all rather than a stale one; see
    `ObservedBranches.unreadable`."""

    remote_commit_at_phase_start: str | None
    """What that same ref pointed at when the phase was handed the workspace,
    from `PhaseStartingPoint`. ``None`` means the ref did not exist then.

    Reported beside `remote_commit` rather than reduced to a verdict: the two
    together say "it moved" without anyone having to claim who moved it, and
    an operator diffing them gets more than a boolean would give."""

    unpushed_commits: int
    """How many commits are reachable from the workspace's HEAD that no remote
    ref holds. ``0`` is a fact about the repository and not about the phase.

    Non-zero is a DIFFERENT INCIDENT from a remote that moved: those commits
    are about to die with the container, which is #1184's quarantine to save
    and not something to fetch. Keeping the count here is what lets a client
    tell "this phase left nothing anywhere" from "this phase is holding work
    that is not on any remote" without reading prose."""

    @property
    def remote_moved(self) -> bool:
        """Whether ``<remote>/<branch>`` is at a different commit than at start.

        A comparison of two readings, and deliberately not called anything
        like "pushed": it is true of a push from this workspace, a push from
        anywhere else, and a ref someone deleted or recreated in between.
        """
        return self.remote_commit != self.remote_commit_at_phase_start

    @property
    def is_worth_recording(self) -> bool:
        """Whether anything here differs from a workspace nobody touched.

        The one place that decides what a record MEANS by deciding when one
        exists. A repository whose remote branch is where it was and whose
        HEAD is fully pushed has nothing an operator would act on, and
        recording it anyway is how a phase that did nothing came to report the
        commit it inherited as somewhere to go and look.
        """
        return self.remote_moved or self.unpushed_commits > 0


@dataclass(frozen=True)
class ExecutionMetrics:
    """Aggregated metrics for workflow execution.

    Immutable summary of execution performance. Cost is Lane 2 telemetry —
    see execution_cost projection.
    """

    total_phases: int = 0
    completed_phases: int = 0
    failed_phases: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0

    @classmethod
    def from_results(cls, results: list[PhaseResult]) -> ExecutionMetrics:
        """Create metrics from phase results."""
        completed = sum(1 for r in results if r.status == PhaseStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == PhaseStatus.FAILED)

        total_input = sum(r.input_tokens for r in results)
        total_output = sum(r.output_tokens for r in results)
        total_cache_creation = sum(r.cache_creation_tokens for r in results)
        total_cache_read = sum(r.cache_read_tokens for r in results)
        total_tokens = sum(r.total_tokens for r in results)

        duration = 0.0
        for result in results:
            if result.started_at and result.completed_at:
                delta = result.completed_at - result.started_at
                duration += delta.total_seconds()

        return cls(
            total_phases=len(results),
            completed_phases=completed,
            failed_phases=failed,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_creation_tokens=total_cache_creation,
            total_cache_read_tokens=total_cache_read,
            total_tokens=total_tokens,
            total_duration_seconds=duration,
        )


@dataclass(frozen=True)
class ExecutablePhase:
    """Phase with full execution configuration.

    Combines phase definition with runtime execution config.

    NOTE: All phases MUST have a prompt_template and valid agent_config.
    Empty prompts will cause agent calls to fail.
    """

    phase_id: str
    name: str
    order: int
    description: str | None = None

    # Agent configuration - defaults to Claude (real agent)
    agent_config: AgentConfiguration = field(default_factory=AgentConfiguration)

    # Prompt template (REQUIRED - actual template, not ID)
    prompt_template: str = ""  # Must be set by workflow definition

    # Input configuration
    inputs: list[PhaseInput] = field(default_factory=list)

    # What this phase's definition declares it produces. Plural and possibly
    # EMPTY, which is the whole point: empty means "declared nothing" and is a
    # phase legitimately allowed to produce nothing, while a non-empty
    # declaration is a contract the collector enforces (#1167). The previous
    # singular `output_artifact_type: str = "text"` could not express the
    # difference - an undeclared phase and one declaring "text" both arrived
    # here as "text", so no enforcement was possible downstream.
    output_artifact_types: tuple[str, ...] = ()

    # Timeout for this phase (can override agent config)
    timeout_seconds: int | None = None

    # Whether this phase's workspace gets the repos checked out (#1187).
    # Provisioning was phase-blind: the only opt-out was workflow-level
    # `requires_repos: false`, which applies to every phase at once. Carried
    # here rather than on `agent_config` because it decides what the WORKSPACE
    # contains, not how the agent is invoked.
    clone_repos: bool = True

    # Whether this phase may create a pull request (#1197). Like clone_repos
    # this decides what the WORKSPACE gets - specifically the permissions of
    # the GitHub token in it - rather than how the agent is invoked, which is
    # why it is not on `agent_config`. A prompt saying "do not open a PR" was
    # already in place when `implement` opened one; this is the same statement
    # made somewhere the agent cannot decline it.
    can_open_pr: bool = False

    # Whether a change to the repositories is part of what this phase delivers
    # (#1308). Unlike clone_repos and can_open_pr this decides nothing about
    # the workspace - it decides how the unpushed-work gate READS the workspace
    # at the end. `git status` cannot tell an agent's edit from a rewrite
    # `cargo check` made while inspecting the toolchain, so the phase says
    # which of the two its working tree can possibly hold.
    delivers_repo_changes: bool = True

    # Resolved plugins for the workspace materializer (issue #726). PR1 leaves
    # this empty; PR2's resolution service populates it from the workflow- and
    # phase-scope ClaudePluginRefs.
    claude_plugins: tuple[ResolvedClaudePlugin, ...] = ()

    # Resolved skills for the workspace materializer (issue #772). Additive
    # alongside claude_plugins. ExecuteWorkflowHandler._resolve_phase_skills
    # populates it from the workflow- and phase-scope SkillRefs, with phase
    # scope winning on identity collision.
    skills: tuple[ResolvedSkill, ...] = ()
