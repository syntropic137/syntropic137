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
from scripts.check_workflow_definitions import _workflow_files, validate_file

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
