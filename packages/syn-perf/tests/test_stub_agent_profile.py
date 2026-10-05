"""The load-test contract (plan 6.1, #1310) against the workflow it stands in for."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_perf.loadtest import (
    HEAD_SHA_LINE,
    GatesWorkload,
    NoWorkload,
    OpenPullRequest,
    PushBranch,
    ReportOnly,
    StubAgentProfile,
    StubPhase,
    StubStream,
    SyntheticWorkload,
    VerifyRemoteBranch,
    head_sha_handed_over,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_WORKFLOW = _REPO / "workflows/sdlc/implement-v3/workflow.yaml"
_AFTER_PREMISE = [
    "implement",
    "verify",
    "fix",
    "reverify",
    "fix_2",
    "reverify_2",
    "fix_3",
    "reverify_3",
    "finalize_pr",
]
"""Every phase that names the head it hands over, in workflow order."""
_SCHEMA = _REPO / "packages/syn-perf/src/syn_perf/loadtest/stub_agent_profile.schema.json"
_FIXTURE = "syntropic137/loadtest-fixture"
_HEAD = "3b7f2bd49a4609f24a516bb4617aadbc1edf751e"
_PUSHED_OVER = "0f0e0d0c0b0a09080706050403020100ffeeddcc"


@pytest.fixture(scope="module")
def workflow() -> WorkflowDefinition:
    return WorkflowDefinition.from_file(_WORKFLOW)


def _streams(workflow: WorkflowDefinition) -> dict[str, StubStream]:
    """One recording per phase, matching the harness the phase really runs."""
    return {
        p.id: StubStream(
            harness=(p.agent.provider if p.agent else None) or "claude",
            recording=f"/recordings/{p.id}.jsonl",
            cli_version="9.9.9",
            pacing_factor=0.25,
        )
        for p in workflow.phases
    }


def _profile(workflow: WorkflowDefinition, tier: str, workload: object = None) -> StubAgentProfile:
    return StubAgentProfile.for_workflow(
        workflow,
        tier=tier,  # type: ignore[arg-type]
        fixture_repo=_FIXTURE,
        streams=_streams(workflow),
        workload=workload or SyntheticWorkload(cpu_seconds=3, mem_bytes=2**20, disk_bytes=4096),  # type: ignore[arg-type]
    )


# --- side effects come from the real phase contract -----------------------


def test_side_effects_follow_the_implement_v3_phase_contracts(
    workflow: WorkflowDefinition,
) -> None:
    kinds = {pid: type(p.side_effect) for pid, p in _profile(workflow, "node").phases.items()}

    assert kinds == {
        "premise": ReportOnly,
        "implement": PushBranch,
        "verify": ReportOnly,
        "fix": PushBranch,
        "reverify": ReportOnly,
        "fix_2": PushBranch,
        "reverify_2": ReportOnly,
        "fix_3": PushBranch,
        "reverify_3": ReportOnly,
        "finalize_pr": OpenPullRequest,
    }


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


def test_platform_tier_checks_the_branch_instead_of_opening_a_pr(
    workflow: WorkflowDefinition,
) -> None:
    profile = _profile(workflow, "platform")

    assert isinstance(profile.phases["finalize_pr"].side_effect, VerifyRemoteBranch)
    assert not any(isinstance(p.side_effect, OpenPullRequest) for p in profile.phases.values())


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
        StubAgentProfile.for_workflow(
            workflow, tier="node", fixture_repo=_FIXTURE, streams=streams, workload=NoWorkload()
        )


def test_a_phase_without_a_stream_is_an_error_not_a_default(workflow: WorkflowDefinition) -> None:
    streams = _streams(workflow)
    del streams["fix"]

    with pytest.raises(ValueError, match="'fix'"):
        StubAgentProfile.for_workflow(
            workflow, tier="node", fixture_repo=_FIXTURE, streams=streams, workload=NoWorkload()
        )


# --- what crosses into the workspace --------------------------------------


def test_the_profile_survives_the_env_var_unchanged(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "node")

    env = profile.to_env()
    restored = StubAgentProfile.from_env(env)

    assert list(env) == ["SYN_STUB_AGENT_PROFILE"]
    assert restored == profile
    assert restored.phases["verify"].stream.pacing_factor == 0.25
    assert restored.phases["implement"].workload == SyntheticWorkload(
        cpu_seconds=3, mem_bytes=2**20, disk_bytes=4096
    )


def test_an_unknown_field_in_the_env_var_is_refused(workflow: WorkflowDefinition) -> None:
    payload = json.loads(_profile(workflow, "node").model_dump_json())
    payload["phases"]["premise"]["side_effect"]["force_push"] = True

    with pytest.raises(ValidationError, match="force_push"):
        StubAgentProfile.from_env({StubAgentProfile.ENV: json.dumps(payload)})


def test_a_missing_env_var_names_itself() -> None:
    with pytest.raises(LookupError, match="SYN_STUB_AGENT_PROFILE"):
        StubAgentProfile.from_env({})


# --- invariants that keep a run at scale safe -----------------------------


@pytest.mark.parametrize("repo", ["syntropic137/syntropic137", "Syntropic137/SYNTROPIC137"])
def test_the_fixture_is_never_this_repository(workflow: WorkflowDefinition, repo: str) -> None:
    with pytest.raises(ValueError, match="cannot be the load-test fixture"):
        StubAgentProfile.for_workflow(
            workflow,
            tier="platform",
            fixture_repo=repo,
            streams=_streams(workflow),
            workload=NoWorkload(),
        )


def test_a_hand_written_platform_profile_cannot_open_prs(workflow: WorkflowDefinition) -> None:
    payload = json.loads(_profile(workflow, "node").model_dump_json())
    payload["tier"] = "platform"

    with pytest.raises(
        ValidationError, match=r"must not open pull requests \(phases \['finalize_pr'\]\)"
    ):
        StubAgentProfile.model_validate(payload)


def test_gates_on_a_phase_without_a_tree_is_refused() -> None:
    stream = StubStream(harness="claude", recording="/r.jsonl", cli_version="1")

    with pytest.raises(ValidationError, match="no working tree"):
        StubPhase(
            stream=stream, workload=GatesWorkload(), side_effect=VerifyRemoteBranch(), artifact="x"
        )


def test_an_artifact_naming_a_field_the_stub_cannot_fill_is_refused() -> None:
    stream = StubStream(harness="claude", recording="/r.jsonl", cli_version="1")

    with pytest.raises(ValidationError, match="pr_url"):
        StubPhase(
            stream=stream,
            workload=NoWorkload(),
            side_effect=PushBranch(),
            artifact="Branch {branch}, PR {pr_url}",
        )


# --- artifacts the next phase reads ---------------------------------------


def test_rendered_artifacts_name_the_execution_and_its_branch(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "node")
    rendered = {pid: profile.render_artifact(pid, "exec-7f3a", _HEAD) for pid in profile.phases}

    assert all("exec-7f3a" in text and "{" not in text for text in rendered.values())
    for pid in _AFTER_PREMISE:
        assert "`loadtest/exec-7f3a`" in rendered[pid], pid
    assert rendered["reverify"].splitlines()[0] == "CERTIFIED"
    assert rendered["finalize_pr"].splitlines()[0] == "READY"
    assert "## 1. Verdict: Confirmed" in rendered["premise"]


@pytest.mark.parametrize(
    ("n", "fix", "reverify"),
    [(1, "fix", "reverify"), (2, "fix_2", "reverify_2"), (3, "fix_3", "reverify_3")],
)
def test_each_repair_round_reports_which_round_it_is(
    workflow: WorkflowDefinition, n: int, fix: str, reverify: str
) -> None:
    """The fix prompts demand the round first; reverify demands it second (PC-63)."""
    profile = _profile(workflow, "node")

    fixed = profile.render_artifact(fix, "exec-7f3a", _HEAD).splitlines()
    certified = profile.render_artifact(reverify, "exec-7f3a", _HEAD).splitlines()

    assert fixed[0] == f"Round: {n} of 3"
    assert certified[:2] == ["CERTIFIED", f"Round: {n} of 3"]


def test_every_pushing_phase_reports_the_file_its_side_effect_commits(
    workflow: WorkflowDefinition,
) -> None:
    """``PushBranch`` commits ``loadtest/<phase_id>.txt``; the report must name that file."""
    profile = _profile(workflow, "node")
    pushing = [pid for pid, p in profile.phases.items() if isinstance(p.side_effect, PushBranch)]

    assert pushing == ["implement", "fix", "fix_2", "fix_3"]
    for pid in pushing:
        assert f"`loadtest/{pid}.txt`" in profile.render_artifact(pid, "exec-7f3a", _HEAD), pid


# --- the schema agentic-workspace builds the stub image against -----------


def test_the_committed_schema_matches_the_model() -> None:
    generated = json.dumps(StubAgentProfile.model_json_schema(), indent=2, sort_keys=True) + "\n"

    assert _SCHEMA.read_text(encoding="utf-8") == generated, (
        "stub_agent_profile.schema.json is stale; regenerate with: uv run python -c "
        "'import json; from syn_perf.loadtest import StubAgentProfile as P; "
        "print(json.dumps(P.model_json_schema(), indent=2, sort_keys=True))' "
        "> packages/syn-perf/src/syn_perf/loadtest/stub_agent_profile.schema.json"
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
    handed = profile.render_artifact(writer, "exec-7f3a", _HEAD)

    head = head_sha_handed_over(handed, branch_head=_HEAD)

    assert head == _HEAD
    assert f"`{_HEAD}`" in profile.render_artifact(reader, "exec-7f3a", head)


@pytest.mark.parametrize(("writer", "reader"), _HANDOFFS)
def test_a_branch_pushed_over_after_the_handoff_is_refused(
    workflow: WorkflowDefinition, writer: str, reader: str
) -> None:
    handed = _profile(workflow, "node").render_artifact(writer, "exec-7f3a", _HEAD)

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
        _profile(workflow, "node").render_artifact(phase_id, "exec-7f3a", head_sha)


# --- every value the model accepts survives the env var -------------------

_MAX_FLOAT = 1.7976931348623157e308
_FINITE = [0.0, 5e-324, 0.25, 1.0, 1e9, _MAX_FLOAT]


def _one_phase_profile(pacing_factor: float, cpu_seconds: float, size: int) -> StubAgentProfile:
    return StubAgentProfile(
        tier="platform",
        fixture_repo=_FIXTURE,
        phases={
            "implement": StubPhase(
                stream=StubStream(
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

    assert StubAgentProfile.from_env(profile.to_env()) == profile


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("field", ["pacing_factor", "cpu_seconds"])
def test_a_value_json_cannot_carry_is_refused_when_the_profile_is_built(
    field: str, value: float
) -> None:
    kwargs = {"pacing_factor": 1.0, "cpu_seconds": 1.0, field: value}

    with pytest.raises(ValidationError, match="finite number"):
        _one_phase_profile(size=0, **kwargs)
