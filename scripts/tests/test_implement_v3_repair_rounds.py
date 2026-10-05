"""`sdlc-implement-v3` repairs a BLOCKED reverify, and stops at its bound (PC-63).

On 2026-10-05 four runs (#1589, #1596, #1597, #1603) ended with `reverify`
BLOCKED on findings one more edit would have closed, and each needed a second
fix round built by hand. The engine advances strictly by `order` and reads no
verdict, so the repeat is written into the workflow definition: three
fix/reverify rounds under distinct phase ids, then `finalize_pr`.

Two halves have to agree, and each is tested where it lives:

- The ENGINE half is the aggregate. Driving the real `WorkflowExecutionAggregate`
  with the phase definitions `POST /workflows` would install shows how many
  rounds a run can take and that it ends - nothing in a processor loops.
- The PROMPT half is which report each phase treats as current. The aggregate
  cannot see a verdict; `finalize_pr` decides READY or DRAFT from whichever
  `reverify*` report its prompt tells it to read first. These tests resolve that
  order from the installed prompt text, so a prompt that reads an older round
  before a newer one turns a certified second round into an abandoned run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from syn_domain.contexts.artifacts import UNREPORTED_AGENT, PhaseOutputFile
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ArtifactsCollectedCommand,
    StartExecutionCommand,
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.domain.events.NextPhaseReadyEvent import (
    NextPhaseReadyEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / "workflows" / "sdlc" / "implement-v3" / "workflow.yaml"
_FINALIZE = _WORKFLOW.parent / "phases" / "finalize_pr.md"

# The bound the task set: one round plus at most two extra. Raising it is a
# decision about cost, so it is pinned here rather than inferred from the YAML.
_ROUNDS = 3


@pytest.fixture(scope="module")
def installed() -> tuple[list[PhaseDefinition], dict[str, str]]:
    """The phase order and prompts exactly as `POST /workflows` installs them."""
    command = build_command_from_definition(WorkflowDefinition.from_file(_WORKFLOW))
    assert command.aggregate_id == "sdlc-implement-v3"
    phases = [
        PhaseDefinition(phase_id=p.phase_id, name=p.name, order=p.order)
        for p in sorted(command.phases, key=lambda p: p.order)
    ]
    prompts = {p.phase_id: re.sub(r"\s+", " ", p.prompt_template or "") for p in command.phases}
    return phases, prompts


def _run(phases: list[PhaseDefinition], reports: dict[str, str]) -> list[str]:
    """Drive the aggregate phase by phase; return the phase ids it ran.

    Each phase "produces" `reports[phase_id]` as its artifact preview, which is
    everything the aggregate is shown of a verdict.
    """
    agg = WorkflowExecutionAggregate()
    agg._handle_command(
        StartExecutionCommand(
            execution_id="exec-pc63",
            workflow_id="sdlc-implement-v3",
            workflow_name="SDLC v3",
            total_phases=len(phases),
            inputs={},
            phase_definitions=phases,
        )
    )
    ran = [phases[0].phase_id]
    while True:
        seen = len(agg._uncommitted_events)
        agg._handle_command(
            ArtifactsCollectedCommand(
                execution_id="exec-pc63",
                phase_id=ran[-1],
                artifact_ids=[f"art-{ran[-1]}"],
                first_content_preview=reports.get(ran[-1], "done"),
            )
        )
        nxt = [
            e.event
            for e in agg._uncommitted_events[seen:]
            if isinstance(e.event, NextPhaseReadyEvent)
        ]
        if not nxt:
            return ran
        assert len(ran) <= len(phases), "the run did not terminate"
        ran.append(nxt[0].next_phase_id)


def _reports_finalize_reads(prompt: str) -> list[str]:
    """The input paths `finalize_pr` may take its verdict from, in the order it tries them."""
    section = prompt[prompt.index("The final verification report") : prompt.index("Never take")]
    listed = re.findall(r"`(artifacts/input/reverify\w*(?:/reverify)?\.md)`", section)
    assert listed, "finalize_pr no longer names any reverify report"
    return listed


def _finalize(inputs: dict[str, str]) -> tuple[str, set[str]]:
    """What `finalize_pr` does given the files injected into its workspace.

    Selection, validation and the `gh pr` actions are all read from the
    installed prompt: the first listed report that exists, checked against the
    two lines the prompt requires, then every `gh pr <verb>` in the section for
    that verdict. An unusable report falls to the BLOCKED section, as it says.
    """
    raw = _FINALIZE.read_text()
    prompt = re.sub(r"\s+", " ", raw)
    report = next((inputs[path] for path in _reports_finalize_reads(prompt) if path in inputs), "")
    lines = report.splitlines()
    verdict = (
        lines[0]
        if len(lines) >= 2 and lines[0] in ("CERTIFIED", "BLOCKED") and lines[1] == "Round: 3 of 3"
        else "FINAL_REPORT_UNUSABLE"
    )
    branch = "CERTIFIED" if verdict == "CERTIFIED" else "BLOCKED"
    start = raw.index(f"\n## If {branch}\n")
    end = raw.index("\n## ", start + 1)
    return verdict, set(re.findall(r"`gh pr (\w+)", raw[start:end]))


def _injected(reports: dict[str, str]) -> dict[str, str]:
    """Reports as the collector injects a well-behaved phase's `reverify.md`."""
    return {f"artifacts/input/{phase}/reverify.md": text for phase, text in reports.items()}


