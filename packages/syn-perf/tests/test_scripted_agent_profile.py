"""The load-test contract (plan 6.1, #1310) against the workflow it stands in for."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_execution.review_rounds import next_phase
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
    ReviewVerdict,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
    VerdictStatus,
)
from syn_perf.loadtest import (
    HEAD_SHA_LINE,
    GatesWorkload,
    MarkPullRequestReady,
    NoWorkload,
    OpenDraftPullRequest,
    PushBranch,
    ReportOnly,
    ScriptedAgentProfile,
    ScriptedPhase,
    ScriptedStream,
    SyntheticWorkload,
    VerifyRemoteBranch,
    head_sha_handed_over,
)
from syn_perf.loadtest.implement_v3_artifacts import IMPLEMENT_V3_ARTIFACTS

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_WORKFLOW = _REPO / "workflows/sdlc/implement-v3/workflow.yaml"
_PHASES = [p.id for p in WorkflowDefinition.from_file(_WORKFLOW).phases]
"""The workflow's phase ids in order, read from the YAML rather than listed."""
_AFTER_PREMISE = _PHASES[1:]
"""Every phase that names the head it hands over, in workflow order."""
_SCHEMA = _REPO / "packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.schema.json"
_FIXTURE = "syntropic137/loadtest-fixture"
_HEAD = "3b7f2bd49a4609f24a516bb4617aadbc1edf751e"
_PUSHED_OVER = "0f0e0d0c0b0a09080706050403020100ffeeddcc"
_PR_URL = f"https://github.com/{_FIXTURE}/pull/4217"


@pytest.fixture(scope="module")
def workflow() -> WorkflowDefinition:
    return WorkflowDefinition.from_file(_WORKFLOW)


def _streams(workflow: WorkflowDefinition) -> dict[str, ScriptedStream]:
    """One recording per phase, matching the harness the phase really runs."""
    return {
        p.id: ScriptedStream(
            harness=(p.agent.provider if p.agent else None) or "claude",
            recording=f"/recordings/{p.id}.jsonl",
            cli_version="9.9.9",
            pacing_factor=0.25,
        )
        for p in workflow.phases
    }


def _profile(
    workflow: WorkflowDefinition,
    tier: str,
    workload: object = None,
    review_verdicts: dict[str, str] | None = None,
) -> ScriptedAgentProfile:
    return ScriptedAgentProfile.for_workflow(
        workflow,
        tier=tier,  # type: ignore[arg-type]
        fixture_repo=_FIXTURE,
        streams=_streams(workflow),
        workload=workload or SyntheticWorkload(cpu_seconds=3, mem_bytes=2**20, disk_bytes=4096),  # type: ignore[arg-type]
        **({} if review_verdicts is None else {"review_verdicts": review_verdicts}),  # type: ignore[arg-type]
    )


_ALL_BLOCKED = {"reverify": "blocked", "reverify_2": "blocked", "reverify_3": "blocked"}


# --- side effects come from the real phase contract -----------------------


def test_side_effects_follow_the_implement_v3_phase_contracts(
    workflow: WorkflowDefinition,
) -> None:
    kinds = {pid: type(p.side_effect) for pid, p in _profile(workflow, "node").phases.items()}

    assert kinds == {
        "premise": ReportOnly,
        "implement": OpenDraftPullRequest,
        "verify": ReportOnly,
        "fix": PushBranch,
        "reverify": ReportOnly,
        "fix_2": PushBranch,
        "reverify_2": ReportOnly,
        "fix_3": PushBranch,
        "reverify_3": ReportOnly,
        "finalize_pr": MarkPullRequestReady,
    }


def test_the_stubs_cover_exactly_the_workflows_phases(workflow: WorkflowDefinition) -> None:
    """A phase added to, renamed in or removed from the workflow fails here first."""
    assert list(IMPLEMENT_V3_ARTIFACTS) == [p.id for p in workflow.phases]
    assert _AFTER_PREMISE[0] == "implement"
    assert _AFTER_PREMISE[-1] == "finalize_pr"


