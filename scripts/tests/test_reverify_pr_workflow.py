"""`sdlc-reverify-pr-v1` is implement-v3's verification half, on an existing PR (#1634).

Three implement-v3 runs finished implement and died in verify on a codex quota
error; nothing could then say "verify this PR head". This workflow replaces
`premise` and `implement` with one `prepare` phase and runs implement-v3's own
verify, repair rounds and finalize_pr after it.

A prompt_file cannot leave its workflow directory, so its prompts are copies.
What keeps them from drifting is here: every installed phase after `prepare` is
implement-v3's phase of the same id, prompt and all, except for `order`, the
verifier model (configurable, README "Switching the verifier model"), and the
one line of verify.md that names which report it reads. The repair-round
behaviour itself runs against this workflow in test_implement_v3_repair_rounds.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_domain.contexts.artifacts import UNREPORTED_AGENT
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"
_REVERIFY = _SDLC / "reverify-pr" / "workflow.yaml"
_IMPLEMENT = _SDLC / "implement-v3" / "workflow.yaml"

#: The phases that certify or block, and so carry the verifier model.
_VERIFIERS = ("verify", "reverify", "reverify_2")

#: The only text verify.md may differ by: which earlier phase's report it reads.
_READS_IMPLEMENT = "`artifacts/input/implement.md`"
_READS_PREPARE = "`artifacts/input/prepare.md`"


def _installed(path: Path) -> dict[str, dict[str, object]]:
    """Each phase as `POST /workflows` would store it, keyed by phase id."""
    command = build_command_from_definition(WorkflowDefinition.from_file(path))
    return {p.phase_id: p.model_dump() for p in command.phases}


@pytest.fixture(scope="module")
def reverify() -> dict[str, dict[str, object]]:
    return _installed(_REVERIFY)


@pytest.fixture(scope="module")
def implement() -> dict[str, dict[str, object]]:
    return _installed(_IMPLEMENT)


def test_prepare_replaces_premise_and_implement(reverify: dict[str, dict[str, object]]) -> None:
    by_order = sorted(reverify, key=lambda pid: int(str(reverify[pid]["order"])))
    assert by_order == [
        "prepare", "verify",
        "fix", "reverify", "fix_2", "reverify_2",
        "finalize_pr",
    ]  # fmt: skip


def test_every_shared_phase_is_implement_v3s_phase(
    reverify: dict[str, dict[str, object]], implement: dict[str, dict[str, object]]
) -> None:
    for phase_id in reverify.keys() - {"prepare"}:
        ours, theirs = dict(reverify[phase_id]), dict(implement[phase_id])
        for field in ("order", "phase_id"):
            ours.pop(field), theirs.pop(field)
        if phase_id in _VERIFIERS:
            for field in ("provider", "model", "allowed_tools"):
                ours.pop(field, None), theirs.pop(field, None)
        if phase_id == "verify":
            theirs["prompt_template"] = str(theirs["prompt_template"]).replace(
                _READS_IMPLEMENT, _READS_PREPARE
            )
        assert ours == theirs, (
            f"{phase_id} drifted from implement-v3's: copy "
            f"workflows/sdlc/implement-v3/phases/{phase_id}.md over "
            f"workflows/sdlc/reverify-pr/phases/{phase_id}.md and match the YAML"
        )


def test_verify_reads_prepare_and_nothing_of_implement_v3s_first_half(
    reverify: dict[str, dict[str, object]],
) -> None:
    prompt = str(reverify["verify"]["prompt_template"])
    assert _READS_PREPARE in prompt
    for phase in reverify.values():
        text = str(phase["prompt_template"])
        assert "artifacts/input/implement" not in text, phase["phase_id"]
        assert "artifacts/input/premise" not in text, phase["phase_id"]


def test_every_verifier_runs_on_the_same_model(reverify: dict[str, dict[str, object]]) -> None:
    # Switching the verifier is one edit made three times; a switch that missed
    # a round would certify round 1 on one model and round 2 on another.
    agents = {(reverify[p]["provider"], reverify[p]["model"]) for p in _VERIFIERS}
    assert len(agents) == 1, agents


async def test_prepares_report_is_injected_where_verify_reads_it(
    reverify: dict[str, dict[str, object]],
) -> None:
    """Through the real collector: prepare writes `prepare.md`, verify finds it.

    The injected path is keyed by the PRODUCING phase's id, not by anything the
    reader declares, so this is the hop a rename of `prepare` would break.
    """

    class _Workspace:
        def __init__(self, to_collect: list[tuple[str, bytes]]) -> None:
            self._to_collect = to_collect
            self.injected: dict[str, str] = {}

        async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
            self.injected.update((path, body.decode()) for path, body in files)

        async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
            return list(self._to_collect)

    collector = ArtifactCollector(repository=None, content_storage=None, query_service=None)  # type: ignore[arg-type]

    async def _discard(**_: object) -> None:
        return None

    collector.create_artifact = _discard  # type: ignore[method-assign,assignment]

    report = "## PR\n#1649\n## Branch\nfeat/x\n## Commit\n" + "a" * 40 + "\n"
    collected = await collector.collect_from_workspace(
        workspace=_Workspace([("artifacts/output/prepare.md", report.encode())]),
        workflow_id="sdlc-reverify-pr-v1",
        phase_id="prepare",
        execution_id="exec-1634",
        session_id="sess-prepare",
        phase_name="prepare",
        output_artifact_types=("markdown",),
        agent=UNREPORTED_AGENT,
        last_agent_message=None,
    )
    verify_ws = _Workspace([])
    await collector.inject_from_previous_phases_explicit(
        workspace=verify_ws,
        completed_phase_ids=["prepare"],
        phase_outputs={},
        execution_id="exec-1634",
        phase_files={"prepare": list(collected.files)},
    )

    named = _READS_PREPARE.strip("`")
    assert named in str(reverify["verify"]["prompt_template"])
    assert verify_ws.injected.get(named) == report
    assert verify_ws.injected.get("artifacts/input/prepare/prepare.md") == report
