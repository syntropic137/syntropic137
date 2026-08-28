"""YAML round-trip for the new ``claude_plugins:`` field (issue #726).

Phase 4 wired ``claude_plugins`` onto both ``WorkflowDefinition`` and
``PhaseYamlDefinition``. This test treats a representative YAML fixture as
the contract: the fixture declares plugins at workflow scope (string
shorthand + verbose mapping) and at phase scope, and the test asserts that
``WorkflowDefinition.from_yaml`` parses every input form into the expected
``ClaudePluginRef`` shape and that scope assignment survives the round-trip.

Why a fixture-style test in addition to the parser unit tests: the parser
tests cover ``ClaudePluginRef`` in isolation; this one proves the field is
actually wired into the YAML schema at both levels and not silently dropped
by an ``extra="forbid"`` ancestor or a missing field declaration.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    WorkflowDefinition,
)

# WHY: covers all three input forms in one fixture so a regression in any
# parser branch surfaces here without needing per-form fixtures.
_WORKFLOW_YAML_WITH_CLAUDE_PLUGINS = """
id: review-leverage-points
name: Leverage Points Review
type: review
classification: standard

claude_plugins:
  - syntropic137/software-leverage-points@5.0.7
  - source: github.com/obra/superpowers
    version: 2.1.0
    name: superpowers-pinned

phases:
  - id: synthesize
    name: Synthesize
    order: 1
    prompt_template: "do the thing"
    claude_plugins:
      - https://gitlab.com/example/extra.git@1.0.0
"""


@pytest.mark.unit
class TestWorkflowYamlClaudePlugins:
    def test_workflow_scope_parses_shorthand_and_verbose_forms(self) -> None:
        defn = WorkflowDefinition.from_yaml(_WORKFLOW_YAML_WITH_CLAUDE_PLUGINS)

        assert len(defn.claude_plugins) == 2

        shorthand = defn.claude_plugins[0]
        assert shorthand.name == "software-leverage-points"
        assert shorthand.source_url == "https://github.com/syntropic137/software-leverage-points"
        assert shorthand.version == "5.0.7"
        assert shorthand.name_overridden is False

        verbose = defn.claude_plugins[1]
        assert verbose.name == "superpowers-pinned"
        # Bare-host shorthand expands to https:// during normalization.
        assert verbose.source_url == "https://github.com/obra/superpowers"
        assert verbose.version == "2.1.0"
        assert verbose.name_overridden is True

    def test_phase_scope_parses_full_url_form(self) -> None:
        defn = WorkflowDefinition.from_yaml(_WORKFLOW_YAML_WITH_CLAUDE_PLUGINS)

        assert len(defn.phases) == 1
        phase = defn.phases[0]
        assert len(phase.claude_plugins) == 1

        url_form = phase.claude_plugins[0]
        assert url_form.source_url == "https://gitlab.com/example/extra.git"
        assert url_form.version == "1.0.0"
        # Display name comes from the URL basename minus .git suffix.
        assert url_form.name == "extra"

    def test_workflow_without_claude_plugins_defaults_to_empty(self) -> None:
        # WHY: pure additive feature must not break workflows that omit it.
        minimal = """
id: no-plugins
name: No Plugins
type: custom

phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "noop"
"""
        defn = WorkflowDefinition.from_yaml(minimal)
        assert defn.claude_plugins == []
        assert defn.phases[0].claude_plugins == []

    def test_at_latest_is_rejected(self) -> None:
        bad = """
id: bad
name: Bad
type: custom
claude_plugins:
  - org/repo@latest
phases:
  - id: p1
    name: Phase
    order: 1
    prompt_template: "noop"
"""
        with pytest.raises(ValueError, match="latest"):
            WorkflowDefinition.from_yaml(bad)
