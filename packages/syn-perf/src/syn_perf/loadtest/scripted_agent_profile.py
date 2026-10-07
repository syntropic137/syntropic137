"""What a stub agent does in each phase of a load-test execution (plan 6.1, #1310).

A load test replaces the agent CLI with a replayer (the stub image, step 7b in
agentic-workspace) so N executions can run without spending a token. The
stub has to exercise the same platform paths a real agent does, or the test
measures something that never happens in production. This module is the
contract between the driver that configures a run and the image that carries
it out: one ``ScriptedAgentProfile`` per run, passed to every workspace as a
single JSON environment variable, keyed by phase id.

Two rules make it trustworthy, and both are enforced here rather than left to
whoever writes a profile by hand (and the profile is read-only once
validated, so neither can be undone after the fact):

- **Side effects follow the workflow, not a list.** ``for_workflow`` derives
  each phase's side effect from the same ``WorkflowDefinition`` fields the
  real execution path reads (``delivers_repo_changes``, ``clone_repos``) and
  the phase order, and checks each recording against the phase's agent
  provider. On the node tier that reproduces the real PR lifecycle: the first
  pushing phase opens a draft, the phase with no tree marks it ready. A phase that
  changes its contract changes its stub with it.
- **The review verdict is declared, and the run follows it.** Each phase's
  ``review_verdict`` is what the stub's ``TASK_RESULT`` reports, so it is the
  value the engine reads, not prose in an artifact. The profile plans the run
  with the aggregate's own ``next_phase``, and the final outcome (``READY`` or
  ``DRAFT``, the repair rounds, whether the PR is marked ready) is derived from
  that plan, so no profile can claim a round or a certification it never ran.
- **The fixture repository is never this one.** Implement and fix push a
  branch per execution; at 100 executions that must not land on
  ``syntropic137/syntropic137``.

"Scripted", not "Stub": these are production contract models describing a
scripted workload, not test doubles, and the ADR-060 in-memory guard treats a
``Stub*`` class as one. See "Scripted Agent" in
docs/architecture/orchestration-ubiquitous-language.md.

Nothing in production reads this. The stub is selected only by the load-test
stack's workspace image (plan 6.3).
"""

from __future__ import annotations

import re
import string
from collections.abc import Mapping  # noqa: TC003 - pydantic resolves the field type at runtime
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import next_phase
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)
from syn_perf.loadtest.handoff import FULL_SHA
from syn_perf.loadtest.implement_v3_artifacts import (
    IMPLEMENT_V3_ARTIFACTS,
    IMPLEMENT_V3_REVIEW_VERDICTS,
    ReviewVerdictName,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import WorkflowDefinition
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        PhaseYamlDefinition,
    )

SCRIPTED_AGENT_PROFILE_ENV: Final = "SYN_SCRIPTED_AGENT_PROFILE"
"""The one environment variable a stub workspace reads its profile from."""

LOADTEST_BRANCH_PREFIX: Final = "loadtest/"
"""Every load-test branch is ``loadtest/<execution_id>`` on the fixture repo."""

_FORBIDDEN_FIXTURE_REPOS: Final = frozenset({"syntropic137/syntropic137"})

#: The only fields an artifact template may name. Anything else is a typo the
#: stub could not fill, so it is refused when the profile is built rather than
#: when the hundredth workspace tries to render it.
_ARTIFACT_FIELDS: Final = frozenset(
    {
        "execution_id",
        "branch",
        "head_sha",
        "pull_request",
        "review_verdict",
        "outcome",
        "repair_rounds",
    }
)

_NO_PULL_REQUEST: Final = "none (the platform tier opens no pull request)"
"""What ``{pull_request}`` renders as on the platform tier."""

# Same shape the workflow parser accepts for a phase id
# (``PHASE_ID_PATTERN`` in syn_domain's workflow_definition).
PhaseId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")]