def test_a_stub_for_a_phase_the_workflow_no_longer_has_is_refused(
    workflow: WorkflowDefinition,
) -> None:
    artifacts = {**IMPLEMENT_V3_ARTIFACTS, "fix_4": "Round: 4 of 3"}

    with pytest.raises(ValueError, match=r"'extra': \['fix_4'\]"):
        ScriptedAgentProfile.for_workflow(
            workflow,
            tier="node",
            fixture_repo=_FIXTURE,
            streams=_streams(workflow),
            workload=NoWorkload(),
            artifacts=artifacts,
        )


def test_side_effects_track_the_workflow_flags_not_the_phase_ids(
    workflow: WorkflowDefinition,
) -> None:
    """Flip the flags on one phase and its stub must follow."""
    phases = [
        p.model_copy(update={"delivers_repo_changes": False}) if p.id == "implement" else p
        for p in workflow.phases
    ]
    changed = workflow.model_copy(update={"phases": phases})

    assert isinstance(_profile(changed, "node").phases["implement"].side_effect, ReportOnly)


def test_the_draft_is_opened_by_the_first_pushing_phase_whatever_its_id(
    workflow: WorkflowDefinition,
) -> None:
    """Stop implement delivering, and the PR moves to the next phase that pushes."""
    phases = [
        p.model_copy(update={"delivers_repo_changes": False}) if p.id == "implement" else p
        for p in workflow.phases
    ]
    profile = _profile(workflow.model_copy(update={"phases": phases}), "node")

    assert isinstance(profile.phases["fix"].side_effect, OpenDraftPullRequest)
    assert isinstance(profile.phases["fix_2"].side_effect, PushBranch)


def test_platform_tier_checks_the_branch_instead_of_touching_a_pr(
    workflow: WorkflowDefinition,
) -> None:
    profile = _profile(workflow, "platform")

    assert isinstance(profile.phases["implement"].side_effect, PushBranch)
    assert isinstance(profile.phases["finalize_pr"].side_effect, VerifyRemoteBranch)
    assert not any(
        isinstance(p.side_effect, OpenDraftPullRequest | MarkPullRequestReady)
        for p in profile.phases.values()
    )


def test_gates_run_where_there_is_a_tree_and_nowhere_else(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "node", GatesWorkload())

    assert isinstance(profile.phases["finalize_pr"].workload, NoWorkload)
    assert all(
        isinstance(p.workload, GatesWorkload)
        for pid, p in profile.phases.items()
        if pid != "finalize_pr"
    )


def test_a_recording_from_the_wrong_harness_is_refused(workflow: WorkflowDefinition) -> None:
    streams = _streams(workflow)
    streams["verify"] = streams["verify"].model_copy(update={"harness": "claude"})

    with pytest.raises(ValueError, match="phase verify runs codex"):
        ScriptedAgentProfile.for_workflow(
            workflow, tier="node", fixture_repo=_FIXTURE, streams=streams, workload=NoWorkload()
        )


def test_a_phase_without_a_stream_is_an_error_not_a_default(workflow: WorkflowDefinition) -> None:
    streams = _streams(workflow)
    del streams["fix"]

    with pytest.raises(ValueError, match="'fix'"):
        ScriptedAgentProfile.for_workflow(
            workflow, tier="node", fixture_repo=_FIXTURE, streams=streams, workload=NoWorkload()
        )


# --- what crosses into the workspace --------------------------------------


def test_the_profile_survives_the_env_var_unchanged(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "node")

    env = profile.to_env()
    restored = ScriptedAgentProfile.from_env(env)

    assert list(env) == ["SYN_SCRIPTED_AGENT_PROFILE"]
    assert restored == profile
    assert restored.phases["verify"].stream.pacing_factor == 0.25
    assert restored.phases["implement"].workload == SyntheticWorkload(
        cpu_seconds=3, mem_bytes=2**20, disk_bytes=4096
    )


def test_an_unknown_field_in_the_env_var_is_refused(workflow: WorkflowDefinition) -> None:
    payload = json.loads(_profile(workflow, "node").model_dump_json())
    payload["phases"]["premise"]["side_effect"]["force_push"] = True

    with pytest.raises(ValidationError, match="force_push"):
        ScriptedAgentProfile.from_env({ScriptedAgentProfile.ENV: json.dumps(payload)})


def test_a_missing_env_var_names_itself() -> None:
    with pytest.raises(LookupError, match="SYN_SCRIPTED_AGENT_PROFILE"):
        ScriptedAgentProfile.from_env({})


# --- invariants that keep a run at scale safe -----------------------------


