"""YAML round-trip for the new ``skills:`` field (issue #772).

Mirrors ``test_workflow_yaml_claude_plugins.py``. ``skills`` rides alongside
``claude_plugins`` at both workflow- and phase-scope. This test treats a
representative YAML fixture as the contract: the fixture declares skills at
workflow scope (three-segment shorthand + verbose mapping with ``names:``)
and at phase scope, and asserts ``WorkflowDefinition.from_yaml`` parses every
input form into the expected ``SkillRef`` shape, that scope assignment
survives the round-trip, and that ``@latest`` is rejected as a parse error.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)

# WHY: covers three-segment shorthand, verbose 'names:' expansion, and
# phase-scope full-URL form in one fixture so a regression in any parser
# branch surfaces here without needing per-form fixtures.
_WORKFLOW_YAML_WITH_SKILLS = """
id: review-leverage-points
name: Leverage Points Review
type: review
classification: standard

skills:
  - syntropic137/agentic-skills/code-review@3.2.1
  - source: github.com/obra/superpowers
    version: 2.1.0
    names:
      - brainstorming
      - test-driven-development

phases:
  - id: synthesize
    name: Synthesize
    order: 1
    prompt_template: "do the thing"
    skills:
      - https://gitlab.com/example/extra-skill.git@1.0.0
"""


@pytest.mark.unit
class TestWorkflowYamlSkills:
    def test_workflow_scope_parses_shorthand_and_names_expansion(self) -> None:
        defn = WorkflowDefinition.from_yaml(_WORKFLOW_YAML_WITH_SKILLS)

        # 1 shorthand + 2 from 'names:' expansion = 3 refs.
        assert len(defn.skills) == 3

        shorthand = defn.skills[0]
        assert shorthand.skill_name == "code-review"
        assert (
            shorthand.source_url == "https://github.com/syntropic137/agentic-skills"
        )
        assert shorthand.version == "3.2.1"
        assert shorthand.name_overridden is False

        expanded_first = defn.skills[1]
        assert expanded_first.skill_name == "brainstorming"
        assert expanded_first.source_url == "https://github.com/obra/superpowers"
        assert expanded_first.version == "2.1.0"
        assert expanded_first.name_overridden is True

        expanded_second = defn.skills[2]
        assert expanded_second.skill_name == "test-driven-development"
        assert expanded_second.source_url == "https://github.com/obra/superpowers"
        assert expanded_second.version == "2.1.0"
        assert expanded_second.name_overridden is True

    def test_phase_scope_parses_full_url_form(self) -> None:
        defn = WorkflowDefinition.from_yaml(_WORKFLOW_YAML_WITH_SKILLS)

        assert len(defn.phases) == 1
        phase = defn.phases[0]
        assert len(phase.skills) == 1

        url_form = phase.skills[0]
        assert url_form.source_url == "https://gitlab.com/example/extra-skill.git"
        assert url_form.version == "1.0.0"
        # Display name comes from the URL basename minus .git suffix.
        assert url_form.skill_name == "extra-skill"

    def test_workflow_and_phase_scope_are_additive_and_dedup_by_identity(self) -> None:
        # WHY: phase-level refs are additive on top of workflow-level refs;
        # the same (source_url, version, skill_name) identity declared at
        # both scopes must not double-count once merged downstream. This
        # test proves the raw YAML lists parse independently and cleanly
        # (the actual merge/dedup happens in the resolution service).
        yaml_content = """
id: additive-test
name: Additive Test
type: custom

skills:
  - syntropic137/agentic-skills/code-review@3.2.1

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "noop"
    skills:
      - syntropic137/agentic-skills/code-review@3.2.1
      - syntropic137/agentic-skills/testing@1.0.0
"""
        defn = WorkflowDefinition.from_yaml(yaml_content)
        assert len(defn.skills) == 1
        assert len(defn.phases[0].skills) == 2

        # Identity equality holds across scopes for the shared ref.
        assert defn.skills[0] == defn.phases[0].skills[0]
        combined = {*defn.skills, *defn.phases[0].skills}
        assert len(combined) == 2

    def test_workflow_without_skills_defaults_to_empty(self) -> None:
        # WHY: pure additive feature must not break workflows that omit it.
        minimal = """
id: no-skills
name: No Skills
type: custom

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "noop"
"""
        defn = WorkflowDefinition.from_yaml(minimal)
        assert defn.skills == []
        assert defn.phases[0].skills == []

    def test_at_latest_is_rejected(self) -> None:
        bad = """
id: bad
name: Bad
type: custom
skills:
  - org/repo/skill@latest
phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "noop"
"""
        with pytest.raises(ValueError, match="latest"):
            WorkflowDefinition.from_yaml(bad)
