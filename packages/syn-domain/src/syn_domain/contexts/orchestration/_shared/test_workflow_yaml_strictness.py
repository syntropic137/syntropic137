"""Unknown workflow/phase keys must be rejected, not silently dropped (#961).

Reproduces a real failure on the Mac Mini deployment. A phase authored with
`prompt:` (the correct key is `prompt_template:`) installed cleanly, executed,
cost $0.088, and reported `completed` -- while the agent received no
instructions at all and spent its turns hunting for a task file:

    ls -la /workspace/
    find /workspace -name "CLAUDE.md" -o -name "AGENTS.md" -o -name "task*"
    cat /workspace/artifacts/input/* || echo "No input files found"

Every layer reported success. The only signal an author can get is a rejection
at parse time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from typing_extensions import TypedDict

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
)

pytestmark = pytest.mark.unit


class _PhaseKwargs(TypedDict, total=False):
    """Structured phase kwargs, so the fixture is not an untyped dict (ADR-063)."""

    id: str
    order: int
    name: str
    prompt_template: str
    prompt_file: str
    allowed_tools: list[str]


def _phase(**overrides: object) -> _PhaseKwargs:
    base = _PhaseKwargs(id="p1", order=1, name="p1", prompt_template="do the thing")
    for key, value in overrides.items():
        base[key] = value  # type: ignore[literal-required]  # test builds bad keys on purpose
    return base


class TestPhaseRejectsUnknownKeys:
    def test_misspelled_prompt_is_rejected_not_dropped(self) -> None:
        """The exact bug: `prompt` instead of `prompt_template`."""
        data = _phase()
        del data["prompt_template"]
        data["prompt"] = "THE INSTRUCTION THE AGENT NEVER RECEIVED"

        with pytest.raises(ValidationError) as exc:
            PhaseYamlDefinition(**data)
        assert "prompt" in str(exc.value)

    def test_hyphenated_allowed_tools_is_rejected(self) -> None:
        """Phase frontmatter uses `allowed-tools`; phase YAML uses `allowed_tools`.

        Both spellings appear in project docs, so an author moving between the
        two formats silently lost their tool allowlist.
        """
        with pytest.raises(ValidationError):
            PhaseYamlDefinition(**_phase(**{"allowed-tools": ["Bash"]}))

    def test_bare_tools_key_is_rejected(self) -> None:
        """Four shipped trigger workflows used `tools:` and lost the allowlist.

        `allowed_tools: []` means unrestricted, so dropping a declared allowlist
        silently GRANTS tools rather than denying them.
        """
        with pytest.raises(ValidationError):
            PhaseYamlDefinition(**_phase(tools=["bash"]))

    def test_correctly_spelled_phase_still_parses(self) -> None:
        phase = PhaseYamlDefinition(**_phase(allowed_tools=["Bash", "Read"]))
        assert phase.prompt_template == "do the thing"
        assert phase.allowed_tools == ["Bash", "Read"]


class TestPhaseRequiresInstructions:
    def test_phase_with_no_prompt_source_is_rejected(self) -> None:
        """Independent second guard: an empty prompt can never do useful work."""
        data = _phase()
        del data["prompt_template"]
        with pytest.raises(ValidationError) as exc:
            PhaseYamlDefinition(**data)
        assert "prompt_template" in str(exc.value)

    def test_prompt_file_alone_is_accepted(self) -> None:
        data = _phase()
        del data["prompt_template"]
        data["prompt_file"] = "phase.md"
        assert PhaseYamlDefinition(**data).prompt_file == "phase.md"

    def test_both_prompt_sources_still_rejected(self) -> None:
        """Pre-existing rule must survive the new one."""
        with pytest.raises(ValidationError):
            PhaseYamlDefinition(**_phase(prompt_file="phase.md"))


class TestWorkflowRejectsUnknownKeys:
    def test_unknown_workflow_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            WorkflowDefinition(
                id="wf-1",
                name="wf",
                phases=[_phase()],
                **{"promptt": "typo"},
            )
        assert "promptt" in str(exc.value)

    def test_correctly_spelled_workflow_still_parses(self) -> None:
        wf = WorkflowDefinition(id="wf-1", name="wf", phases=[_phase()])
        assert wf.name == "wf"
        assert len(wf.phases) == 1