class _Contract(BaseModel):
    # JSON has no infinity or NaN: pydantic writes them as ``null``, which
    # ``from_env`` then refuses, so a profile that validated here would fail in
    # every workspace it was sent to.
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def _named_fields(template: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


class ScriptedStream(_Contract):
    """The recorded session a phase replays, and how fast.

    The harness decides the format - ``claude`` replays stream-json, ``codex``
    replays JSONL - so it is not declared twice. ``cli_version`` is the
    version the recording was captured from; the driver refuses a run whose
    pinned image carries a different one (plan section 8), because a stream
    from another CLI version exercises a parser production no longer runs.
    """

    harness: Literal["claude", "codex"]
    recording: str = Field(min_length=1)
    """Path of the recording inside the stub image."""
    cli_version: str = Field(min_length=1)
    pacing_factor: float = Field(default=1.0, ge=0)
    """Recorded inter-event timing multiplied by this. ``0`` replays at once."""


class NoWorkload(_Contract):
    kind: Literal["none"] = "none"


class SyntheticWorkload(_Contract):
    """Burn this much CPU, hold this much memory, write this much disk.

    Disk goes outside the repository or to an ignored path, so a phase that
    must leave its tree clean still does.
    """

    kind: Literal["synthetic"] = "synthetic"
    cpu_seconds: float = Field(ge=0)
    mem_bytes: int = Field(ge=0)
    disk_bytes: int = Field(ge=0)


class GatesWorkload(_Contract):
    """Run ``just preflight-agent`` in the cloned repository - the real gates."""

    kind: Literal["gates"] = "gates"


Workload = Annotated[NoWorkload | SyntheticWorkload | GatesWorkload, Field(discriminator="kind")]


class ReportOnly(_Contract):
    """Write the artifact and leave the working tree exactly as cloned.

    The real phase declares ``delivers_repo_changes: false``, which does not
    yet exempt a dirty tree from the unpushed-work guard (nothing mounts the
    repository read-only, ``unpushed_work_guard.py``), so a stub that left a
    file behind would fail where the real phase passes.
    """

    kind: Literal["report_only"] = "report_only"


class PushBranch(_Contract):
    """Commit one deterministic file and push ``loadtest/<execution_id>``.

    The file is ``loadtest/<phase_id>.txt`` holding ``<execution_id>
    <phase_id>``, committed on top of the branch if an earlier phase already
    pushed it, so implement and fix both land on one branch as they do for
    real. The artifact names the branch.
    """

    kind: Literal["push_branch"] = "push_branch"


class OpenDraftPullRequest(_Contract):
    """Push exactly as ``PushBranch`` does, then ``gh pr create --draft`` from it.

    Node tier only, and only the first phase that delivers repository changes:
    the real implement phase opens a draft on its first push and records its
    number and URL, and every later pushing phase lands on that same PR. The
    driver closes it afterwards.
    """

    kind: Literal["open_draft_pull_request"] = "open_draft_pull_request"


class MarkPullRequestReady(_Contract):
    """``gh pr ready`` the draft an earlier phase opened on the fixture repo.

    Node tier only. The real finalize_pr phase is the only one allowed to mark
    the PR ready (#1197). The phase has no working tree (``clone_repos:
    false``).
    """

    kind: Literal["mark_pull_request_ready"] = "mark_pull_request_ready"


class VerifyRemoteBranch(_Contract):
    """``git ls-remote`` the execution's branch and fail if it is absent.

    The platform-tier stand-in for the PR lifecycle, so 100 executions do not
    open 100 PRs. The phase has no working tree (``clone_repos: false``).
    """

    kind: Literal["verify_remote_branch"] = "verify_remote_branch"


SideEffect = Annotated[
    ReportOnly | PushBranch | OpenDraftPullRequest | MarkPullRequestReady | VerifyRemoteBranch,
    Field(discriminator="kind"),
]

_NO_WORKING_TREE: Final = (MarkPullRequestReady, VerifyRemoteBranch)
_TOUCHES_A_PR: Final = (OpenDraftPullRequest, MarkPullRequestReady)

#: The PR side effects a profile may run, in phase order: none (platform tier),
#: a draft nobody marks ready, or the real lifecycle.
_PR_LIFECYCLES: Final = frozenset(
    {(), ("open_draft_pull_request",), ("open_draft_pull_request", "mark_pull_request_ready")}
)


class ScriptedPhase(_Contract):
    """Everything the stub does in one phase."""

    stream: ScriptedStream
    workload: Workload
    side_effect: SideEffect
    artifact: str = Field(min_length=1)
    """Markdown written to ``artifacts/output/<phase_id>.md``. May name
    ``{execution_id}``, ``{branch}``, ``{head_sha}``, ``{pull_request}``,
    ``{review_verdict}`` (this phase's, upper-cased), and ``{outcome}`` and
    ``{repair_rounds}`` (how the planned run ends); literal braces are doubled."""
    review_verdict: ReviewVerdictName | None = None
    """The ``review_verdict`` this phase's ``TASK_RESULT`` reports, or none.

    The stub ends the phase with ``ScriptedAgentProfile.task_result`` as its
    last message and does not replay the recording's own ``TASK_RESULT``, so
    this field, not the recording, is what the engine's verdict reader sees."""

    @model_validator(mode="after")
    def _consistent(self) -> ScriptedPhase:
        if isinstance(self.workload, GatesWorkload) and isinstance(
            self.side_effect, _NO_WORKING_TREE
        ):
            msg = (
                f"a {self.side_effect.kind} phase has no working tree, so it "
                "cannot run the gates workload"
            )
            raise ValueError(msg)
        if unknown := _named_fields(self.artifact) - _ARTIFACT_FIELDS:
            msg = (
                f"artifact names {sorted(unknown)}; only {sorted(_ARTIFACT_FIELDS)} "
                "can be filled (double a literal brace)"
            )
            raise ValueError(msg)
        return self


class ScriptedAgentProfile(_Contract):
    """One load-test run's instructions to the stub agent, per phase id."""

    ENV: ClassVar[str] = SCRIPTED_AGENT_PROFILE_ENV

    tier: Literal["platform", "node"]
    fixture_repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    """``owner/name`` of the dedicated repository the stub pushes to."""
    phases: Annotated[
        Mapping[PhaseId, ScriptedPhase],
        Field(min_length=1),
        AfterValidator(MappingProxyType),
        PlainSerializer(dict, return_type=dict[PhaseId, ScriptedPhase]),
    ]
    """Read-only once validated: ``frozen`` stops reassigning the field, and
    this stops editing it in place, so no phase can be added or swapped after
    the checks below have passed it."""

    @model_validator(mode="after")
    def _safe_to_run_at_scale(self) -> ScriptedAgentProfile:
        if self.fixture_repo.lower() in _FORBIDDEN_FIXTURE_REPOS:
            msg = f"{self.fixture_repo} cannot be the load-test fixture repository"
            raise ValueError(msg)
        if self.tier == "platform":
            touching = sorted(
                phase_id
                for phase_id, phase in self.phases.items()
                if isinstance(phase.side_effect, _TOUCHES_A_PR)
            )
            if touching:
                msg = (
                    f"platform tier must not touch pull requests (phases {touching}); "
                    "use push_branch and verify_remote_branch"
                )
                raise ValueError(msg)
        lifecycle = tuple(
            phase.side_effect.kind
            for phase in self.phases.values()
            if isinstance(phase.side_effect, _TOUCHES_A_PR)
        )
        if lifecycle not in _PR_LIFECYCLES:
            msg = (
                f"pull request side effects run {list(lifecycle)}; exactly one phase "
                "opens the draft pull request, before the one that marks it ready"
            )
            raise ValueError(msg)
        run = self.planned_run()
        ran = [self.phases[p].side_effect for p in run.ran]
        opened = any(isinstance(s, OpenDraftPullRequest) for s in ran)
        readied = any(isinstance(s, MarkPullRequestReady) for s in ran)
        if readied != (opened and run.ended_on == "certified"):
            msg = (
                f"the run is {list(run.ran)} and ends {run.ended_on or 'with no verdict'}; "
                "a phase that runs marks the draft ready exactly when the run ends certified"
            )
            raise ValueError(msg)
        return self

    def planned_run(self) -> PlannedRun:
        """The phases this profile's verdicts make the engine run, and how it ends."""
        ran, ended_on = _walk({p: phase.review_verdict for p, phase in self.phases.items()})
        pushes = sum(
            isinstance(self.phases[p].side_effect, (PushBranch, OpenDraftPullRequest)) for p in ran
        )
        return PlannedRun(ran=ran, ended_on=ended_on, repair_rounds=max(pushes - 1, 0))

    def task_result(self, phase_id: str) -> str:
        """The ``TASK_RESULT`` block the stub writes as its last message in ``phase_id``."""
        phase = self.phases[phase_id]
        report = _TaskResult(
            side_effects="none" if isinstance(phase.side_effect, ReportOnly) else "succeeded",
            comments=f"Load-test stub for phase {phase_id}; no agent ran.",
            review_verdict=phase.review_verdict,
        )
        return f"TASK_RESULT: {report.model_dump_json(exclude_none=True)}\nTASK_RESULT_END"

    @staticmethod
    def branch(execution_id: str) -> str:
        return f"{LOADTEST_BRANCH_PREFIX}{execution_id}"

    def render_artifact(
        self,
        phase_id: str,
        execution_id: str,
        head_sha: str | None = None,
        pr_url: str | None = None,
    ) -> str:
        """The exact artifact text the stub writes for this phase and execution.

        ``head_sha`` is the full commit the execution's branch is at when the
        phase writes its artifact: ``git rev-parse HEAD`` after pushing
        (implement, fix) or checking out (verify, reverify), the ``git
        ls-remote`` result where there is no tree (finalize_pr). A template
        that names it will not render without a full 40-character SHA.

        ``pr_url`` is the draft the node tier opened on the fixture repository;
        ``{pull_request}`` renders as its number and URL. The platform tier
        opens none, so it takes no URL and says so.
        """
        phase = self.phases[phase_id]
        template = phase.artifact
        named = _named_fields(template)
        run = self.planned_run()
        if "head_sha" in named and not (head_sha and FULL_SHA.fullmatch(head_sha)):
            msg = f"phase {phase_id} artifact names the head; {head_sha!r} is not a full SHA"
            raise ValueError(msg)
        return template.format(
            execution_id=execution_id,
            branch=self.branch(execution_id),
            head_sha=head_sha,
            pull_request=self._pull_request(phase_id, pr_url) if "pull_request" in named else None,
            review_verdict=(phase.review_verdict or "no verdict").upper(),
            outcome="READY" if run.ended_on == "certified" else "DRAFT",
            repair_rounds=run.repair_rounds,
        )

    def _pull_request(self, phase_id: str, pr_url: str | None) -> str:
        if self.tier == "platform":
            if pr_url is not None:
                msg = f"phase {phase_id}: the platform tier opens no pull request, got {pr_url}"
                raise ValueError(msg)
            return _NO_PULL_REQUEST
        on_fixture = re.fullmatch(
            rf"https://github\.com/{re.escape(self.fixture_repo)}/pull/([1-9][0-9]*)",
            pr_url or "",
            re.IGNORECASE,
        )
        if not on_fixture:
            msg = (
                f"phase {phase_id} artifact names the pull request; {pr_url!r} is not "
                f"a pull request on {self.fixture_repo}"
            )
            raise ValueError(msg)
        return f"#{on_fixture[1]} {pr_url}"

    def to_env(self) -> dict[str, str]:
        return {self.ENV: self.model_dump_json()}

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> ScriptedAgentProfile:
        try:
            raw = environ[cls.ENV]
        except KeyError:
            msg = f"{cls.ENV} is not set; a stub workspace cannot run without its profile"
            raise LookupError(msg) from None
        return cls.model_validate_json(raw)

    @classmethod
    def for_workflow(
        cls,
        workflow: WorkflowDefinition,
        *,
        tier: Literal["platform", "node"],
        fixture_repo: str,
        streams: Mapping[str, ScriptedStream],
        workload: NoWorkload | SyntheticWorkload | GatesWorkload,
        artifacts: Mapping[str, str] = IMPLEMENT_V3_ARTIFACTS,
        review_verdicts: Mapping[str, ReviewVerdictName] = IMPLEMENT_V3_REVIEW_VERDICTS,
    ) -> ScriptedAgentProfile:
        """Build the profile for every phase of ``workflow``.

        The side effect is the real phase's contract: ``delivers_repo_changes``
        means a pushed branch, and on the node tier the first such phase also
        opens the draft PR; no working tree means the phase finishes through
        the remote (marking that PR ready on the node tier, checking the branch
        on the platform tier); anything else leaves the tree clean.
        ``workload`` applies to every phase that has a tree to work in. Each
        stream must replay the harness the phase actually runs, and the
        streams and artifacts must cover exactly the workflow's phases - a
        missing one is an error, never a default, and a leftover one is a stub
        for a phase the workflow no longer has. ``review_verdicts`` names the
        phases that report one; the PR is marked ready only if the run they
        produce ends certified, and otherwise stays a draft.
        """
        ids = {p.id for p in workflow.phases}
        mismatched = {
            name: {"missing": sorted(ids - set(given)), "extra": sorted(set(given) - ids)}
            for name, given in (("streams", streams), ("artifacts", artifacts))
            if set(given) != ids
        }
        if mismatched:
            msg = f"workflow {workflow.id} phases and stubs differ: {mismatched}"
            raise ValueError(msg)
        if unknown := sorted(set(review_verdicts) - ids):
            msg = f"workflow {workflow.id} has no phases {unknown} to report a review verdict"
            raise ValueError(msg)

        first_push = next((p.id for p in workflow.phases if _pushes(p)), None)
        _, ended_on = _walk({p.id: review_verdicts.get(p.id) for p in workflow.phases})
        phases = {
            phase.id: ScriptedPhase(
                stream=_stream_for(phase, streams[phase.id]),
                workload=workload if phase.clone_repos else NoWorkload(),
                side_effect=_side_effect_for(
                    phase,
                    tier,
                    opens_the_pr=phase.id == first_push,
                    marks_ready=ended_on == "certified",
                ),
                artifact=artifacts[phase.id],
                review_verdict=review_verdicts.get(phase.id),
            )
            for phase in workflow.phases
        }
        return cls(tier=tier, fixture_repo=fixture_repo, phases=phases)


def _stream_for(phase: PhaseYamlDefinition, stream: ScriptedStream) -> ScriptedStream:
    provider = (phase.agent.provider if phase.agent else None) or "claude"
    if stream.harness != provider:
        msg = (
            f"phase {phase.id} runs {provider} but its recording is "
            f"{stream.harness}; the stub would exercise the wrong harness"
        )
        raise ValueError(msg)
    return stream


def _pushes(phase: PhaseYamlDefinition) -> bool:
    return phase.clone_repos and phase.delivers_repo_changes


def _side_effect_for(
    phase: PhaseYamlDefinition,
    tier: Literal["platform", "node"],
    *,
    opens_the_pr: bool,
    marks_ready: bool,
) -> ReportOnly | PushBranch | OpenDraftPullRequest | MarkPullRequestReady | VerifyRemoteBranch:
    node = tier == "node"
    if not phase.clone_repos:
        if not node:
            return VerifyRemoteBranch()
        # A run that ends blocked or unreported leaves the draft a draft.
        return MarkPullRequestReady() if marks_ready else ReportOnly()
    if _pushes(phase):
        return OpenDraftPullRequest() if node and opens_the_pr else PushBranch()
    return ReportOnly()


@dataclass(frozen=True)
class PlannedRun:
    """What a profile's declared verdicts make the engine do."""

    ran: tuple[str, ...]
    """The phases that run, in order; the rounds a certification skips are absent."""
    ended_on: ReviewVerdictName | None
    """The last verdict any phase that ran reported, as the aggregate records it."""
    repair_rounds: int
    """Pushing phases that ran after the first: the fix rounds."""


class _TaskResult(_Contract):
    success: Literal[True] = True
    side_effects: Literal["none", "succeeded"]
    comments: str
    review_verdict: ReviewVerdictName | None = None


def _walk(
    verdicts: Mapping[str, ReviewVerdictName | None],
) -> tuple[tuple[str, ...], ReviewVerdictName | None]:
    """Sequence ``verdicts`` (phase id -> verdict, in phase order) with the aggregate's rule."""
    definitions = [PhaseDefinition(phase_id=p, name=p, order=n) for n, p in enumerate(verdicts)]
    ran: list[str] = []
    ended_on: ReviewVerdictName | None = None
    at = definitions[0] if definitions else None
    while at is not None:
        ran.append(at.phase_id)
        said = verdicts[at.phase_id]
        ended_on = said or ended_on
        step = next_phase(definitions, at.order, ReviewVerdict(said) if said else None)
        at = step.phase if step else None
    return tuple(ran), ended_on