@pytest.mark.parametrize("repo", ["syntropic137/syntropic137", "Syntropic137/SYNTROPIC137"])
def test_the_fixture_is_never_this_repository(workflow: WorkflowDefinition, repo: str) -> None:
    with pytest.raises(ValueError, match="cannot be the load-test fixture"):
        ScriptedAgentProfile.for_workflow(
            workflow,
            tier="platform",
            fixture_repo=repo,
            streams=_streams(workflow),
            workload=NoWorkload(),
        )


def test_a_hand_written_platform_profile_cannot_touch_prs(workflow: WorkflowDefinition) -> None:
    payload = json.loads(_profile(workflow, "node").model_dump_json())
    payload["tier"] = "platform"

    with pytest.raises(
        ValidationError,
        match=r"must not touch pull requests \(phases \['finalize_pr', 'implement'\]\)",
    ):
        ScriptedAgentProfile.model_validate(payload)


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param({"implement": {"kind": "push_branch"}}, id="ready-with-no-draft"),
        pytest.param({"fix": {"kind": "open_draft_pull_request"}}, id="two-drafts"),
        pytest.param({"premise": {"kind": "mark_pull_request_ready"}}, id="ready-before-draft"),
    ],
)
def test_a_hand_written_node_profile_must_open_the_draft_before_marking_it_ready(
    workflow: WorkflowDefinition, edit: dict[str, dict[str, str]]
) -> None:
    payload = json.loads(_profile(workflow, "node").model_dump_json())
    for phase_id, side_effect in edit.items():
        payload["phases"][phase_id]["side_effect"] = side_effect
        payload["phases"][phase_id]["workload"] = {"kind": "none"}

    with pytest.raises(ValidationError, match="exactly one phase opens the draft pull request"):
        ScriptedAgentProfile.model_validate(payload)


def test_a_validated_platform_profile_cannot_gain_a_pr_opening_phase(
    workflow: WorkflowDefinition,
) -> None:
    profile = _profile(workflow, "platform")
    opening = _profile(workflow, "node").phases["finalize_pr"]

    with pytest.raises(TypeError):
        profile.phases["finalize_pr"] = opening  # type: ignore[index]
    with pytest.raises(TypeError):
        del profile.phases["premise"]  # type: ignore[attr-defined]

    sent = json.loads(profile.to_env()[ScriptedAgentProfile.ENV])
    assert sent["phases"]["finalize_pr"]["side_effect"] == {"kind": "verify_remote_branch"}


def test_the_callers_mapping_is_not_the_profiles(workflow: WorkflowDefinition) -> None:
    stream = ScriptedStream(harness="claude", recording="/r.jsonl", cli_version="1")
    report = ScriptedPhase(
        stream=stream, workload=NoWorkload(), side_effect=ReportOnly(), artifact="x"
    )
    phases = {"premise": report}
    profile = ScriptedAgentProfile(tier="platform", fixture_repo=_FIXTURE, phases=phases)

    phases["finalize_pr"] = _profile(workflow, "node").phases["finalize_pr"]
    phases.clear()

    sent = json.loads(profile.to_env()[ScriptedAgentProfile.ENV])
    assert list(sent["phases"]) == ["premise"]


def test_gates_on_a_phase_without_a_tree_is_refused() -> None:
    stream = ScriptedStream(harness="claude", recording="/r.jsonl", cli_version="1")

    with pytest.raises(ValidationError, match="no working tree"):
        ScriptedPhase(
            stream=stream, workload=GatesWorkload(), side_effect=VerifyRemoteBranch(), artifact="x"
        )


def test_an_artifact_naming_a_field_the_stub_cannot_fill_is_refused() -> None:
    stream = ScriptedStream(harness="claude", recording="/r.jsonl", cli_version="1")

    with pytest.raises(ValidationError, match="pr_url"):
        ScriptedPhase(
            stream=stream,
            workload=NoWorkload(),
            side_effect=PushBranch(),
            artifact="Branch {branch}, PR {pr_url}",
        )


# --- artifacts the next phase reads ---------------------------------------


