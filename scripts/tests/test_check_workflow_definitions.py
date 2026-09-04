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

import pytest
import yaml
from scripts.check_workflow_definitions import validate_file

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
