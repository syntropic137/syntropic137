"""`sdlc-implement-v3` repairs a BLOCKED reverify, and stops at its bound (PC-63).

On 2026-10-05 four runs (#1589, #1596, #1597, #1603) ended with `reverify`
BLOCKED on findings one more edit would have closed, and each needed a second
fix round built by hand. The engine advances strictly by `order` and reads no
verdict, so the repeat is written into the workflow definition: two
fix/reverify rounds under distinct phase ids, then `finalize_pr` (three until
the owner capped it at two on 2026-10-07). A round
whose predecessor certified never runs: the aggregate skips to `finalize_pr`.

Two halves have to agree, and each is tested where it lives:

- The ENGINE half is the aggregate. Driving the real `WorkflowExecutionAggregate`
  with the phase definitions `POST /workflows` would install shows how many
  rounds a run can take and that it ends - nothing in a processor loops.
- The PROMPT half is which report each phase treats as current. The aggregate
  sees only the verdict an agent reports; `finalize_pr` decides READY or DRAFT
  from the report of the newest round that ran. These tests resolve that
  choice from the installed prompt text, so a prompt that insists on a round
  the aggregate skipped turns an early certification into an abandoned run.
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
    AgentExecutionCompletedCommand,
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
from syn_domain.contexts.orchestration.slices.execute_workflow.phase_verdict import (
    AgentVerdict,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / "workflows" / "sdlc" / "implement-v3" / "workflow.yaml"

#: Every workflow that runs these repair rounds, by id. sdlc-reverify-pr-v1 is
#: implement-v3's verification half on an existing PR (#1634), with copies of
#: the same prompts that test_reverify_pr_workflow.py holds byte-equal, so
#: tests that read prompt FILES read implement-v3's and cover both.
_ROUND_WORKFLOWS = {
    "sdlc-implement-v3": _WORKFLOW,
    "sdlc-reverify-pr-v1": _REPO_ROOT / "workflows" / "sdlc" / "reverify-pr" / "workflow.yaml",
}
_FINALIZE = _WORKFLOW.parent / "phases" / "finalize_pr.md"

# The bound the owner set on 2026-10-07: one round plus at most one extra.
# Raising it is a decision about cost, so it is pinned here rather than
# inferred from the YAML.
_ROUNDS = 2
_FIXES = ["fix", *(f"fix_{n}" for n in range(2, _ROUNDS + 1))]
_REVERIFIES = ["reverify", *(f"reverify_{n}" for n in range(2, _ROUNDS + 1))]
_LAST_FIX, _LAST_REVERIFY = _FIXES[-1], _REVERIFIES[-1]


@pytest.fixture(scope="module", params=list(_ROUND_WORKFLOWS))
def installed(request: pytest.FixtureRequest) -> tuple[list[PhaseDefinition], dict[str, str]]:
    """The phase order and prompts exactly as `POST /workflows` installs them."""
    command = build_command_from_definition(
        WorkflowDefinition.from_file(_ROUND_WORKFLOWS[request.param])
    )
    assert command.aggregate_id == request.param
    phases = [
        PhaseDefinition(phase_id=p.phase_id, name=p.name, order=p.order)
        for p in sorted(command.phases, key=lambda p: p.order)
    ]
    prompts = {p.phase_id: re.sub(r"\s+", " ", p.prompt_template or "") for p in command.phases}
    return phases, prompts


def _run(phases: list[PhaseDefinition], reports: dict[str, str]) -> list[str]:
    """Drive the aggregate phase by phase; return the phase ids it ran."""
    return _drive(phases, reports)[0]


def _drive(
    phases: list[PhaseDefinition], reports: dict[str, str]
) -> tuple[list[str], WorkflowExecutionAggregate]:
    """Drive the aggregate phase by phase; return the phase ids it ran, and it.

    Each phase "produces" `reports[phase_id]` as its artifact preview, and its
    agent reports the report's first line as its `review_verdict` through the
    reader production uses - which is what the aggregate decides on.
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
        said = reports.get(ran[-1], "").split("\n", 1)[0].lower()
        verdict = AgentVerdict.from_agent_text(
            f'TASK_RESULT: {{"success": true, "review_verdict": "{said}"}}\nTASK_RESULT_END'
            if said
            else 'TASK_RESULT: {"success": true}\nTASK_RESULT_END'
        )
        agg._handle_command(
            AgentExecutionCompletedCommand(
                execution_id="exec-pc63",
                phase_id=ran[-1],
                session_id=f"sess-{ran[-1]}",
                reported_review_verdict=verdict.reported_review_verdict,
            )
        )
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
            return ran, agg
        assert len(ran) <= len(phases), "the run did not terminate"
        ran.append(nxt[0].next_phase_id)