def test_rendered_artifacts_name_the_execution_and_its_branch(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "node")
    rendered = {
        pid: profile.render_artifact(pid, "exec-7f3a", _HEAD, _PR_URL) for pid in profile.phases
    }

    assert all("exec-7f3a" in text and "{" not in text for text in rendered.values())
    for pid in _AFTER_PREMISE:
        assert "`loadtest/exec-7f3a`" in rendered[pid], pid
    assert rendered["reverify"].splitlines()[0] == "CERTIFIED"
    assert rendered["finalize_pr"].splitlines()[:2] == ["READY", "Repair rounds: 1 of 3"]
    assert "## 1. Verdict: Confirmed" in rendered["premise"]


def test_finalize_pr_marks_ready_the_draft_implement_recorded(
    workflow: WorkflowDefinition,
) -> None:
    """implement records the draft's number and URL; finalize_pr names the same one."""
    profile = _profile(workflow, "node")

    implemented = profile.render_artifact("implement", "exec-7f3a", _HEAD, _PR_URL)
    finalized = profile.render_artifact("finalize_pr", "exec-7f3a", _HEAD, _PR_URL)

    assert f"#4217 {_PR_URL}" in implemented
    assert f"PR: #4217 {_PR_URL}" in finalized.splitlines()


@pytest.mark.parametrize(
    "pr_url",
    [
        None,
        "https://github.com/syntropic137/syntropic137/pull/4217",
        f"https://github.com/{_FIXTURE}/pull/0",
        f"https://github.com/{_FIXTURE}/issues/4217",
    ],
)
@pytest.mark.parametrize("phase_id", ["implement", "finalize_pr"])
def test_a_node_artifact_cannot_name_a_pr_off_the_fixture(
    workflow: WorkflowDefinition, phase_id: str, pr_url: str | None
) -> None:
    with pytest.raises(ValueError, match=f"phase {phase_id} artifact names the pull request"):
        _profile(workflow, "node").render_artifact(phase_id, "exec-7f3a", _HEAD, pr_url)


def test_a_platform_artifact_says_no_pr_was_opened(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "platform")

    finalized = profile.render_artifact("finalize_pr", "exec-7f3a", _HEAD)

    assert "PR: none (the platform tier opens no pull request)" in finalized.splitlines()
    with pytest.raises(ValueError, match="platform tier opens no pull request"):
        profile.render_artifact("implement", "exec-7f3a", _HEAD, _PR_URL)


@pytest.mark.parametrize(
    ("n", "fix", "reverify"),
    [(1, "fix", "reverify"), (2, "fix_2", "reverify_2"), (3, "fix_3", "reverify_3")],
)
def test_each_repair_round_reports_which_round_it_is(
    workflow: WorkflowDefinition, n: int, fix: str, reverify: str
) -> None:
    """The fix prompts demand the round first; reverify demands it second (PC-63)."""
    profile = _profile(workflow, "node", review_verdicts=_ALL_BLOCKED)

    fixed = profile.render_artifact(fix, "exec-7f3a", _HEAD).splitlines()
    reviewed = profile.render_artifact(reverify, "exec-7f3a", _HEAD).splitlines()

    assert fixed[0] == f"Round: {n} of 3"
    assert reviewed[:2] == ["BLOCKED", f"Round: {n} of 3"]


# --- the declared verdict is what the engine reads, and the run follows it ---

_ROUNDS = ("fix", "reverify", "fix_2", "reverify_2", "fix_3", "reverify_3")


def _engine_run(
    workflow: WorkflowDefinition, profile: ScriptedAgentProfile
) -> tuple[list[str], ReviewVerdict | None]:
    """Feed each phase's emitted TASK_RESULT to the real reader and ``next_phase``.

    The phase definitions carry the workflow's own ``order``, not the profile's
    mapping position, so this is an independent run of the aggregate's rule.
    """
    definitions = [
        PhaseDefinition(phase_id=p.id, name=p.name, order=p.order) for p in workflow.phases
    ]
    ran: list[str] = []
    ended_on: ReviewVerdict | None = None
    at: PhaseDefinition | None = definitions[0]
    while at is not None:
        ran.append(at.phase_id)
        read = AgentVerdict.from_agent_text(profile.task_result(at.phase_id))
        assert read.status is VerdictStatus.SUCCESS, at.phase_id
        ended_on = read.reported_review_verdict or ended_on
        step = next_phase(definitions, at.order, read.reported_review_verdict)
        at = step.phase if step else None
    return ran, ended_on