def _round_report(verdict: str, n: int) -> str:
    return f"{verdict}\nRound: {n} of {_ROUNDS}\n"


class TestABlockedReverifyIsRepaired:
    def test_blocked_then_certified_completes_certified(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, _ = installed
        reports = {
            "reverify": _round_report("BLOCKED", 1),
            "reverify_2": _round_report("CERTIFIED", 2),
            # Round 3's fix changed nothing and its reverify carried round 2's
            # certification forward, as both prompts instruct.
            "reverify_3": _round_report("CERTIFIED", 3),
        }
        ran = _run(phases, reports)

        assert ran.index("fix_2") == ran.index("reverify") + 1, (
            "a BLOCKED first reverify must be followed by another fix round"
        )
        assert ran[-1] == "finalize_pr"
        verdict, actions = _finalize(_injected(reports))
        assert verdict == "CERTIFIED"
        assert "ready" in actions, "a certified run must mark the PR ready"
        assert not actions & {"close", "merge"}

    def test_only_round_three_is_ever_read(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        # Round 3 always runs before finalize_pr, so an earlier round's report
        # is never the current one - listing it as a fallback is how a stale
        # certification gets acted on.
        _, prompts = installed
        assert _reports_finalize_reads(prompts["finalize_pr"]) == [
            "artifacts/input/reverify_3/reverify.md",
            "artifacts/input/reverify_3.md",
        ]

    async def test_a_recovered_round_three_never_falls_back_to_round_two(self) -> None:
        """Round 2 CERTIFIED, round 3 wrote no file and was salvaged BLOCKED.

        Driven through the real collector and handoff, which file a salvaged
        phase under `recovered-from-transcript.md` and an alias whose first
        line is the recovery notice - so no `reverify_3/reverify.md` exists.
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

        async def _collect(phase: str, ws: _Workspace, said: str | None) -> list[PhaseOutputFile]:
            got = await collector.collect_from_workspace(
                workspace=ws,
                workflow_id="sdlc-implement-v3",
                phase_id=phase,
                execution_id="exec-pc63",
                session_id=f"sess-{phase}",
                phase_name=phase,
                output_artifact_types=("markdown",),
                agent=UNREPORTED_AGENT,
                last_agent_message=said,
            )
            return list(got.files)

        round_2 = _round_report("CERTIFIED", 2)
        files = {
            "reverify_2": await _collect(
                "reverify_2",
                _Workspace([("artifacts/output/reverify.md", round_2.encode())]),
                None,
            ),
            "reverify_3": await _collect(
                "reverify_3",
                _Workspace([]),
                "BLOCKED\nRound: 3 of 3\nRepair bound reached: 3 of 3 rounds used, findings "
                "still open. The fix to the collector reintroduced the dropped alias for "
                "recovered phases, and the regression test asserts nothing about it.",
            ),
        }
        finalize_ws = _Workspace([])
        await collector.inject_from_previous_phases_explicit(
            workspace=finalize_ws,
            completed_phase_ids=list(files),
            phase_outputs={},
            execution_id="exec-pc63",
            phase_files=files,
        )
        injected = finalize_ws.injected
        assert "artifacts/input/reverify_2/reverify.md" in injected
        assert "artifacts/input/reverify_3/reverify.md" not in injected

        verdict, actions = _finalize(injected)
        assert verdict == "FINAL_REPORT_UNUSABLE"
        assert "ready" not in actions, "round 2's certification must not mark the PR ready"
        assert "comment" in actions

    def test_an_unreadable_or_mislabelled_final_report_keeps_the_pr_draft(self) -> None:
        for report in ("", "CERTIFIED\nRound: 2 of 3\n", "Looks good to me\n"):
            verdict, actions = _finalize(_injected({"reverify_3": report}))
            assert verdict == "FINAL_REPORT_UNUSABLE", report
            assert "ready" not in actions, report


class TestTheRepairIsBounded:
    def test_blocked_every_round_stops_at_the_bound_with_a_blocked_verdict(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, _ = installed
        reports = {
            phase: _round_report("BLOCKED", n)
            for n, phase in enumerate(["reverify", "reverify_2", "reverify_3"], start=1)
        }
        ran = _run(phases, reports)

        fixes = [p for p in ran if p == "fix" or p.startswith("fix_")]
        assert len(fixes) == _ROUNDS
        assert ran[-2:] == ["reverify_3", "finalize_pr"], "nothing may run after the bound"
        verdict, actions = _finalize(_injected(reports))
        assert verdict == "BLOCKED"
        assert "comment" in actions, "a blocked run must say why on the PR"
        assert not actions & {"ready", "close", "merge"}, "a blocked PR stays an open draft"

    def test_the_final_round_must_say_the_bound_was_reached(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        _, prompts = installed
        assert "Repair bound reached: 3 of 3 rounds used" in prompts["reverify_3"]
        assert "Repair rounds: N of 3" in prompts["finalize_pr"]


class TestEveryRoundIsVisibleAndWired:
    """The round count is on the execution as distinct phases, and the prompts
    know every one of them. Adding a round to the YAML without teaching the
    prompts about it would leave a phase that reads the wrong verdict."""

    def test_each_round_is_its_own_phase_on_the_execution(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, _ = installed
        ids = [p.phase_id for p in phases]
        assert ids[ids.index("verify") + 1 :] == [
            "fix",
            "reverify",
            "fix_2",
            "reverify_2",
            "fix_3",
            "reverify_3",
            "finalize_pr",
        ]

    def test_each_round_reads_the_round_before_it(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        _, prompts = installed
        acts_on = {
            "fix": "verify/verify.md",
            "fix_2": "reverify/reverify.md",
            "fix_3": "reverify_2/reverify.md",
        }
        for fix, verdict in acts_on.items():
            assert f"artifacts/input/{verdict}" in prompts[fix], fix
            assert f"Round: {fix[-1] if fix != 'fix' else 1} of {_ROUNDS}" in prompts[fix], fix
        for n, (fix, reverify) in enumerate(
            [("fix", "reverify"), ("fix_2", "reverify_2"), ("fix_3", "reverify_3")], start=1
        ):
            assert f"artifacts/input/{fix}/fix.md" in prompts[reverify], reverify
            assert f"Round {n} of {_ROUNDS}" in prompts[reverify], reverify


@pytest.mark.parametrize(
    ("base", "rounds"), [("fix", ("fix_2", "fix_3")), ("reverify", ("reverify_2", "reverify_3"))]
)
def test_round_prompts_differ_only_in_their_round_section(
    base: str, rounds: tuple[str, ...]
) -> None:
    """Each round has its own file because a prompt may only name phases that
    already ran (`check_workflow_definitions`). Everything else is one prompt,
    so an edit to `fix.md` that is not made to `fix_2.md` fails here."""

    def body(phase: str) -> str:
        text = (_WORKFLOW.parent / "phases" / f"{phase}.md").read_text()
        start = text.index("## Which round this is\n")
        end = text.index("\n## ", start + 1)
        return text[:start] + text[end:]

    for phase in rounds:
        assert body(phase) == body(base), f"{phase}.md has drifted from {base}.md"