def _reports_finalize_reads(prompt: str) -> list[str]:
    """The input paths `finalize_pr` may take its verdict from, in the order it tries them."""
    section = prompt[prompt.index("The final verification report") : prompt.index("Never take")]
    listed = re.findall(r"`(artifacts/input/reverify\w*(?:/reverify)?\.md)`", section)
    assert listed, "finalize_pr no longer names any reverify report"
    return listed


def _round_of(path: str) -> str:
    """The round a listed report belongs to: `reverify`, `reverify_2`, ..."""
    found = re.match(r"artifacts/input/(reverify(?:_\d)?)[/.]", path)
    assert found, path
    return found.group(1)


def _finalize(inputs: dict[str, str]) -> tuple[str, set[str]]:
    """What `finalize_pr` does given the files injected into its workspace.

    Selection, validation and the `gh pr` actions are all read from the
    installed prompt: the first listed round that RAN - anything of it was
    injected - then that round's first listed report that exists, checked
    against the two lines the prompt requires, then every `gh pr <verb>` in the
    section for that verdict. An unusable report falls to the BLOCKED section,
    as it says.
    """
    raw = _FINALIZE.read_text()
    prompt = re.sub(r"\s+", " ", raw)
    listed = _reports_finalize_reads(prompt)
    ran = [
        r
        for r in dict.fromkeys(map(_round_of, listed))
        if any(
            p.startswith(f"artifacts/input/{r}/") or p == f"artifacts/input/{r}.md" for p in inputs
        )
    ]
    newest = ran[0] if ran else None
    report = next((inputs[p] for p in listed if _round_of(p) == newest and p in inputs), "")
    rule = re.search(
        r"first line is exactly `(\w+)` or `(\w+)` and its second line is exactly `([^`]+)`",
        prompt,
    )
    assert rule, "finalize_pr no longer says what makes the final report usable"
    *verdicts, round_line = rule.groups()
    assert round_line == f"Round: N of {_ROUNDS}"
    n = 1 if newest == "reverify" else int((newest or "_0")[-1])
    lines = report.splitlines()
    usable = (
        len(lines) >= 2 and lines[0] in verdicts and lines[1] == round_line.replace("N", str(n))
    )
    verdict = lines[0] if usable else "FINAL_REPORT_UNUSABLE"
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
    @pytest.mark.parametrize("certified_in", range(1, _ROUNDS + 1))
    def test_a_certification_in_any_round_marks_the_pr_ready(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]], certified_in: int
    ) -> None:
        phases, _ = installed
        rounds = _REVERIFIES
        reports = {
            phase: _round_report("CERTIFIED" if n == certified_in else "BLOCKED", n)
            for n, phase in enumerate(rounds[:certified_in], start=1)
        }
        ran = _run(phases, reports)

        assert [p for p in ran if p in rounds] == rounds[:certified_in], (
            "a BLOCKED reverify is followed by another round; a CERTIFIED one by none"
        )
        assert ran[-1] == "finalize_pr"
        verdict, actions = _finalize(_injected({p: reports[p] for p in ran if p in reports}))
        assert verdict == "CERTIFIED"
        assert "ready" in actions, "a certified run must mark the PR ready"
        assert not actions & {"close", "merge"}

    def test_rounds_are_read_newest_first(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        # An older round's report is only the current one when no newer round
        # ran; listing it first is how a stale certification gets acted on.
        _, prompts = installed
        assert _reports_finalize_reads(prompts["finalize_pr"]) == [
            "artifacts/input/reverify_2/reverify.md",
            "artifacts/input/reverify_2.md",
            "artifacts/input/reverify/reverify.md",
            "artifacts/input/reverify.md",
        ]

    def test_a_newer_round_that_ran_without_a_report_never_falls_back(self) -> None:
        verdict, actions = _finalize(
            {
                "artifacts/input/reverify/reverify.md": _round_report("CERTIFIED", 1),
                "artifacts/input/reverify_2/fix-notes.md": "round 2 ran and wrote no report",
            }
        )
        assert verdict == "FINAL_REPORT_UNUSABLE"
        assert "ready" not in actions

    async def test_a_recovered_round_two_never_falls_back_to_round_one(self) -> None:
        """Round 1 CERTIFIED, round 2 wrote no file and was salvaged BLOCKED.

        Driven through the real collector and handoff, which file a salvaged
        phase under `recovered-from-transcript.md` and an alias whose first
        line is the recovery notice - so no `reverify_2/reverify.md` exists.
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

        round_1 = _round_report("CERTIFIED", 1)
        files = {
            "reverify": await _collect(
                "reverify",
                _Workspace([("artifacts/output/reverify.md", round_1.encode())]),
                None,
            ),
            "reverify_2": await _collect(
                "reverify_2",
                _Workspace([]),
                "BLOCKED\nRound: 2 of 2\nRepair bound reached: 2 of 2 rounds used, findings "
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
        assert "artifacts/input/reverify/reverify.md" in injected
        assert "artifacts/input/reverify_2/reverify.md" not in injected

        verdict, actions = _finalize(injected)
        assert verdict == "FINAL_REPORT_UNUSABLE"
        assert "ready" not in actions, "round 1's certification must not mark the PR ready"
        assert "comment" in actions

    def test_an_unreadable_or_mislabelled_final_report_keeps_the_pr_draft(self) -> None:
        # "Round: 2 of 3" is the line a report written under the old bound
        # carries; it is not this run's round line, so it is unusable.
        for report in ("", "CERTIFIED\nRound: 1 of 2\n", "CERTIFIED\nRound: 2 of 3\n", "Looks good\n"):
            verdict, actions = _finalize(_injected({_LAST_REVERIFY: report}))
            assert verdict == "FINAL_REPORT_UNUSABLE", report
            assert "ready" not in actions, report


class TestTheRepairIsBounded:
    def test_blocked_every_round_stops_at_the_bound_with_a_blocked_verdict(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, _ = installed
        reports = {
            phase: _round_report("BLOCKED", n)
            for n, phase in enumerate(_REVERIFIES, start=1)
        }
        ran = _run(phases, reports)

        fixes = [p for p in ran if p == "fix" or p.startswith("fix_")]
        assert len(fixes) == _ROUNDS
        assert ran[-2:] == [_LAST_REVERIFY, "finalize_pr"], "nothing may run after the bound"
        verdict, actions = _finalize(_injected(reports))
        assert verdict == "BLOCKED"
        assert "comment" in actions, "a blocked run must say why on the PR"
        assert not actions & {"ready", "close", "merge"}, "a blocked PR stays an open draft"

    def test_a_run_blocked_at_the_bound_resumes_at_the_last_fix_round(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        # The repair point is the phase before the review that blocked last,
        # read from the run's own definitions: fix_2 now, where a run started
        # under the three-round definition still resumes at fix_3.
        phases, _ = installed
        reports = {
            phase: _round_report("BLOCKED", n) for n, phase in enumerate(_REVERIFIES, start=1)
        }
        _, agg = _drive(phases, reports)

        assert agg._reviews.repair_point(phases) == _LAST_FIX == "fix_2"

    def test_the_final_round_must_say_the_bound_was_reached(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        _, prompts = installed
        assert "Repair bound reached: 2 of 2 rounds used" in prompts[_LAST_REVERIFY]
        assert "Repair rounds: N of 2" in prompts["finalize_pr"]

    def test_no_third_round_is_defined(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        phases, _ = installed
        ids = {p.phase_id for p in phases}
        assert not ids & {"fix_3", "reverify_3"}, "the owner capped repair at two rounds"
        assert not any("of 3" in prompt for prompt in installed[1].values()), (
            "a prompt still counts rounds out of three"
        )


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
            "finalize_pr",
        ]

    def test_each_round_reads_the_round_before_it(
        self, installed: tuple[list[PhaseDefinition], dict[str, str]]
    ) -> None:
        _, prompts = installed
        acts_on = {
            "fix": "verify/verify.md",
            "fix_2": "reverify/reverify.md",
        }
        for fix, verdict in acts_on.items():
            assert f"artifacts/input/{verdict}" in prompts[fix], fix
            assert f"Round: {fix[-1] if fix != 'fix' else 1} of {_ROUNDS}" in prompts[fix], fix
        for n, (fix, reverify) in enumerate(
            zip(_FIXES, _REVERIFIES, strict=True), start=1
        ):
            assert f"artifacts/input/{fix}/fix.md" in prompts[reverify], reverify
            assert f"Round {n} of {_ROUNDS}" in prompts[reverify], reverify


def _section(raw: str, heading: str) -> str:
    start = raw.index(f"\n## {heading}\n")
    return raw[start : raw.index("\n## ", start + 1)]


def _fix_checkout(
    phase: str, *, reported: str, remote: str, resume_comment: str | None = None
) -> str | None:
    """What a fix phase checks out, or None where its prompt says to stop.

    `reported` is the SHA the round's verdict report names, `remote` the
    branch's head, and `resume_comment` the head SHA in `finalize_pr`'s BLOCKED
    comment when the run is a resume. Which SHA counts as verified is read from
    the prompt; the checkout block is then run against a fake git and judged by
    the gate the prompt states.
    """
    raw = (_WORKFLOW.parent / "phases" / f"{phase}.md").read_text()
    flat = lambda s: re.sub(r"\s+", " ", s)  # noqa: E731
    rounds = flat(_section(raw, "Which round this is"))
    checkout = _section(raw, "Check out exactly what verification reviewed")
    verified = reported
    if (
        resume_comment is not None
        and "on a resume the verified SHA is the head SHA that comment names" in rounds
        and "when the round section above names a different SHA as the verified one"
        in flat(checkout)
    ):
        verified = resume_comment
    block = re.search(r"```\n(.*?)```", checkout, re.S)
    assert block, f"{phase} no longer gives the checkout commands"
    head, parsed = "", []
    for line in block.group(1).splitlines():
        cmd = line.replace("<branch>", "b").replace("<verified-sha>", verified)
        if cmd == "git rev-parse origin/b":
            parsed.append(remote)
        elif cmd.startswith("git checkout -B b "):
            head = cmd.rsplit(" ", 1)[1]
        elif cmd == "git rev-parse HEAD":
            parsed.append(head)
    assert "Both `rev-parse` results must equal the verified SHA" in flat(checkout)
    assert len(parsed) == 2, f"{phase} no longer runs both rev-parse checks"
    return head if all(sha == verified for sha in parsed) else None


class TestAResumedFixBuildsOnThePushedHead:
    """A resume re-runs `fix_2` after round 2 pushed head B and was BLOCKED.

    `reverify.md` is still injected and names A, the head before round 2's
    push. Taking A as verified makes the remote check fail on B and the resumed
    round stops before repairing anything; checking out A would drop round 2's
    commits.
    """

    A, B = "a" * 40, "b" * 40

    def test_the_resumed_round_checks_out_the_head_the_blocked_comment_names(self) -> None:
        got = _fix_checkout(_LAST_FIX, reported=self.A, remote=self.B, resume_comment=self.B)
        assert got == self.B

    def test_without_a_resume_a_moved_branch_still_stops_the_round(self) -> None:
        assert _fix_checkout(_LAST_FIX, reported=self.A, remote=self.B) is None
        assert _fix_checkout(_LAST_FIX, reported=self.A, remote=self.A) == self.A

    def test_the_resume_signal_is_what_finalize_pr_writes(self) -> None:
        # The last fix round recognises a resume by the BLOCKED comment; if finalize_pr
        # stopped writing its round count or head SHA, nothing would match.
        rounds = re.sub(
            r"\s+",
            " ",
            _section(
                (_WORKFLOW.parent / "phases" / f"{_LAST_FIX}.md").read_text(), "Which round this is"
            ),
        )
        blocked = re.sub(r"\s+", " ", _section(_FINALIZE.read_text(), "If BLOCKED"))
        assert "saying `2 of 2` repair rounds ran" in rounds
        assert "`2 of 2`" in blocked
        assert "gives the head SHA it applies to" in blocked


@pytest.mark.parametrize(
    ("base", "rounds"), [("fix", tuple(_FIXES[1:])), ("reverify", tuple(_REVERIFIES[1:]))]
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