@pytest.mark.parametrize(
    ("verdicts", "rounds_run", "ended_on", "outcome"),
    [
        pytest.param(None, 1, ReviewVerdict.CERTIFIED, "READY", id="certified-in-round-1"),
        pytest.param(
            {"reverify": "blocked", "reverify_2": "certified"},
            2,
            ReviewVerdict.CERTIFIED,
            "READY",
            id="blocked-then-certified",
        ),
        pytest.param(_ALL_BLOCKED, 3, ReviewVerdict.BLOCKED, "DRAFT", id="blocked-at-the-bound"),
        pytest.param({}, 3, None, "DRAFT", id="no-verdict-reported"),
    ],
)
def test_the_final_outcome_is_the_run_the_engine_takes_from_the_emitted_verdicts(
    workflow: WorkflowDefinition,
    verdicts: dict[str, str] | None,
    rounds_run: int,
    ended_on: ReviewVerdict | None,
    outcome: str,
) -> None:
    profile = _profile(workflow, "node", review_verdicts=verdicts)

    ran, engine_ended_on = _engine_run(workflow, profile)

    assert ran == [*_PHASES[:3], *_ROUNDS[: 2 * rounds_run], "finalize_pr"]
    assert engine_ended_on is ended_on
    assert profile.planned_run().ran == tuple(ran)
    finalized = profile.render_artifact("finalize_pr", "exec-7f3a", _HEAD, _PR_URL)
    assert finalized.splitlines()[:2] == [outcome, f"Repair rounds: {rounds_run} of 3"]
    readies = isinstance(profile.phases["finalize_pr"].side_effect, MarkPullRequestReady)
    assert readies is (outcome == "READY")
    last_review = _ROUNDS[2 * rounds_run - 1]
    reviewed = profile.render_artifact(last_review, "exec-7f3a", _HEAD).splitlines()
    assert reviewed[0] == (ended_on.value.upper() if ended_on else "NO VERDICT")


@pytest.mark.parametrize(
    ("verdicts", "final_side_effect"),
    [
        pytest.param(None, {"kind": "report_only"}, id="certified-but-left-a-draft"),
        pytest.param(_ALL_BLOCKED, {"kind": "mark_pull_request_ready"}, id="blocked-but-ready"),
        pytest.param({}, {"kind": "mark_pull_request_ready"}, id="unreported-but-ready"),
    ],
)
def test_a_hand_written_profile_cannot_finish_against_its_own_verdicts(
    workflow: WorkflowDefinition, verdicts: dict[str, str] | None, final_side_effect: dict[str, str]
) -> None:
    payload = json.loads(_profile(workflow, "node", review_verdicts=verdicts).model_dump_json())
    payload["phases"]["finalize_pr"]["side_effect"] = final_side_effect

    with pytest.raises(ValidationError, match="marks the draft ready exactly when the run ends"):
        ScriptedAgentProfile.model_validate(payload)


def test_a_verdict_for_a_phase_the_workflow_does_not_have_is_refused(
    workflow: WorkflowDefinition,
) -> None:
    with pytest.raises(ValueError, match=r"has no phases \['reverify_4'\]"):
        _profile(workflow, "node", review_verdicts={"reverify_4": "certified"})


def test_every_pushing_phase_reports_the_file_its_side_effect_commits(
    workflow: WorkflowDefinition,
) -> None:
    """``PushBranch`` commits ``loadtest/<phase_id>.txt``; the report must name that file."""
    profile = _profile(workflow, "node")
    pushing = [
        pid
        for pid, p in profile.phases.items()
        if isinstance(p.side_effect, PushBranch | OpenDraftPullRequest)
    ]

    assert pushing == ["implement", "fix", "fix_2", "fix_3"]
    for pid in pushing:
        rendered = profile.render_artifact(pid, "exec-7f3a", _HEAD, _PR_URL)
        assert f"`loadtest/{pid}.txt`" in rendered, pid


# --- the schema agentic-workspace builds the stub image against -----------


def test_the_committed_schema_matches_the_model() -> None:
    generated = (
        json.dumps(ScriptedAgentProfile.model_json_schema(), indent=2, sort_keys=True) + "\n"
    )

    assert _SCHEMA.read_text(encoding="utf-8") == generated, (
        "scripted_agent_profile.schema.json is stale; regenerate with: uv run python -c "
        "'import json; from syn_perf.loadtest import ScriptedAgentProfile as P; "
        "print(json.dumps(P.model_json_schema(), indent=2, sort_keys=True))' "
        "> packages/syn-perf/src/syn_perf/loadtest/scripted_agent_profile.schema.json"
    )


