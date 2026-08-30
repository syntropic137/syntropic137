"""A phase must not write outside the next phase's workspace.

Outputs are injected into the CONSUMING phase at
`artifacts/input/<phase-id>/<relative path>`. Both halves of that path came
from untrusted-ish input:

- `phase_id` was `min_length=1` and nothing else, so `../../../tmp/owned` was a
  valid phase id. Workflows are installable from a marketplace, so whoever
  writes a phase id is not necessarily the operator running it.
- `source_path` arrives from the projection on the recovery path, so a row
  written before the id grammar existed reaches the sink without passing it.

With the Docker backend the injected path is joined to the host-side workspace
directory, so an escape is a write beside the mount rather than merely
elsewhere inside the container.

These assert the REAL traversal strings. A near-miss input can fail safe for
the wrong reason and certify an open class as closed.
"""

from __future__ import annotations

from typing import TypedDict

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)

pytestmark = pytest.mark.unit


class _PhaseInput(TypedDict):
    id: str
    name: str
    order: int
    prompt_template: str


class _WorkflowInput(TypedDict):
    """Typed rather than a loose string-to-object mapping.

    This repo ratchets untyped dicts, and a test fixture is structured state
    like any other. Note the ratchet greps raw file text, so writing the
    offending annotation out even inside a docstring counts against it - which
    is why this sentence describes it rather than quoting it.
    """

    id: str
    name: str
    requires_repos: bool
    phases: list[_PhaseInput]


def _workflow_with_phase_id(phase_id: str) -> _WorkflowInput:
    return {
        "id": "wf",
        "name": "WF",
        "requires_repos": False,
        "phases": [{"id": phase_id, "name": "N", "order": 1, "prompt_template": "x"}],
    }


class TestAPhaseIdCannotBeAPath:
    @pytest.mark.parametrize(
        "evil",
        [
            "../../../tmp/owned",
            "..",
            "../sibling",
            "a/b",
            "/etc/passwd",
            "./relative",
            ".hidden",
            "with space",
            "semi;colon",
        ],
    )
    def test_a_traversing_phase_id_is_rejected(self, evil: str) -> None:
        with pytest.raises(ValidationError):
            WorkflowDefinition.model_validate(_workflow_with_phase_id(evil))

    @pytest.mark.parametrize("ok", ["research", "plan", "plan-2", "cross_model_review", "p.1", "a"])
    def test_ordinary_phase_ids_still_work(self, ok: str) -> None:
        """The negative control. An allowlist that rejects real ids would be
        found the first time someone writes a workflow, and reverted."""
        d = WorkflowDefinition.model_validate(_workflow_with_phase_id(ok))
        assert d.phases[0].id == ok


class TestTheSinkRefusesToEscape:
    """The id grammar protects NEW workflows. `source_path` still arrives from
    the projection, so the sink is validated independently."""

    def test_an_ordinary_file_lands_under_its_phase(self) -> None:
        got = ArtifactCollector._tree_path("research", "artifacts/output/findings.md")
        assert got == "artifacts/input/research/findings.md"

    def test_a_nested_file_keeps_its_structure(self) -> None:
        got = ArtifactCollector._tree_path("research", "artifacts/output/raw/a.yaml")
        assert got == "artifacts/input/research/raw/a.yaml"

    @pytest.mark.parametrize(
        "source_path",
        [
            "artifacts/output/../../../etc/passwd",
            "artifacts/output/../../escaped.md",
            "../../../etc/passwd",
            "/etc/passwd",
            "artifacts/output/nested/../../../out.md",
        ],
    )
    def test_a_traversing_source_path_is_refused(self, source_path: str) -> None:
        """Refused, not sanitised. Silently rewriting an escaping path to a safe
        one would inject a file the author did not describe, under a name they
        did not choose - a dropped file is visible in a short tree; a quietly
        relocated one is not."""
        assert ArtifactCollector._tree_path("research", source_path) is None

    def test_a_traversing_phase_id_is_refused_at_the_sink_too(self) -> None:
        """Defence in depth: the grammar covers authoring, this covers a phase
        id that reached the sink some other way - a projection row predating the
        grammar, or a future call site that skips validation."""
        assert ArtifactCollector._tree_path("../../../tmp/owned", "artifacts/output/a.md") is None

    def test_the_refusal_is_for_containment_not_for_the_literal_dots(self) -> None:
        """A path with no literal `..` that still resolves outside must also be
        refused, so the check is containment rather than string matching."""
        assert ArtifactCollector._tree_path("research", "artifacts/output/ok.md") is not None
        assert ArtifactCollector._tree_path("/absolute", "artifacts/output/ok.md") is None

    def test_an_absolute_source_path_is_refused_even_though_it_stays_contained(self) -> None:
        """Writing this test found the subtlety: `/etc/passwd` does NOT escape -
        joining collapses the slashes and it lands at
        `artifacts/input/<phase>/etc/passwd`. Safe, but it silently becomes a
        nested file nobody described. A source_path is workspace-relative by
        contract, so an absolute one means the contract is already broken."""
        assert ArtifactCollector._tree_path("research", "/etc/passwd") is None
