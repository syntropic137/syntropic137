"""The workflow gate must reject exactly what the API rejects.

A codex review found the gate stopped at `WorkflowDefinition.model_validate()`
while the create endpoint goes further and converts the definition to a
command. A workflow with an unresolved `prompt_file` therefore PASSED the gate
and got HTTP 400 from the API - the precise class of failure the gate exists to
prevent (#942).

The review also noted the PR added zero test files, so nothing here was
covered at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pytest
import yaml
from pydantic import ValidationError
from scripts.check_workflow_definitions import _ROOT as _REPO_ROOT
from scripts.check_workflow_definitions import (
    _workflow_files,
    grant_violations,
    stale_phase_references,
    validate_file,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
    )

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, body: dict[str, object], name: str = "wf.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(body))
    return path


def _gate_accepts(path: Path) -> bool:
    """Calls the GATE, not a copy of it.

    An earlier version of this helper reimplemented the gate's logic, so
    reverting the script to a shallow `model_validate` left every test green.
    A suite that measures its own copy of the code measures nothing.
    """
    return validate_file(path) is None


class TestTheGateAgreesWithTheApi:
    def test_an_unresolved_prompt_file_is_rejected(self, tmp_path: Path) -> None:
        """The concrete blocker from the review. Before the fix this passed the
        gate and returned HTTP 400 from the create endpoint."""
        path = _write(
            tmp_path,
            {
                "id": "slips-through",
                "name": "Slips through",
                "requires_repos": False,
                "phases": [{"id": "one", "name": "One", "order": 1, "prompt_file": "missing.md"}],
            },
        )
        assert not _gate_accepts(path), (
            "the gate accepted a definition whose prompt_file does not resolve; "
            "the API rejects it with 400, so the gate is not doing its job"
        )

    def test_a_resolvable_prompt_file_is_accepted(self, tmp_path: Path) -> None:
        """The negative control: the fix must not simply reject everything with
        a prompt_file, which would make the gate useless and get it disabled."""
        (tmp_path / "present.md").write_text("do the thing")
        path = _write(
            tmp_path,
            {
                "id": "resolves",
                "name": "Resolves",
                "requires_repos": False,
                "phases": [{"id": "one", "name": "One", "order": 1, "prompt_file": "present.md"}],
            },
        )
        assert _gate_accepts(path), "a valid workflow was rejected; this gate gets disabled next"

    def test_an_inline_prompt_template_is_accepted(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            {
                "id": "inline",
                "name": "Inline",
                "requires_repos": False,
                "phases": [{"id": "one", "name": "One", "order": 1, "prompt_template": "do it"}],
            },
        )
        assert _gate_accepts(path)

    @pytest.mark.parametrize("typo", ["prompt", "tools"])
    def test_a_field_typo_is_rejected(self, tmp_path: Path, typo: str) -> None:
        """The real fields are `prompt_template` and `allowed_tools`. Without
        extra="forbid" these were silently discarded and the phase ran with no
        prompt at all (fixed in #962; asserted here so it stays fixed)."""
        path = _write(
            tmp_path,
            {
                "id": "typo",
                "name": "Typo",
                "requires_repos": False,
                "phases": [
                    {
                        "id": "one",
                        "name": "One",
                        "order": 1,
                        "prompt_template": "do it",
                        typo: "x",
                    }
                ],
            },
        )
        assert not _gate_accepts(path), f"`{typo}:` was silently discarded"


class TestTheRepositoryOwnWorkflowsStayValid:
    def test_every_shipped_workflow_passes(self) -> None:
        """If this fails, a workflow in the repo cannot be created via the API."""
        import subprocess

        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["uv", "run", "python", "scripts/check_workflow_definitions.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestAnInputArtifactMustBeSuppliedBySomething:
    """An input nothing supplies is a phase reading a file that is never written.

    This is #1166: a `report` phase that reads `verify.md` when no `verify`
    output exists reads nothing, silently, and reports on it anyway. The
    invariant is that every declared input resolves to SOMETHING - an earlier
    phase's output or a declared workflow input. Not "an earlier phase": a
    workflow input is a legitimate supplier, and requiring a producing phase
    would reject workflows that work today.

    `WorkflowDefinition.validate_input_artifacts_resolve` already implements
    this and `tests/contexts/workflows/test_declaration_integrity.py` already
    tests it at the model. What was untested is the GATE's verdict, and the two
    are not the same assertion. Measured, not assumed: making the gate swallow
    this one rejection -

        except (ValidationError, ValueError, OSError) as exc:
            if "input_artifacts" in str(exc):
                return None

    - leaves all 56 model-level and fitness tests green and fails only the
    first test below. That is not a hypothetical mutation. It is the shortest
    path to a green run for anyone who hits this rejection on a workflow they
    believe is fine, which makes it the one worth nailing down here.
    """

    def test_an_input_nothing_supplies_is_rejected(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            {
                "id": "starved",
                "name": "Starved",
                "requires_repos": False,
                "phases": [
                    {
                        "id": "produce",
                        "name": "Produce",
                        "order": 1,
                        "prompt_template": "x",
                        "output_artifacts": ["plan"],
                    },
                    {
                        "id": "report",
                        "name": "Report",
                        "order": 2,
                        "prompt_template": "x",
                        "input_artifacts": ["verify_notes"],
                    },
                ],
            },
        )

        reason = validate_file(path)

        assert reason is not None, (
            "the gate accepted a phase whose declared input no phase produces "
            "and no workflow input provides; that phase reads nothing at "
            "runtime and says so to no one (#1166)"
        )
        assert "report" in reason, f"the rejection must name the offending PHASE, got: {reason!r}"
        assert "verify_notes" in reason, (
            f"the rejection must name the unsatisfied INPUT, got: {reason!r}"
        )

    def test_an_input_an_earlier_phase_produces_is_accepted(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            {
                "id": "chained",
                "name": "Chained",
                "requires_repos": False,
                "phases": [
                    {
                        "id": "produce",
                        "name": "Produce",
                        "order": 1,
                        "prompt_template": "x",
                        "output_artifacts": ["plan"],
                    },
                    {
                        "id": "report",
                        "name": "Report",
                        "order": 2,
                        "prompt_template": "x",
                        "input_artifacts": ["plan"],
                    },
                ],
            },
        )

        assert _gate_accepts(path), (
            f"a phase consuming an earlier phase's declared output was rejected: "
            f"{validate_file(path)!r}"
        )

    def test_an_input_a_workflow_input_supplies_is_accepted(self, tmp_path: Path) -> None:
        """The case a stricter "must have a producing PHASE" rule would break.

        A first phase has no earlier phase and no other spelling for its
        dependency. Rejecting this would make authors delete the declaration
        rather than fix it, which loses the graph the check exists to protect.
        """
        path = _write(
            tmp_path,
            {
                "id": "from-input",
                "name": "From Input",
                "requires_repos": False,
                "inputs": [{"name": "task", "description": "the task", "required": True}],
                "phases": [
                    {
                        "id": "research",
                        "name": "Research",
                        "order": 1,
                        "prompt_template": "x",
                        "input_artifacts": ["task"],
                    },
                ],
            },
        )

        assert _gate_accepts(path), (
            f"a phase consuming a DECLARED WORKFLOW INPUT was rejected: "
            f"{validate_file(path)!r}. A workflow input is a legitimate "
            "supplier; this phase is not starved."
        )


class TestNoShippedWorkflowDeclaresToolsItCannotGet:
    """#1207, and the two blind spots that let one sit in the tree unseen.

    The vocabulary lost four names the CLI never granted. That is only safe to
    ship if nothing tracked here declares one, and a one-off grep is not a
    gate. Worse, a grep of the YAML is the wrong instrument twice over:

    1. ``allowed_tools`` need not appear in the workflow YAML at all. A phase
       with ``prompt_file:`` inherits ``allowed-tools`` from that .md file's
       frontmatter for any key the YAML leaves unset. The one real instance in
       this repo - the codex phase in the delegation workflow - is invisible to
       ``grep allowed_tools workflows/``, which is why it was reported as "not
       in the repo".
    2. ``check_workflow_definitions.main()`` skips workflow PACKAGES, because
       their package-relative skill refs only resolve against a plugin root.
       The delegation workflow lives in one, so the repo's own gate was green
       on a file that does not validate.

    So this reads the EFFECTIVE declaration through the real loader, which
    performs the frontmatter merge itself, and it covers packages.
    """

    #: Workflows the loader cannot resolve standing alone. Every one of them
    #: fails for the same reason: a package-relative skill ref (``./skills/x``)
    #: only resolves against a plugin root, and ``WorkflowDefinition.from_file``
    #: has no seam for one. (The two starter-plugin entries report their
    #: ``shared://`` prompt first; supplying ``phase_library_dir`` only uncovers
    #: the same skill-ref error underneath, so the exemption is not removable by
    #: passing that argument - measured, not assumed.)
    #:
    #: Enumerated rather than computed by a predicate, so ADDING one is a test
    #: failure somebody has to argue for. Exempt here is the ONLY way a workflow
    #: may be absent from the checks below; see ``_definitions``.
    UNRESOLVABLE_ALONE: ClassVar[set[str]] = {
        "workflows/examples/starter-plugin/workflows/pr-review/workflow.yaml",
        "workflows/examples/starter-plugin/workflows/research/workflow.yaml",
        "workflows/validation/workflows/skills-injection/workflow.yaml",
    }

    def _load_every_shipped_workflow(
        self,
    ) -> tuple[list[tuple[Path, WorkflowDefinition]], dict[str, str]]:
        """Load them all, keeping WHY each failure failed.

        The reason is kept, not just the name, because it is the whole content
        of the failure report: "delegation/workflow.yaml is unresolvable" sends
        the reader back to the loader, while the ValidationError it raised
        already says the codex phase cannot honour allowed_tools.
        """
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        loaded: list[tuple[Path, WorkflowDefinition]] = []
        unresolvable: dict[str, str] = {}
        for path in _workflow_files():
            raw = yaml.safe_load(path.read_text())
            if not isinstance(raw, dict) or "phases" not in raw:
                continue  # marketplace manifests and fragments are not workflows
            try:
                loaded.append((path, WorkflowDefinition.from_file(path)))
            except (ValidationError, ValueError, OSError) as exc:
                unresolvable[path.relative_to(_REPO_ROOT).as_posix()] = str(exc)
        return loaded, unresolvable

    def _definitions(self) -> list[tuple[Path, WorkflowDefinition]]:
        """Every shipped workflow, loaded - or a FAILURE naming the ones that were not.

        The checks below iterate exactly what this returns, so a workflow this
        drops is a workflow they claim to cover and do not. This helper used to
        drop them silently: load errors went into a set nobody downstream read,
        which made the collection under test precisely the collection that
        already passes. Both checks below were therefore green when the
        delegation workflow's ``allowed_tools: []`` override was deleted - the
        one mutation their own docstrings say they catch (review of #1210).

        So an unloadable workflow is now one of two things and never a third:
        a failure here, quoting the loader's own error, or an argued entry in
        ``UNRESOLVABLE_ALONE``. It is never an invisible omission.
        """
        loaded, unresolvable = self._load_every_shipped_workflow()
        unexpected = {
            path: reason
            for path, reason in unresolvable.items()
            if path not in self.UNRESOLVABLE_ALONE
        }

        assert not unexpected, (
            "these workflows did not load, so the checks in this class cannot "
            "see them. Fix the workflow, or add it to UNRESOLVABLE_ALONE with "
            "a reason: " + "; ".join(f"{path} -> {reason}" for path, reason in unexpected.items())
        )

        return loaded

    def test_the_set_of_workflows_this_cannot_check_has_not_grown(self) -> None:
        """The exemption list is an assertion, not an escape hatch.

        ``_definitions`` already fails on an unlisted unloadable workflow. This
        catches the other direction, which that cannot: an entry that has been
        FIXED and should now be checked, kept exempt out of habit.
        """
        _, unresolvable = self._load_every_shipped_workflow()

        assert set(unresolvable) == self.UNRESOLVABLE_ALONE, (
            "a workflow became unresolvable standing alone, so the checks below "
            "silently stopped covering it - which is exactly how #1207 hid. "
            "Errors: " + "; ".join(f"{path} -> {reason}" for path, reason in unresolvable.items())
        )

    def test_every_declared_tool_is_a_name_the_cli_actually_grants(self) -> None:
        from syn_shared.tools import canonical_tool_name

        offenders = [
            (path, phase.id, name)
            for path, definition in self._definitions()
            for phase in definition.phases
            for name in phase.allowed_tools
            if canonical_tool_name(name) is None
        ]

        assert not offenders, (
            "these declarations name a tool the CLI does not grant, so the "
            "phase would run with an empty tool set: "
            + "; ".join(f"{p}::{phase} -> {name}" for p, phase, name in offenders)
        )

    def test_no_codex_phase_declares_tools_it_cannot_honour(self) -> None:
        """The one real instance (#1207), pinned so it cannot come back.

        Codex has no tool vocabulary at all - it scopes with a filesystem
        sandbox (#1202) - so ``allowed_tools`` on a codex phase is refused at
        creation. Before the fix this held for every tracked workflow EXCEPT
        the delegation one, whose declaration arrived from prompt frontmatter.
        """
        offenders = [
            (path, phase.id, list(phase.allowed_tools))
            for path, definition in self._definitions()
            for phase in definition.phases
            if phase.allowed_tools and (phase.agent.provider if phase.agent else None) == "codex"
        ]

        assert not offenders, (
            "a codex phase cannot honour allowed_tools and is refused at "
            "creation: " + "; ".join(f"{p}::{ph} -> {t}" for p, ph, t in offenders)
        )

    def test_the_delegation_workflow_validates(self) -> None:
        """(d) The workflow #1207 named, checked through the gate's own validator.

        It is a workflow PACKAGE member, so ``main()`` skips it and this is the
        only thing checking it. Before the fix ``validate_file`` returned the
        codex-cannot-honour-allowed_tools error.
        """
        path = _REPO_ROOT / "workflows/validation/workflows/delegation/workflow.yaml"

        assert validate_file(path) is None

    def test_the_delegation_phase_keeps_the_harness_it_exists_to_exercise(self) -> None:
        """The fix must not be "make the error go away".

        Switching the phase to ``provider: claude`` also validates, and would
        gut the workflow: it exists to prove a CODEX-primary phase can delegate
        to ``claude -p`` and that both legs are costed (#895). So the tools go
        and the provider stays.
        """
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )

        definition = WorkflowDefinition.from_file(
            _REPO_ROOT / "workflows/validation/workflows/delegation/workflow.yaml"
        )
        phase = definition.phases[0]

        assert phase.id == "build-and-delegate"
        assert phase.agent is not None
        assert phase.agent.provider == "codex", "the cross-harness leg is the point"
        assert phase.agent.allow_delegation is True
        assert phase.allowed_tools == [], (
            "the YAML must override the frontmatter's allowed-tools; an absent "
            "key inherits Read,Write,Bash from phases/delegate.md and the "
            "workflow stops validating"
        )


class TestNoPromptAsksPastItsGrant:
    """A phase's instructions and its tool grant must agree (#1122).

    THE FAILURE. #1110 added a `gh pr comment` step to the pr-review `report`
    prompt so a review would deliver itself. `report` grants Read, Grep, Glob,
    Write. The install succeeded and the deployed prompt carried the step, so
    three reviews (#1113, #1115, #1117) each wrote "this needs a tool this
    phase does not have" and left their verdicts in object storage.

    WHY NOTHING CAUGHT IT. Each half is valid on its own - a prompt may say
    anything, and that tool list is a perfectly good tool list. Only the PAIR
    is wrong, and the two halves live in different files, which is why review
    read past it three times. A schema cannot express the pair, so the create
    endpoint accepts it too.

    The three outcomes of shipping the pair are all bad and one is silent: the
    phase fails, or it finds a way around the restriction, or it quietly does
    not do the thing - and nothing reports the third.
    """

    def _violations(
        self,
        tmp_path: Path,
        tools: list[str],
        prompt: str,
        outputs: list[str] | None = None,
    ) -> list[str]:
        path = _write(
            tmp_path,
            {
                "id": "pair",
                "name": "Pair",
                "requires_repos": False,
                "phases": [
                    {
                        "id": "the-phase",
                        "name": "The phase",
                        "order": 1,
                        "prompt_template": prompt,
                        "allowed_tools": tools,
                        "output_artifacts": outputs or [],
                    }
                ],
            },
        )
        return grant_violations(path)

    #: The instruction that actually shipped, quoted from the #1110 prompt.
    POSTING_STEP: ClassVar[str] = (
        "After writing your deliverable, post it as a comment on the PR:\n\n"
        "```bash\n"
        "gh pr comment <PR-NUMBER> --repo <OWNER>/<REPO> --body-file <your-deliverable>\n"
        "```\n"
    )

    def test_a_prompt_that_runs_shell_without_bash_is_reported(self, tmp_path: Path) -> None:
        """The reproduction. This is the pair that shipped in #1110."""
        (violation,) = self._violations(
            tmp_path, ["Read", "Grep", "Glob", "Write"], self.POSTING_STEP
        )

        assert "the-phase" in violation
        assert "run shell" in violation
        assert "none of [Bash]" in violation

    def test_a_blockquoted_shell_fence_fails_closed(self, tmp_path: Path) -> None:
        """A fence inside a CommonMark block quote is still an instruction.

        The info-string layer was fixed first: bare, capitalised, tilde and
        four-backtick fences all read correctly. The CONTAINER layer was not.
        `_FENCE` allowed leading whitespace and one list marker, so a fence
        nested in a block quote - a quoted command, which is exactly how a
        prompt shows the step it wants run - matched nothing, and a miss reads
        as a pass.

        Same defect class as the four already fixed, one layer up: a fence the
        matcher cannot see, in a position nobody enumerated.
        """
        prompt = (
            "Post your deliverable. Run the quoted command:\n\n"
            "> ```bash\n"
            "> gh pr comment 42 --repo o/r --body-file out.md\n"
            "> ```\n"
        )
        (violation,) = self._violations(tmp_path, ["Read", "Grep", "Glob", "Write"], prompt)
        assert "Bash" in violation

    def test_a_nested_blockquoted_shell_fence_fails_closed(self, tmp_path: Path) -> None:
        """CommonMark allows the container to nest, so one level is not the rule."""
        prompt = (
            "Quoting a review that quoted the step:\n\n"
            "> > ```bash\n"
            "> > gh pr comment 42 --repo o/r --body-file out.md\n"
            "> > ```\n"
        )
        (violation,) = self._violations(tmp_path, ["Read", "Grep", "Glob", "Write"], prompt)
        assert "Bash" in violation

    def test_a_blockquoted_exempt_fence_is_still_exempt(self, tmp_path: Path) -> None:
        """Reading the container must not make every quoted block look like shell.

        The pairing walk has to close a block quoted opener with its block
        quoted closer, or an exempt block's own closing fence reads as a bare
        opener - which would report every prompt that quotes a table.
        """
        prompt = (
            "The report looked like this:\n\n"
            "> ```text\n"
            "> gh pr comment 42 --repo o/r --body-file out.md\n"
            "> ```\n"
        )
        assert self._violations(tmp_path, ["Read", "Grep", "Glob", "Write"], prompt) == []

    def test_a_quoted_exempt_opener_does_not_absorb_an_unquoted_shell_fence(
        self, tmp_path: Path
    ) -> None:
        """A fence closes one opened at the SAME quote depth, or it closes nothing.

        Teaching the PATTERN about block-quote containers without teaching the
        WALK about them created a new fail-open: a quoted `text` opener never
        meets its quoted closer if the walk ignores depth, so it stays open
        across the end of its own block quote and swallows the unquoted
        ```bash fence that follows. A CommonMark parser renders that last block
        as bash; the gate saw content inside an exempt block and reported
        nothing.

        Found by cross-model review of the container-prefix fix, which is to
        say: introduced by the previous commit in this PR.
        """
        prompt = (
            "Here is what the report looked like:\n\n"
            "> ```text\n"
            "> shown\n\n"
            "Now run it:\n\n"
            "```bash\n"
            "gh pr comment 42 --repo o/r --body-file out.md\n"
            "```\n"
        )
        (violation,) = self._violations(tmp_path, ["Read", "Grep", "Glob", "Write"], prompt)
        assert "Bash" in violation

    def test_a_quoted_exempt_block_still_closes_at_its_own_depth(self, tmp_path: Path) -> None:
        """The guard must not make every quoted exempt block unclosable."""
        prompt = (
            "The report looked like this:\n\n"
            "> ```text\n"
            "> gh pr comment 42 --repo o/r --body-file out.md\n"
            "> ```\n"
        )
        assert self._violations(tmp_path, ["Read", "Grep", "Glob", "Write"], prompt) == []

    def test_the_same_prompt_is_fine_when_bash_is_granted(self, tmp_path: Path) -> None:
        """Negative control on the GRANT.

        Without it this class passes just as well against a check that reports
        every fenced prompt, which would fail every phase that legitimately
        runs commands - `open_pr` and `quickfix` publish exactly this way.
        """
        assert self._violations(tmp_path, ["Read", "Bash", "Write"], self.POSTING_STEP) == []

    def test_a_scoped_bash_grant_is_not_a_spelling_this_has_to_know(self, tmp_path: Path) -> None:
        """Why the membership test is a plain `in` and needs no prefix match.

        The first version of this check accepted `Bash(gh:*)` as a Bash grant,
        reasoning that a scoped grant still runs the command. It cannot arise:
        `allowed_tools` is validated against a fixed vocabulary of bare names
        (#1207), so the definition never loads. Pinned because the alternative
        is a prefix match nothing can reach, which reads to the next person as
        a spelling the gate handles - and invites more of them.
        """
        with pytest.raises(ValidationError, match="unknown tool name"):
            self._violations(tmp_path, ["Read", "Bash(gh:*)"], self.POSTING_STEP)

    def test_the_same_grant_is_fine_without_the_instruction(self, tmp_path: Path) -> None:
        """Negative control on the PROMPT: a Bash-less phase is not itself a
        defect. Most phases in this repo are one, deliberately."""
        assert (
            self._violations(
                tmp_path,
                ["Read", "Grep", "Glob", "Write"],
                "Compose the verdict from artifacts/input and write it out. You are read-only.",
            )
            == []
        )

    def test_an_empty_allowlist_is_not_a_restriction(self, tmp_path: Path) -> None:
        """`_build_agent_command` omits `--tools` entirely for an empty list, so
        the phase holds every tool. Reporting it would fail every codex phase,
        which cannot carry a tool list at all (#1207)."""
        assert self._violations(tmp_path, [], self.POSTING_STEP) == []

    def test_no_shipped_workflow_ships_the_pair(self) -> None:
        """The whole corpus, PACKAGES INCLUDED.

        `main()` skips workflow packages, so the repo's own gate cannot see
        `examples/research-package` or the starter plugin. Driving
        `grant_violations` directly covers them, and reuses the exemption list
        argued in the class above rather than restating it - a second copy
        would let the two drift, and drift in an exemption list is invisible.
        """
        exempt = TestNoShippedWorkflowDeclaresToolsItCannotGet.UNRESOLVABLE_ALONE
        offenders: list[str] = []
        for path in _workflow_files():
            raw = yaml.safe_load(path.read_text())
            if not isinstance(raw, dict) or "phases" not in raw:
                continue
            if path.relative_to(_REPO_ROOT).as_posix() in exempt:
                continue
            offenders.extend(
                f"{path.relative_to(_REPO_ROOT).as_posix()}: {why}"
                for why in grant_violations(path)
            )

        assert not offenders, "\n".join(offenders)


class TestNoPhaseMustProduceAnArtifactItCannotWrite:
    """A phase declaring an output must hold a tool that can create a file.

    THE SECOND SPELLING OF #1122. The gate above was written for the shape
    #1110 shipped - a shell fence in a prompt, no Bash - and that is the only
    shape it knew. So the fix for #1122 passed its own gate while three phases
    of `research-experiment-plan` carried the identical defect stated
    differently: `revise-after-experiment`, `plan` and `final-plan` each
    declare `output_artifacts: [markdown]` and grant `[Read, Grep, Glob]`.

    No Write and no Bash is not a phase that does its job awkwardly. It is a
    phase that CANNOT put anything in `artifacts/output/`, so the collector
    finds an empty directory and the phase after it - `review-plan` reading
    `plan`, `final-plan` reading `review-plan` - starts from nothing. Silent,
    because a phase that produces no artifact does not fail.

    WHY THE DECLARATION AND NOT THE PROMPT. Every phase says what it delivers
    twice, once in prose and once in `output_artifacts`, and only the second is
    structured. Matching the prose means matching "write to artifacts/output",
    which the phases that only READ that directory also contain - it is in the
    boilerplate telling them where their input came from. The declaration says
    the same thing without the ambiguity, and cannot be dodged by rewording.
    """

    def _violations(self, tmp_path: Path, tools: list[str], outputs: list[str]) -> list[str]:
        return TestNoPromptAsksPastItsGrant()._violations(
            tmp_path,
            tools,
            # No fence: this class must be driven by the DECLARATION alone. A
            # prompt that also ran shell would let the other demand raise the
            # violation and these tests would pass without this one existing.
            "Read the input and deliver the plan.",
            outputs=outputs,
        )

    #: The grant the three phases actually shipped with.
    READ_ONLY: ClassVar[list[str]] = ["Read", "Grep", "Glob"]

    def test_a_declared_output_without_write_or_bash_is_reported(self, tmp_path: Path) -> None:
        """The reproduction, with the exact pair the three phases shipped."""
        (violation,) = self._violations(tmp_path, self.READ_ONLY, ["markdown"])

        assert "the-phase" in violation
        assert "create a file" in violation
        assert "Bash, Write" in violation

    def test_write_satisfies_it(self, tmp_path: Path) -> None:
        """Negative control on the GRANT, and the fix that was applied."""
        assert self._violations(tmp_path, [*self.READ_ONLY, "Write"], ["markdown"]) == []

    def test_bash_satisfies_it_without_write(self, tmp_path: Path) -> None:
        """Bash alone is enough, and this is load-bearing, not a technicality.

        `research` and `revise-spec` in the same workflow grant
        `[Read, Grep, Glob, Bash]` and declare a markdown output. They are NOT
        the defect - a heredoc creates a file - and the audit for this change
        left them alone on exactly this reasoning. Pinned so that a later
        tightening to "Write specifically" has to argue with a test rather than
        silently reclassify two working phases as broken.
        """
        assert self._violations(tmp_path, [*self.READ_ONLY, "Bash"], ["markdown"]) == []

    def test_a_phase_declaring_no_output_is_not_asked_to_write(self, tmp_path: Path) -> None:
        """Negative control on the DECLARATION: read-only phases are fine.

        Without this the check could report every Write-less phase, which would
        make `output_artifacts` irrelevant to a check that claims to read it.
        """
        assert self._violations(tmp_path, self.READ_ONLY, []) == []

    def test_naming_the_input_directory_in_prose_is_not_a_declaration(self, tmp_path: Path) -> None:
        """The false positive this design avoids, quoted from the real prompts.

        Every phase in `research-experiment-plan` carries this paragraph, and a
        check that matched `artifacts/output` in prose would report all of them
        - including the read-only ones, where the mention describes where the
        PREVIOUS phase wrote.
        """
        assert (
            TestNoPromptAsksPastItsGrant()._violations(
                tmp_path,
                self.READ_ONLY,
                "> The durable location is `artifacts/input/<phase-id>/`, holding\n"
                "> whatever the previous phase wrote under `artifacts/output/`.\n",
                outputs=[],
            )
            == []
        )

    def test_every_plan_phase_reaches_the_platform_able_to_write(self) -> None:
        """The three phases, through the conversion the create endpoint runs.

        Not `grant_violations` and not the YAML: those are the two ends, and a
        grant that is correct in the file but dropped in conversion passes both
        while the deployed phase still cannot write. `build_command_from_definition`
        is the hop between them and the last point the value is ours.
        """
        from syn_domain.contexts.orchestration._shared.workflow_definition import (
            WorkflowDefinition,
        )
        from syn_domain.contexts.orchestration._shared.yaml_to_command import (
            build_command_from_definition,
        )

        definition = WorkflowDefinition.from_file(
            _REPO_ROOT / "workflows/sdlc/research-experiment-plan/workflow.yaml"
        )
        phases = {p.phase_id: p for p in build_command_from_definition(definition).phases}

        unable = {
            phase_id: sorted(phase.allowed_tools)
            for phase_id, phase in phases.items()
            if phase.output_artifact_types
            and phase.allowed_tools
            and not {"Write", "Bash"} & set(phase.allowed_tools)
        }

        assert unable == {}, (
            f"these phases are handed to the platform declaring an output they "
            f"cannot produce: {unable}"
        )


class TestEveryFenceSpellingIsShellUnlessItSaysOtherwise:
    """A fence the matcher cannot read must fail CLOSED (#1261 review).

    THE DEFECT. The first version of this matched one spelling: three
    backticks, an optional space, then one of `bash|sh|shell|zsh|console`,
    case-sensitively. Every other fence CommonMark allows missed - a bare
    fence with no info string, `Bash` with a capital B, a four-backtick fence,
    a tilde fence. On a miss `_told_to_run_shell` returned None,
    `grant_violations` hit `continue`, and no violation was recorded.

    A miss was silence and silence was a pass. That is the whole defect: the
    gate could not distinguish "this prompt runs no shell" from "this prompt
    runs shell in a spelling I do not know", and reported both as fine. It was
    reproduced end to end against #1110 itself - retyped with an ordinary bare
    fence, the gate reported zero violations for the exact pair it exists to
    catch. Bare fences outnumber tagged ones in this repo's own prompts, so
    the common spelling was the invisible one.

    THE FIX IS THE INVERSION. The vocabulary is now an allowlist of NON-shell
    info strings, and an unknown or absent one is shell. A spelling nobody
    anticipated therefore produces a false POSITIVE, which someone sees and
    tags, rather than a false negative, which nobody sees at all. That
    asymmetry is the point and the reason the list is short: every entry is a
    deliberate exemption, and the cost of a missing one is a visible failure.

    Each case below is the #1110 instruction verbatim, retyped in one more
    spelling of a fence. All four failed against the old regex.
    """

    def _violations_for(self, tmp_path: Path, prompt: str) -> list[str]:
        """The #1110 grant, so the ONLY variable across these cases is the fence."""
        return TestNoPromptAsksPastItsGrant()._violations(
            tmp_path, ["Read", "Grep", "Glob", "Write"], prompt
        )

    def _assert_reported(self, violations: list[str]) -> None:
        assert len(violations) == 1, f"expected the pair to be reported, got {violations!r}"
        assert "run shell" in violations[0]
        assert "none of [Bash]" in violations[0]

    #: The body of the block, identical in every case below.
    RUNS: ClassVar[str] = "gh pr comment 42 --repo o/r --body-file out.md"

    def test_a_bare_fence_is_shell(self, tmp_path: Path) -> None:
        """The spelling that outnumbers every other in this repo's prompts, and
        the one the old regex could not see at all."""
        self._assert_reported(
            self._violations_for(tmp_path, f"Post it:\n\n```\n{self.RUNS}\n```\n")
        )

    def test_a_capitalised_tag_is_shell(self, tmp_path: Path) -> None:
        """The old pattern carried no `re.I`, so `Bash` and `BASH` both missed
        while `bash` matched - a defect no reader of the prompt could observe."""
        self._assert_reported(
            self._violations_for(tmp_path, f"Post it:\n\n```Bash\n{self.RUNS}\n```\n")
        )

    def test_a_tilde_fence_is_shell(self, tmp_path: Path) -> None:
        """CommonMark's other fence character. The old pattern hard-coded the
        backtick, so a tilde fence was not a fence to it."""
        self._assert_reported(
            self._violations_for(tmp_path, f"Post it:\n\n~~~bash\n{self.RUNS}\n~~~\n")
        )

    def test_a_four_backtick_fence_is_shell(self, tmp_path: Path) -> None:
        """Four backticks is the ordinary way to fence a block that itself
        contains a fence, so it appears exactly where prompts quote prompts."""
        self._assert_reported(
            self._violations_for(tmp_path, f"Post it:\n\n````bash\n{self.RUNS}\n````\n")
        )

    def test_a_tagged_non_shell_block_is_not_shell(self, tmp_path: Path) -> None:
        """The negative control on the INVERSION.

        Without this, every test above passes against a matcher that calls
        every fence shell - which would fail every read-only phase that shows
        the shape of its own output, and there are many. The exemption has to
        be real, and this is the tag the one affected block in the corpus was
        given.
        """
        assert (
            self._violations_for(
                tmp_path, "Open with this line:\n\n```text\nReviewed at head `<sha>`.\n```\n"
            )
            == []
        )

    def test_a_closing_fence_is_not_a_bare_opener(self, tmp_path: Path) -> None:
        """Why this walks fence PAIRS and does not scan lines.

        The closing fence of any tagged block is, on its own line, exactly a
        bare fence. A line scanner that treats bare as shell would therefore
        report every exempt block in the corpus via its own closer - the
        inversion would be unusable and the pressure would be to revert it.
        Tracking the open/close state is what makes failing closed affordable.
        """
        assert (
            self._violations_for(
                tmp_path,
                "Two exempt blocks:\n\n```text\nfirst\n```\n\nand\n\n```yaml\nid: x\n```\n",
            )
            == []
        )

    def test_a_fence_inside_an_exempt_block_is_not_an_opener(self, tmp_path: Path) -> None:
        """Content between a pair is content, not markup.

        A `text` block quoting a bash fence is showing it, not running it - the
        report template does exactly this. Reading the inner fence as an opener
        would make quoting a command indistinguishable from being told to run
        one.
        """
        assert (
            self._violations_for(
                tmp_path,
                f"Your report should look like:\n\n````text\n```bash\n{self.RUNS}\n```\n````\n",
            )
            == []
        )


class TestContainerNestingIsNotOneFixedShape:
    """Fences the walk used to miss, each found by a cross-model review.

    Every case here reaches `grant_violations` rather than the fence helper,
    because the helper returning an offset is not the claim the gate makes. The
    claim is that a phase told to run shell without a Bash grant is reported,
    and only the end-to-end call can be wrong about that.

    What these have in common is that the earlier walk was right about the
    inputs it had been shown and wrong about the shape of the space. It knew
    one nesting order, and it reasoned about a single fence at a time when the
    damage from mispairing one fence is that every fence AFTER it is read in
    the wrong state.
    """

    TOOLS: ClassVar[list[str]] = ["Read", "Grep", "Glob", "Write"]

    def _violations(self, tmp_path: Path, prompt: str) -> list[str]:
        return grant_violations(
            _write(
                tmp_path,
                {
                    "id": "nest",
                    "name": "Nest",
                    "requires_repos": False,
                    "phases": [
                        {
                            "id": "the-phase",
                            "name": "The phase",
                            "order": 1,
                            "prompt_template": prompt,
                            "allowed_tools": self.TOOLS,
                            "output_artifacts": [],
                        }
                    ],
                },
            )
        )

    def test_a_mispaired_closer_desyncs_the_walk_onto_a_phantom_opener(
        self, tmp_path: Path
    ) -> None:
        """Why the closing rule has to compare container depth.

        The argument for dropping that comparison was that a DEEPER fence
        closing a shallower opener can only end a block early, which fails
        closed. That is true of the one fence and false of the document: the
        walk carries its state forward. Here the deeper `> ``` ` ends the
        exempt block early, the displayed `~~~text` line is then read as a real
        opener, backticks cannot close a tilde fence, and the genuine ```bash
        instruction below is swallowed as that phantom's content.
        """
        prompt = "```text\n> ```\n~~~text\n```\nNow run this:\n```bash\necho RUN\n```\n"
        (violation,) = self._violations(tmp_path, prompt)
        assert "must run shell" in violation

    def test_the_closing_fence_of_a_quoting_block_is_not_an_instruction(
        self, tmp_path: Path
    ) -> None:
        """The same missing comparison, costing a false positive.

        A `text` block that displays a quoted fence is one block: CommonMark
        does not let the deeper line close it. Reading that line as the closer
        leaves the block's REAL closing fence looking like a bare opener, and a
        bare fence names no exempt language, so the gate reported a prompt that
        runs nothing. This gate blocks merges; a false positive is not a safe
        direction to be wrong in.
        """
        assert self._violations(tmp_path, "```text\n> ```\n```\n") == []

    @pytest.mark.parametrize(
        ("label", "prompt"),
        [
            ("list containing a quote", "- > ```bash\n  > echo RUN\n"),
            ("list containing a list", "- - ```bash\n    echo RUN\n"),
            ("quote containing a list", "> - ```bash\n>   echo RUN\n"),
            ("two quotes then a list", "> > - ```bash\n> >   echo RUN\n"),
        ],
    )
    def test_containers_nest_in_any_order(self, tmp_path: Path, label: str, prompt: str) -> None:
        """CommonMark imposes no order on container markers, so neither can we.

        The previous pattern read quote markers followed by at most ONE list
        marker. That is a description of the examples it was written against,
        not of the grammar. Each prompt here is valid CommonMark containing a
        real bash block, and each matched nothing at all.

        These are deliberately UNTERMINATED, which is the silent half: a fence
        with no closing line gives the walk no later mismatch that might expose
        the miss.
        """
        assert self._violations(tmp_path, prompt), label


class TestARenameMustNotLeaveANameBehind:
    """#1298. The `bootstrap` -> `premise` rename had to land in four workflows,
    and in each one the phase AFTER it carried the old id in its prompt.

    The two halves are one invariant with two failure times. A prompt file
    named for the wrong phase is wrong when someone reads it; a prompt naming a
    phase that does not exist is wrong at RUN time, as an empty input directory
    that the phase reads and proceeds on. The second is the one that costs a
    whole execution, and nothing in the repository looked for it - both rules
    were prose in `workflows/sdlc/README.md`, and the reason it gives for the
    first is precisely that a rename should "break loudly in one place instead
    of silently in two".
    """

    def _workflow(self, prompt: str, first_id: str = "premise") -> dict[str, object]:
        return {
            "id": "renamed",
            "name": "Renamed",
            "requires_repos": False,
            "phases": [
                {
                    "id": first_id,
                    "name": "Check the premise",
                    "order": 1,
                    "prompt_template": "check it",
                    "output_artifacts": ["markdown"],
                },
                {
                    "id": "implement",
                    "name": "Make the change",
                    "order": 2,
                    "prompt_template": prompt,
                    "input_artifacts": ["markdown"],
                },
            ],
        }

    def test_a_prompt_naming_a_phase_that_does_not_exist_is_rejected(self, tmp_path: Path) -> None:
        """The concrete #1298 failure: the phase was renamed, the prompt after
        it was not. Nothing downstream can detect this - the declared input
        artifact TYPE still resolves, because a type says nothing about whose
        output it is."""
        path = _write(
            tmp_path,
            self._workflow("The report is at `artifacts/input/bootstrap.md`."),
        )

        assert _gate_accepts(path), (
            "precondition: this workflow is otherwise valid, so a failure below "
            "is attributable to the reference and not to something else"
        )
        violations = stale_phase_references(path)

        assert violations, (
            "the gate accepted a prompt telling a phase to read the output of a "
            "phase this workflow does not have; at run time that directory is "
            "empty and the phase reports on nothing (#1298)"
        )
        joined = " ".join(violations)
        assert "implement" in joined, f"must name the phase holding the stale reference: {joined}"
        assert "bootstrap" in joined, f"must name the reference that does not resolve: {joined}"

    def test_a_prompt_naming_an_earlier_phase_is_accepted(self, tmp_path: Path) -> None:
        """The negative control. A gate that rejects every `artifacts/input/`
        reference would flag every multi-phase workflow in the repo and get
        deleted within the week."""
        path = _write(
            tmp_path,
            self._workflow("The report is at `artifacts/input/premise.md`."),
        )

        assert stale_phase_references(path) == []

    def test_a_prompt_naming_a_LATER_phase_is_rejected(self, tmp_path: Path) -> None:
        """Existing is not enough - it has to have RUN. A phase reading the
        output of one that comes after it gets the same empty directory as a
        phase reading one that does not exist, and the id resolving makes it
        look wired up."""
        path = _write(
            tmp_path,
            self._workflow("The report is at `artifacts/input/verify.md`."),
        )
        raw = yaml.safe_load(path.read_text())
        raw["phases"].append({"id": "verify", "name": "Verify", "order": 3, "prompt_template": "x"})
        path.write_text(yaml.safe_dump(raw))

        violations = stale_phase_references(path)

        assert violations, "a phase was told to read an artifact from a phase that runs after it"
        assert "verify" in " ".join(violations)

    def test_the_phase_id_placeholder_is_not_read_as_a_reference(self, tmp_path: Path) -> None:
        """Every phase prompt in this repository carries the boilerplate
        `artifacts/input/<phase-id>/` telling it where inputs live. If that
        read as a reference the gate would fail every workflow it ships, which
        is how a gate gets switched off rather than fixed."""
        path = _write(
            tmp_path,
            self._workflow(
                "The durable location is `artifacts/input/<phase-id>/`, and a "
                "flat `artifacts/input/<phase-id>.md` alias also exists."
            ),
        )

        assert stale_phase_references(path) == []

    def test_a_prompt_file_named_for_another_phase_is_rejected(self, tmp_path: Path) -> None:
        """README rule 2, which until now nothing enforced."""
        (tmp_path / "bootstrap.md").write_text("check it")
        path = _write(
            tmp_path,
            {
                "id": "misfiled",
                "name": "Misfiled",
                "requires_repos": False,
                "phases": [
                    {"id": "premise", "name": "Premise", "order": 1, "prompt_file": "bootstrap.md"}
                ],
            },
        )

        violations = stale_phase_references(path)

        assert violations, (
            "phase 'premise' reads 'bootstrap.md' and the gate said nothing; a "
            "rename that moves the id and not the file leaves the old name as "
            "the only thing a reader sees"
        )
        assert "bootstrap.md" in " ".join(violations)

    def test_a_shared_prompt_reference_is_not_a_misfiled_file(self, tmp_path: Path) -> None:
        """`shared://` prompts are named for the JOB and reused by phases with
        different ids - that is what the phase library is for - so the filename
        rule cannot apply to them without banning the feature."""
        lib = tmp_path / "lib"
        lib.mkdir()
        (lib / "summarize.md").write_text("summarize it")
        path = _write(
            tmp_path,
            {
                "id": "shared",
                "name": "Shared",
                "requires_repos": False,
                "phases": [
                    {
                        "id": "premise",
                        "name": "Premise",
                        "order": 1,
                        "prompt_file": "shared://summarize",
                    }
                ],
            },
        )

        assert stale_phase_references(path, phase_library_dir=lib) == [], (
            "the phase library became unusable"
        )