# --- the head each phase hands to the next --------------------------------

# Each phase hands to the next by order; a certified reverify also hands
# straight to finalize_pr, skipping the rounds after it.
_HANDOFFS = [
    *pairwise(_AFTER_PREMISE),
    ("reverify", "finalize_pr"),
    ("reverify_2", "finalize_pr"),
]


@pytest.mark.parametrize(("writer", "reader"), _HANDOFFS)
def test_the_next_phase_receives_the_full_head_the_previous_one_wrote(
    workflow: WorkflowDefinition, writer: str, reader: str
) -> None:
    profile = _profile(workflow, "node")
    handed = profile.render_artifact(writer, "exec-7f3a", _HEAD, _PR_URL)

    head = head_sha_handed_over(handed, branch_head=_HEAD)

    assert head == _HEAD
    assert f"`{_HEAD}`" in profile.render_artifact(reader, "exec-7f3a", head, _PR_URL)


@pytest.mark.parametrize(("writer", "reader"), _HANDOFFS)
def test_a_branch_pushed_over_after_the_handoff_is_refused(
    workflow: WorkflowDefinition, writer: str, reader: str
) -> None:
    handed = _profile(workflow, "node").render_artifact(writer, "exec-7f3a", _HEAD, _PR_URL)

    with pytest.raises(ValueError, match=f"handed over {_HEAD} but the branch is at"):
        head_sha_handed_over(handed, branch_head=_PUSHED_OVER)


@pytest.mark.parametrize(
    "artifact", ["Branch `loadtest/exec-7f3a`.", HEAD_SHA_LINE.format(head_sha=_HEAD[:12])]
)
def test_an_artifact_without_a_full_head_hands_nothing_over(artifact: str) -> None:
    with pytest.raises(ValueError, match="exactly one full head SHA"):
        head_sha_handed_over(artifact, branch_head=_HEAD)


@pytest.mark.parametrize("head_sha", [None, "", _HEAD[:12], _HEAD.upper(), _HEAD + "0"])
@pytest.mark.parametrize("phase_id", _AFTER_PREMISE)
def test_a_phase_after_premise_cannot_write_its_artifact_without_a_full_head(
    workflow: WorkflowDefinition, phase_id: str, head_sha: str | None
) -> None:
    with pytest.raises(ValueError, match=f"phase {phase_id} artifact names the head"):
        _profile(workflow, "node").render_artifact(phase_id, "exec-7f3a", head_sha, _PR_URL)


# --- every value the model accepts survives the env var -------------------

_MAX_FLOAT = 1.7976931348623157e308
_FINITE = [0.0, 5e-324, 0.25, 1.0, 1e9, _MAX_FLOAT]


def _one_phase_profile(pacing_factor: float, cpu_seconds: float, size: int) -> ScriptedAgentProfile:
    return ScriptedAgentProfile(
        tier="platform",
        fixture_repo=_FIXTURE,
        phases={
            "implement": ScriptedPhase(
                stream=ScriptedStream(
                    harness="claude",
                    recording="/r.jsonl",
                    cli_version="1",
                    pacing_factor=pacing_factor,
                ),
                workload=SyntheticWorkload(
                    cpu_seconds=cpu_seconds, mem_bytes=size, disk_bytes=size
                ),
                side_effect=PushBranch(),
                artifact="x",
            )
        },
    )


@pytest.mark.parametrize("value", _FINITE)
@pytest.mark.parametrize("size", [0, 2**63 - 1, 2**80])
def test_every_accepted_profile_survives_the_env_var(value: float, size: int) -> None:
    profile = _one_phase_profile(pacing_factor=value, cpu_seconds=value, size=size)

    assert ScriptedAgentProfile.from_env(profile.to_env()) == profile


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("field", ["pacing_factor", "cpu_seconds"])
def test_a_value_json_cannot_carry_is_refused_when_the_profile_is_built(
    field: str, value: float
) -> None:
    kwargs = {"pacing_factor": 1.0, "cpu_seconds": 1.0, field: value}

    with pytest.raises(ValidationError, match="finite number"):
        _one_phase_profile(size=0, **kwargs)
