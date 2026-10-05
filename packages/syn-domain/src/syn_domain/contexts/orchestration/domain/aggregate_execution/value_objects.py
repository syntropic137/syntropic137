"""Value objects for workflow execution."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 - needed at runtime for dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

# Runtime import: a pydantic field type of DelegationAttempt.
from syn_domain.contexts.agent_sessions import DelegationOutcome  # noqa: TC001
from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
    ResolvedClaudePlugin,  # noqa: TC001 - needed at runtime for dataclass field default
)
from syn_domain.contexts.orchestration._shared.resolved_skill import (
    ResolvedSkill,  # noqa: TC001 - needed at runtime for dataclass field default
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.legacy_event_shapes import (
    classify_resumed_payload,
)
from syn_shared.agents import (
    DEFAULT_PHASE_SANDBOX,
    AgentProvider,
    resolve_phase_model,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger(__name__)


class ExecutionStatus(StrEnum):
    """Status of workflow execution."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
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


class SideEffectStatus(StrEnum):
    """What a phase says happened to the external writes it attempted.

    THE CONFLATION THIS SPLITS. A phase that wrote its deliverable and was then
    refused a PR comment had one word for both facts - `success` - so it wrote
    `false` and the run failed with the finished review still on disk. 17 runs
    of one canary were recorded as failures that way. The deliverable and the
    write-back are separate outcomes and take separate responses: a missing
    deliverable is a failed phase, a refused comment is a permission to grant.

    A REPORT, NEVER A MEASUREMENT, and spelled `reported_side_effects` wherever
    it is carried for the reason `ReportedFailureReason` is: the agent chose
    the word and nothing corroborates it. It never decides whether a phase
    completes - `success` does that, unchanged.
    """

    NONE = "none"
    """The phase attempted no external write."""

    SUCCEEDED = "succeeded"
    """Every external write the phase attempted went through."""

    DENIED = "denied"
    """A write was refused: missing permission, protected branch, read-only token."""

    FAILED = "failed"
    """A write was attempted and broke: network, API error, tool crash."""

    @classmethod
    def from_stored(cls, value: object) -> SideEffectStatus | None:
        """What a stored row or payload names, None when it names nothing known.

        Total and never raises, for `ReportedFailureReason.from_stored`'s
        reason: an unknown string must not take down a projection replay.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            return None

    @classmethod
    def from_reported(cls, value: object) -> SideEffectStatus | None:
        """What a TASK_RESULT block named, None when it named nothing known.

        Crosses the agent trust boundary, so it never raises; an unknown word
        is logged so a key that quietly stops working stays visible.
        """
        if value is None:
            return None
        matched = cls.from_stored(value)
        if matched is None:
            logger.warning(
                "TASK_RESULT block named side_effects this reader does not know (%r). "
                "It must be exactly one of %s. Recorded as not reported.",
                value,
                [member.value for member in cls],
            )
        return matched

    @classmethod
    def most_severe(cls, reported: Iterable[SideEffectStatus | None]) -> SideEffectStatus | None:
        """The worst status any phase reported, None when no phase reported one.

        FAILED outranks DENIED outranks SUCCEEDED outranks NONE: an execution whose second
        phase was refused is not one whose side effects succeeded because the
        first phase's did.
        """
        rank = {cls.NONE: 0, cls.SUCCEEDED: 1, cls.DENIED: 2, cls.FAILED: 3}
        present = [r for r in reported if r is not None]
        return max(present, key=rank.__getitem__) if present else None


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
    # resolves it PER PROVIDER: Claude gets DEFAULT_CLAUDE_MODEL, codex gets
    # DEFAULT_CODEX_MODEL (a concrete priced model the platform forces with
    # --model, never a Claude alias - issue #788). Both are static fallbacks
    # for templates stored before defaults were persisted at install time.
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

    pull_request: int | None = None
    """The PR open from this branch on the forge as the phase failed (#1513).

    Read from the forge, not inferred, so a resume continues THIS PR and
    never another one opened from the same branch since. ``None`` when none
    was open or nobody could ask. Written only when set: every reader before
    #1513 forbids extra fields, so an observation without a PR stays exactly
    what a rollback can replay."""

    @model_serializer(mode="wrap")
    def _omit_unset_pull_request(self, handler: SerializerFunctionWrapHandler) -> object:
        payload = handler(self)
        if isinstance(payload, dict) and payload.get("pull_request") is None:
            payload.pop("pull_request", None)
        return payload

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


class InheritedPhase(BaseModel):
    """One completed phase a resume takes over from its parent (ADR-014 s7).

    The phase is not re-run and its artifacts are not copied: the resume names
    them. A Pydantic model rather than a dataclass because it travels on
    ``ExecutionResumedEvent`` and must serialise as event data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: str
    artifact_ids: list[str]
    """Every artifact the parent collected for this phase, in collection
    order. Empty is a real answer - a phase can complete having stored
    nothing - and not "unknown"."""
    origin_execution_id: str | None = Field(default=None, exclude=True)
    """The execution that RAN this phase, and so holds its artifacts (#1462).

    Not always the parent: a resume of a resume inherits phases its parent itself
    inherited, whose artifacts were only ever stored under the execution that
    ran them. Carried rather than looked up, so the stream says whose output a
    run is resting on.

    Never serialised as part of this model. It forbids extra fields, and so
    did every release before this one: an event nesting the owner here could
    not be read at all by a reader from before it, which is what a rollback
    runs. The events carry it BESIDE their phases instead, under
    `INHERITED_PHASE_OWNERS` (see `owners_to_carry`, `restore_owners`), where
    such a reader loses only the owner.

    None on every event written before #1462. Read it through
    `ResumeOrigin.owner_of`, never directly: absent means the parent the event
    names, which is what it meant when those events were written."""


#: The key under which a resume's events carry the execution that ran each
#: inherited phase (#1462), beside the phases rather than inside them.
#:
#: Why beside: every model a phase is nested in forbids extra fields, and so
#: did the releases before this key existed. A reader from one of those - a
#: rollback - fails on an unknown field INSIDE a resumed origin, and that
#: failure is deliberately fatal (`start_pins.read_resume_origin`). An unknown
#: key at the top of an event only fails its typed validation, and ADR-023 then
#: replays it as a `GenericDomainEvent`, whose readers ignore what they do not
#: name. So that reader still replays the stream, and loses only the owner.
#:
#: Written only for a phase that the execution the event already names did not
#: run, which is exactly the case the key exists for. A first resume writes none,
#: so its events are identical to those written before the key existed.
INHERITED_PHASE_OWNERS = "inherited_phase_owners"


def owners_to_carry(phases: Sequence[InheritedPhase], named: str) -> dict[str, str]:
    """What an event writes under `INHERITED_PHASE_OWNERS`, by phase id.

    ``named`` is the execution the event already names as the phases' source -
    the parent - which a phase without an entry is read as owned by anyway.
    """
    return {
        p.phase_id: p.origin_execution_id
        for p in phases
        if p.origin_execution_id and p.origin_execution_id != named
    }


def restore_owners(phases: object, owners: object) -> object:
    """Stored ``phases`` with the owner ``owners`` carried for each put back.

    Operates on the stored shape: a list of plain phase payloads, before they
    are validated. Anything else - a typed phase, which already has its owner,
    or a payload with nothing carried - is returned as it came.
    """
    if not isinstance(phases, list) or not isinstance(owners, Mapping) or not owners:
        return phases
    return [
        {**phase, "origin_execution_id": owners[phase["phase_id"]]}
        if isinstance(phase, Mapping) and phase.get("phase_id") in owners
        else phase
        for phase in phases
    ]


def payload_with_owners_restored(data: object) -> object:
    """A stored event payload with each inherited phase's owner put back (#1462).

    The whole restore step, so an EVENT file can declare its payload and hold no
    logic: vsa forbids an event importing `collections.abc`, and the isinstance
    guard this needs is exactly the kind of code that belongs beside the value
    objects rather than in a declaration.

    Anything that is not a payload carrying owners is returned untouched, so a
    stream written before the owners existed validates exactly as it did.
    """
    if not isinstance(data, Mapping) or INHERITED_PHASE_OWNERS not in data:
        return data
    payload = dict(data)
    owners = payload.pop(INHERITED_PHASE_OWNERS)
    payload["inherited_phases"] = restore_owners(payload.get("inherited_phases"), owners)
    return payload


def resumed_payload_for_replay(data: object) -> object:
    """A stored `ExecutionResumed` payload, checked and then normalised.

    Two steps the EVENT must not hold itself, for the reason given on
    `payload_with_owners_restored`: vsa requires an event file to be a
    declaration, and both steps need isinstance guards.

    First the meaning is settled. `ExecutionResumed` recorded un-pausing before
    2026-09-29 and records resume-from-unfinished after it, so the payload shape
    decides which it is and an ambiguous one is refused rather than guessed
    (`classify_resumed_payload`). Only then are carried owners restored (#1462).
    """
    classify_resumed_payload(data)
    return payload_with_owners_restored(data)


def payload_with_origin_owners_restored(data: object) -> object:
    """As `payload_with_owners_restored`, for a payload whose phases sit inside
    `resumed_from` rather than at the top level (#1462).

    Same reason for living here: the event file declares a payload and holds no
    logic, because vsa forbids it importing `collections.abc` for the isinstance
    guards this needs.
    """
    if not isinstance(data, Mapping) or INHERITED_PHASE_OWNERS not in data:
        return data
    payload = dict(data)
    owners = payload.pop(INHERITED_PHASE_OWNERS)
    origin = payload.get("resumed_from")
    if isinstance(origin, Mapping):
        payload["resumed_from"] = {
            **origin,
            "inherited_phases": restore_owners(origin.get("inherited_phases"), owners),
        }
    return payload


#: Keys that stored `WorkflowExecutionStarted` events carry inside
#: `pinned_phases` and `ExecutablePhase` no longer declares. The event forbids
#: extra keys, so without this one of them would fail typed validation and the
#: whole start event would replay as a generic one (ADR-023), losing its pins.
#:
#: Entries are NEVER removed: stored history replays forever. Independent of
#: `RETIRED_PHASE_FIELDS`, which is what authors may still write and changes on
#: its own schedule.
REMOVED_EXECUTABLE_PHASE_KEYS: Final[frozenset[str]] = frozenset(
    {
        # Retired by #1477; every start event written since #1454 carries it.
        "can_open_pr",
    }
)


def started_payload_for_replay(data: object) -> object:
    """A stored `WorkflowExecutionStarted` payload, normalised for validation.

    Lives here, not on the event, for the reason given on
    `payload_with_owners_restored`. Removed keys are dropped from each pinned
    phase, then carried owners are restored (#1462).
    """
    if isinstance(data, Mapping) and isinstance(data.get("pinned_phases"), list):
        data = {
            **data,
            "pinned_phases": [
                {k: v for k, v in phase.items() if k not in REMOVED_EXECUTABLE_PHASE_KEYS}
                if isinstance(phase, Mapping)
                else phase
                for phase in data["pinned_phases"]
            ],
        }
    return payload_with_origin_owners_restored(data)


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

    # Whether a change to the repositories is part of what this phase delivers
    # (#1308). Unlike clone_repos this decides nothing about
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


# --- what a resume's start event carries ------------------------------------
#
# These two live HERE rather than beside the rest of `start_pins` because
# `WorkflowExecutionStarted` carries them, and a domain EVENT may import value
# objects from this module but not from an aggregate's internals - vsa enforces
# that, and `ExecutionResumedEvent` already depends on this module the same way.


class SourceCommit(BaseModel):
    """The commit one repository was at when the execution started (#1457).

    `sha` is None when nothing could resolve it - no GitHub access, a repository
    that has since gone - and that is recorded as an honest "unknown" rather
    than left out, so the repository list stays complete.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `owner/name`, the canonical slug of `RepositoryRef`.
    repository: str
    sha: str | None = None


class EvalBaselinePin(BaseModel):
    """One repository of the frozen baseline an eval run starts from (#967).

    Copied from the eval at admission, once its baseline was frozen, so the run
    records the exact commit it was launched against without reading the eval
    again: a branch that moves later, or an eval read model that lags, changes
    nothing here. Unlike `SourceCommit` the sha is never unknown - an eval
    refuses a ref it could not pin.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `owner/name`, the canonical slug of `RepositoryRef`.
    repository: str
    #: The branch, tag or sha a person asked for, kept for display.
    requested_ref: str
    #: The full commit sha it resolved to: what the run checks out.
    commit_sha: str


class ResumeOrigin(BaseModel):
    """Where a resumed execution came from (ADR-014 s7).

    Copied from the parent's `ExecutionResumed`, which is the decision; this is
    the child recording which decision it is carrying out, so the child's own
    stream answers "what was this a resume of" without reading the parent's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_execution_id: str
    #: The parent's completed prefix, in phase order. The child never runs
    #: these; their artifacts are the ones it hands forward.
    inherited_phases: list[InheritedPhase]
    resume_phase_id: str

    def owner_of(self, phase: InheritedPhase) -> str:
        """The execution holding ``phase``'s artifacts.

        The one reading of `InheritedPhase.origin_execution_id`, so a stream
        written before it existed replays as it was meant: owned by the parent.
        """
        return phase.origin_execution_id or self.parent_execution_id

    def owners(self) -> dict[str, str]:
        """Every inherited phase's owner, by phase id."""
        return {p.phase_id: self.owner_of(p) for p in self.inherited_phases}


# Re-exported for `WorkflowExecutionStarted` (#1513): a domain event imports its
# value objects from this module, and this one is past the file-size limit.
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (  # noqa: E402
    AbandonedBranch as AbandonedBranch,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (  # noqa: E402
    ContinuedBranch as ContinuedBranch,
)

# --- Delegation failure (#894) -------------------------------------------
#
# Why a phase that declared delegation is recorded as not having delegated.
# A value object rather than prose in ``error``: the reason and the delegates
# the platform observed are what an operator acts on - a delegate that never
# launched and a delegate that launched and failed are different incidents -
# and a client cannot select between them by parsing a sentence. Carried from
# the failure command through `WorkflowFailedEvent` to the execution detail
# read model and its API response, unchanged at every hop.
#
# It is a platform-observed fact, never the agent's word, which is why it is a
# field of its own and not a `ReportedFailureReason`. It lives here, not in a
# module of its own, because `WorkflowFailedEvent` carries it and an event may
# import value objects and nothing else from its aggregate (VSA).


class DelegationFailureReason(StrEnum):
    """Why a required delegation is counted as not having happened."""

    NOT_ATTEMPTED = "not_attempted"
    """The record was read and holds no delegation at all."""
    FAILED = "failed"
    """Delegates were launched and none of them succeeded."""
    UNVERIFIABLE = "unverifiable"
    """No record could be read, so success cannot be shown."""


class DelegationAttempt(BaseModel):
    """One delegate the phase's agent launched, as the platform observed it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delegate_id: str
    """The journal's id for this child invocation."""
    target_harness: str
    """Which harness the work was delegated TO (``claude``, ``codex``)."""
    outcome: DelegationOutcome | None
    """How it ended; None when it launched and never reported an end."""
    exit_code: int | None = None
    reason: str | None = None
    """Why it could not launch, when the shim named a reason."""

    def describe(self) -> str:
        ended = self.outcome.value if self.outcome is not None else "never reported an outcome"
        detail = [f"exit_code={self.exit_code}"] if self.exit_code is not None else []
        if self.reason is not None:
            detail.append(f"reason={self.reason}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        return f"delegate {self.delegate_id} -> {self.target_harness}: {ended}{suffix}"


class DelegationFailure(BaseModel):
    """The typed account of a failed required delegation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: DelegationFailureReason
    attempts: tuple[DelegationAttempt, ...] = ()
    """Every cross-harness delegate the record held; empty for `not_attempted`
    and `unverifiable`."""
    detail: str | None = None
    """Why the record could not be read, for `unverifiable`."""

    @classmethod
    def from_stored(cls, value: object) -> DelegationFailure | None:
        """The stored account, `None` for a failure that recorded none.

        Every row and event written before #894 has no such key, and replays
        as `None` rather than raising.
        """
        return None if value is None else cls.model_validate(value)
