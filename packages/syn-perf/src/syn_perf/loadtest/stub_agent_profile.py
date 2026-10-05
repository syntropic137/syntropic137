"""What a stub agent does in each phase of a load-test execution (plan 6.1, #1310).

A load test replaces the agent CLI with a replayer (the stub image, step 7b in
agentic-workspace) so N executions can run without spending a token. The
stub has to exercise the same platform paths a real agent does, or the test
measures something that never happens in production. This module is the
contract between the driver that configures a run and the image that carries
it out: one ``StubAgentProfile`` per run, passed to every workspace as a
single JSON environment variable, keyed by phase id.

Two rules make it trustworthy, and both are enforced here rather than left to
whoever writes a profile by hand:

- **Side effects follow the workflow, not a list.** ``for_workflow`` derives
  each phase's side effect from the same ``WorkflowDefinition`` fields the
  real execution path reads (``delivers_repo_changes``, ``clone_repos``), and
  checks each recording against the phase's agent provider. A phase that
  changes its contract changes its stub with it.
- **The fixture repository is never this one.** Implement and fix push a
  branch per execution; at 100 executions that must not land on
  ``syntropic137/syntropic137``.

Nothing in production reads this. The stub is selected only by the load-test
stack's workspace image (plan 6.3).
"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from syn_perf.loadtest.implement_v3_artifacts import IMPLEMENT_V3_ARTIFACTS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration import WorkflowDefinition

STUB_AGENT_PROFILE_ENV: Final = "SYN_STUB_AGENT_PROFILE"
"""The one environment variable a stub workspace reads its profile from."""

LOADTEST_BRANCH_PREFIX: Final = "loadtest/"
"""Every load-test branch is ``loadtest/<execution_id>`` on the fixture repo."""

_FORBIDDEN_FIXTURE_REPOS: Final = frozenset({"syntropic137/syntropic137"})

#: The only fields an artifact template may name. Anything else is a typo the
#: stub could not fill, so it is refused when the profile is built rather than
#: when the hundredth workspace tries to render it.
_ARTIFACT_FIELDS: Final = frozenset({"execution_id", "branch"})

# Same shape the workflow parser accepts for a phase id
# (``PHASE_ID_PATTERN`` in syn_domain's workflow_definition).
PhaseId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")]


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StubStream(_Contract):
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


class OpenPullRequest(_Contract):
    """``gh pr create`` from the execution's branch on the fixture repo.

    Node tier only; the driver closes it afterwards. The phase has no
    working tree (``clone_repos: false``).
    """

    kind: Literal["open_pull_request"] = "open_pull_request"


class VerifyRemoteBranch(_Contract):
    """``git ls-remote`` the execution's branch and fail if it is absent.

    The platform-tier stand-in for opening a PR, so 100 executions do not
    open 100 PRs. The phase has no working tree (``clone_repos: false``).
    """

    kind: Literal["verify_remote_branch"] = "verify_remote_branch"


SideEffect = Annotated[
    ReportOnly | PushBranch | OpenPullRequest | VerifyRemoteBranch,
    Field(discriminator="kind"),
]

_NO_WORKING_TREE: Final = (OpenPullRequest, VerifyRemoteBranch)


class StubPhase(_Contract):
    """Everything the stub does in one phase."""

    stream: StubStream
    workload: Workload
    side_effect: SideEffect
    artifact: str = Field(min_length=1)
    """Markdown written to ``artifacts/output/<phase_id>.md``. May name
    ``{execution_id}`` and ``{branch}``; literal braces are doubled."""

    @model_validator(mode="after")
    def _consistent(self) -> StubPhase:
        if isinstance(self.workload, GatesWorkload) and isinstance(
            self.side_effect, _NO_WORKING_TREE
        ):
            msg = (
                f"a {self.side_effect.kind} phase has no working tree, so it "
                "cannot run the gates workload"
            )
            raise ValueError(msg)
        named = {field for _, field, _, _ in string.Formatter().parse(self.artifact) if field}
        if unknown := named - _ARTIFACT_FIELDS:
            msg = (
                f"artifact names {sorted(unknown)}; only {sorted(_ARTIFACT_FIELDS)} "
                "can be filled (double a literal brace)"
            )
            raise ValueError(msg)
        return self


class StubAgentProfile(_Contract):
    """One load-test run's instructions to the stub agent, per phase id."""

    ENV: ClassVar[str] = STUB_AGENT_PROFILE_ENV

    tier: Literal["platform", "node"]
    fixture_repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    """``owner/name`` of the dedicated repository the stub pushes to."""
    phases: dict[PhaseId, StubPhase] = Field(min_length=1)

    @model_validator(mode="after")
    def _safe_to_run_at_scale(self) -> StubAgentProfile:
        if self.fixture_repo.lower() in _FORBIDDEN_FIXTURE_REPOS:
            msg = f"{self.fixture_repo} cannot be the load-test fixture repository"
            raise ValueError(msg)
        if self.tier == "platform":
            opening = sorted(
                phase_id
                for phase_id, phase in self.phases.items()
                if isinstance(phase.side_effect, OpenPullRequest)
            )
            if opening:
                msg = (
                    f"platform tier must not open pull requests (phases {opening}); "
                    "use verify_remote_branch"
                )
                raise ValueError(msg)
        return self

    @staticmethod
    def branch(execution_id: str) -> str:
        return f"{LOADTEST_BRANCH_PREFIX}{execution_id}"

    def render_artifact(self, phase_id: str, execution_id: str) -> str:
        """The exact artifact text the stub writes for this phase and execution."""
        return self.phases[phase_id].artifact.format(
            execution_id=execution_id, branch=self.branch(execution_id)
        )

    def to_env(self) -> dict[str, str]:
        return {self.ENV: self.model_dump_json()}

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> StubAgentProfile:
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
        streams: Mapping[str, StubStream],
        workload: NoWorkload | SyntheticWorkload | GatesWorkload,
        artifacts: Mapping[str, str] = IMPLEMENT_V3_ARTIFACTS,
    ) -> StubAgentProfile:
        """Build the profile for every phase of ``workflow``.

        The side effect is the real phase's contract: no working tree means
        the phase delivers through the remote (a PR on the node tier, a branch
        check on the platform tier); ``delivers_repo_changes`` means a pushed
        branch; anything else leaves the tree clean. ``workload`` applies to
        every phase that has a tree to work in. Each stream must replay the
        harness the phase actually runs, and every phase needs both a stream
        and an artifact - a missing one is an error, never a default.
        """
        missing = {
            "streams": sorted(p.id for p in workflow.phases if p.id not in streams),
            "artifacts": sorted(p.id for p in workflow.phases if p.id not in artifacts),
        }
        if any(missing.values()):
            msg = f"workflow {workflow.id} phases without a stub: {missing}"
            raise ValueError(msg)

        phases: dict[str, StubPhase] = {}
        for phase in workflow.phases:
            stream = streams[phase.id]
            provider = (phase.agent.provider if phase.agent else None) or "claude"
            if stream.harness != provider:
                msg = (
                    f"phase {phase.id} runs {provider} but its recording is "
                    f"{stream.harness}; the stub would exercise the wrong harness"
                )
                raise ValueError(msg)
            side_effect: ReportOnly | PushBranch | OpenPullRequest | VerifyRemoteBranch
            if not phase.clone_repos:
                side_effect = OpenPullRequest() if tier == "node" else VerifyRemoteBranch()
            elif phase.delivers_repo_changes:
                side_effect = PushBranch()
            else:
                side_effect = ReportOnly()
            phases[phase.id] = StubPhase(
                stream=stream,
                workload=workload if phase.clone_repos else NoWorkload(),
                side_effect=side_effect,
                artifact=artifacts[phase.id],
            )
        return cls(tier=tier, fixture_repo=fixture_repo, phases=phases)
