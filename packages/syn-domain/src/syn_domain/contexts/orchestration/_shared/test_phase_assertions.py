"""The authoring hop for declared phase assertions (#1085).

The behaviour that matters - a broken capability failing its execution - is
driven end to end in
``packages/syn-domain/tests/contexts/workflows/execute_workflow/test_declared_phase_assertions.py``.
What is left here is the half that test cannot see: whether the YAML an
operator writes reaches the domain at all, and whether a pattern that cannot
compile is caught while they are writing it rather than a container run later.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.phase_assertions import (
    PhaseAssertionError,
    require_asserted_output,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[7]
_VALIDATION = _REPO_ROOT / "workflows" / "validation" / "workflows"

_YAML = """
id: wf-assert
name: Asserting workflow
type: custom
classification: simple
phases:
  - id: exercise
    name: Exercise
    order: 1
    prompt_template: do the thing
    asserts:
      - '^CLOSE: ok$'
      - '^TOKEN_SCOPE: none$'
"""


class TestTheDeclarationReachesTheDomain:
    def test_yaml_asserts_survive_to_domain(self) -> None:
        """The seam #1039 lived in: a phase field parsed, stored, and dropped
        one hop before it could do anything."""
        (phase,) = WorkflowDefinition.from_yaml(_YAML).get_domain_phases()

        assert phase.asserts == ("^CLOSE: ok$", "^TOKEN_SCOPE: none$")

    def test_a_phase_declaring_none_gets_an_empty_tuple(self) -> None:
        """Not None, and not a missing attribute: every pre-#1085 workflow
        takes this path and must keep meaning "judged on exit code"."""
        (phase,) = WorkflowDefinition.from_yaml(_YAML.split("    asserts:")[0]).get_domain_phases()

        assert phase.asserts == ()


class TestAnUncompilablePatternIsRefusedAtAuthoringTime:
    def test_it_raises_when_the_workflow_is_parsed(self) -> None:
        """`[A-` is a plausible typo in a pattern matching a report line.

        Accepting it would defer the error to the moment the phase's artifacts
        are collected - inside a container, after the tokens are spent, and
        reported as an execution failure that looks like the capability broke
        rather than like the workflow being malformed.
        """
        bad = _YAML.replace("'^CLOSE: ok$'", "'^CLOSE: [A-'")

        with pytest.raises(ValidationError, match="not a valid regular expression"):
            WorkflowDefinition.from_yaml(bad)


class TestTheMatcher:
    def test_it_searches_every_collected_file_not_just_the_first(self) -> None:
        """A phase's output is a directory (#988). Matching only the primary
        deliverable would make a two-file report fail for where it put the
        line rather than for what the line said."""
        require_asserted_output(
            phase_id="exercise",
            assertions=["^CLOSE: ok$"],
            outputs=["nothing here", "CLOSE: ok"],
        )

    def test_an_unmet_pattern_names_itself_and_the_phase(self) -> None:
        with pytest.raises(PhaseAssertionError) as caught:
            require_asserted_output(
                phase_id="exercise",
                assertions=["^CLOSE: ok$", "^ISSUE: [0-9]+$"],
                outputs=["ISSUE: 1084\nCLOSE: FAILED"],
            )

        assert caught.value.unmet == ("^CLOSE: ok$",)
        assert "exercise" in str(caught.value)

    def test_no_assertions_accepts_no_output_at_all(self) -> None:
        require_asserted_output(phase_id="exercise", assertions=[], outputs=[])


class TestThePackagedValidationWorkflowsDeclareTheirCapability:
    """The README says each of these asserts one capability; until #1085 none
    of them could fail. A workflow that quietly loses its `asserts` block goes
    back to being green whatever it reports, and nothing else would notice.
    """

    @pytest.mark.parametrize(
        ("workflow", "expected"),
        [
            ("github-ops", "^CLOSE: ok$"),
            ("skills-injection", "^SENTINEL: VENDORED-SKILL-OK-7f3a91$"),
            ("delegation", "^DELEGATE_RAN: ok$"),
        ],
    )
    def test_it_declares_the_line_that_proves_its_capability(
        self, workflow: str, expected: str
    ) -> None:
        raw = yaml.safe_load((_VALIDATION / workflow / "workflow.yaml").read_text())
        declared = {a for phase in raw["phases"] for a in phase.get("asserts", [])}

        assert expected in declared, (
            f"{workflow} no longer asserts {expected!r}. Its prompt still asks "
            "for the report, so the run looks identical - and passes whatever "
            "the report says (#1085)."
        )
