"""The load-test contract (plan 6.1, #1310) against the workflow it stands in for."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration import WorkflowDefinition
from syn_perf.loadtest import (
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
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_WORKFLOW = _REPO / "workflows/sdlc/implement-v3/workflow.yaml"
_SCHEMA = _REPO / "packages/syn-perf/src/syn_perf/loadtest/stub_agent_profile.schema.json"
_FIXTURE = "syntropic137/loadtest-fixture"


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

    with pytest.raises(ValidationError, match="head_sha"):
        StubPhase(
            stream=stream,
            workload=NoWorkload(),
            side_effect=PushBranch(),
            artifact="Branch {branch} at {head_sha}",
        )


# --- artifacts the next phase reads ---------------------------------------


def test_rendered_artifacts_name_the_execution_and_its_branch(workflow: WorkflowDefinition) -> None:
    profile = _profile(workflow, "node")
    rendered = {pid: profile.render_artifact(pid, "exec-7f3a") for pid in profile.phases}

    assert all("exec-7f3a" in text and "{" not in text for text in rendered.values())
    for pid in ("implement", "fix", "verify", "reverify", "finalize_pr"):
        assert "`loadtest/exec-7f3a`" in rendered[pid], pid
    assert rendered["reverify"].splitlines()[0] == "CERTIFIED"
    assert rendered["finalize_pr"].splitlines()[0] == "READY"
    assert "## 1. Verdict: Confirmed" in rendered["premise"]


# --- the schema agentic-workspace builds the stub image against -----------


def test_the_committed_schema_matches_the_model() -> None:
    generated = json.dumps(StubAgentProfile.model_json_schema(), indent=2, sort_keys=True) + "\n"

    assert _SCHEMA.read_text(encoding="utf-8") == generated, (
        "stub_agent_profile.schema.json is stale; regenerate with: uv run python -c "
        "'import json; from syn_perf.loadtest import StubAgentProfile as P; "
        "print(json.dumps(P.model_json_schema(), indent=2, sort_keys=True))' "
        "> packages/syn-perf/src/syn_perf/loadtest/stub_agent_profile.schema.json"
    )
