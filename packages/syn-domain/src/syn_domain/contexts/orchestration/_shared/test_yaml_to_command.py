"""Tests for the shared yaml → CreateWorkflowTemplateCommand builder.

These tests used to live in ``seed_workflow/test_seeder.py`` against the
seeder-private ``_build_create_command`` / ``_infer_requires_repos``
helpers. They moved here with the extraction of the shared module
(``yaml_to_command``) so both the seeder and the HTTP upload endpoint
exercise the same code path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
    infer_requires_repos,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    WorkflowClassification,
    WorkflowType,
)


def _minimal_definition(**overrides: object) -> WorkflowDefinition:
    data: Mapping[str, object] = {
        "id": "wf-1",
        "name": "Test",
        "phases": [{"id": "p-1", "name": "Phase 1", "order": 1}],
        **overrides,
    }
    return WorkflowDefinition.model_validate(data)


@pytest.mark.unit
class TestBuildCommandFromDefinition:
    def test_builds_command_from_definition_with_repository(self) -> None:
        definition = _minimal_definition(
            type="research",
            classification="simple",
            repository={"url": "https://github.com/test/repo", "ref": "main"},
        )
        cmd = build_command_from_definition(definition)
        assert cmd.aggregate_id == "wf-1"
        assert cmd.name == "Test"
        assert cmd.workflow_type == WorkflowType.RESEARCH
        assert cmd.classification == WorkflowClassification.SIMPLE
        assert cmd.repository_url == "https://github.com/test/repo"
        assert cmd.repository_ref == "main"
        assert cmd.requires_repos is True

    def test_uses_empty_url_without_repository(self) -> None:
        definition = _minimal_definition(name="No Repo")
        cmd = build_command_from_definition(definition)
        assert cmd.repository_url == ""
        assert cmd.repository_ref == "main"
        # Default is opt-out: workflows without explicit requires_repos still
        # require -R at runtime. Research/no-repo workflows must opt out.
        assert cmd.requires_repos is True

    def test_unknown_type_falls_back_to_custom(self) -> None:
        definition = _minimal_definition(type="not-a-real-type")
        cmd = build_command_from_definition(definition)
        assert cmd.workflow_type == WorkflowType.CUSTOM

    def test_overrides_apply_over_yaml_identity(self) -> None:
        definition = _minimal_definition(name="Original")
        cmd = build_command_from_definition(
            definition,
            workflow_id_override="override-id",
            name_override="Override Name",
        )
        assert cmd.aggregate_id == "override-id"
        assert cmd.name == "Override Name"

    def test_roundtrips_description_and_project_name(self) -> None:
        definition = _minimal_definition(
            description="A test workflow",
            project_name="alpha",
        )
        cmd = build_command_from_definition(definition)
        assert cmd.description == "A test workflow"
        assert cmd.project_name == "alpha"

    def test_roundtrips_input_declarations(self) -> None:
        definition = _minimal_definition(
            inputs=[
                {"name": "repo", "description": "target repo", "required": True},
                {"name": "branch", "required": False, "default": "main"},
            ],
        )
        cmd = build_command_from_definition(definition)
        assert len(cmd.input_declarations) == 2
        assert cmd.input_declarations[0].name == "repo"
        assert cmd.input_declarations[1].default == "main"


@pytest.mark.unit
class TestInferRequiresRepos:
    """ADR-058 #666 (v0.25.2): explicit value wins; otherwise default True (opt-out)."""

    def test_explicit_true_overrides_no_repo(self) -> None:
        definition = _minimal_definition(requires_repos=True)
        assert infer_requires_repos(definition) is True

    def test_explicit_false_overrides_repo_present(self) -> None:
        definition = _minimal_definition(
            repository={"url": "https://github.com/test/repo", "ref": "main"},
            requires_repos=False,
        )
        assert infer_requires_repos(definition) is False

    def test_default_true_when_no_repository_and_no_explicit_value(self) -> None:
        """v0.25.2: default is opt-out - workflows require -R unless they say otherwise."""
        definition = _minimal_definition()
        assert infer_requires_repos(definition) is True

    def test_default_true_when_repository_present(self) -> None:
        definition = _minimal_definition(
            repository={"url": "https://github.com/test/repo", "ref": "main"},
        )
        assert infer_requires_repos(definition) is True
