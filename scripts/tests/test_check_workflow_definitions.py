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
