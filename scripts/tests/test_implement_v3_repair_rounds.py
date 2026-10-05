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

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / "workflows" / "sdlc" / "implement-v3" / "workflow.yaml"

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


def _verdict_finalize_reads(prompt: str, reports: dict[str, str]) -> str:
    """The report `finalize_pr` treats as current: the first one it lists that exists."""
    listed = re.findall(r"`artifacts/input/(reverify\w*)/reverify\.md`", prompt)
    assert listed, "finalize_pr no longer names any reverify report"
    return next(reports[phase] for phase in listed if phase in reports)


def _round_report(verdict: str, n: int) -> str:
    return f"{verdict}\nRound: {n} of {_ROUNDS}\n"


class TestABlockedReverifyIsRepaired:
    def test_blocked_then_certified_completes_certified(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, prompts = installed
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
        assert _verdict_finalize_reads(prompts["finalize_pr"], reports).startswith("CERTIFIED")

    def test_newest_round_wins_over_an_older_blocked_one(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        # If finalize_pr listed round 1 first it would abandon a branch round 2
        # certified - the exact hand-rescue PC-63 is about.
        _, prompts = installed
        reports = {
            "reverify": _round_report("BLOCKED", 1),
            "reverify_2": _round_report("CERTIFIED", 2),
        }
        assert _verdict_finalize_reads(prompts["finalize_pr"], reports).startswith("CERTIFIED")


class TestTheRepairIsBounded:
    def test_blocked_every_round_stops_at_the_bound_with_a_blocked_verdict(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, prompts = installed
        reports = {
            phase: _round_report("BLOCKED", n)
            for n, phase in enumerate(["reverify", "reverify_2", "reverify_3"], start=1)
        }
        ran = _run(phases, reports)

        fixes = [p for p in ran if p == "fix" or p.startswith("fix_")]
        assert len(fixes) == _ROUNDS
        assert ran[-2:] == ["reverify_3", "finalize_pr"], "nothing may run after the bound"
        final = _verdict_finalize_reads(prompts["finalize_pr"], reports)
        assert final.startswith("BLOCKED")
        assert f"Round: {_ROUNDS} of {_ROUNDS}" in final

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
        for reverify in ("reverify", "reverify_2", "reverify_3"):
            assert f"artifacts/input/{reverify}/reverify.md" in prompts["finalize_pr"], reverify


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
