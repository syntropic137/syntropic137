"""Fitness function: nothing the platform ships selects a retired Claude model.

Owner directive 2026-10-10: never run Sonnet 4.5 (or anything below the 5
family) again. The runtime refuses one at install, edit, startup and launch
(``syn_shared.agents.resolve_claude_model``); this keeps the shipped defaults
from ever reaching that refusal:

* every ``model`` value in a workflow YAML or phase-prompt frontmatter under
  ``workflows/``, at any depth and in any YAML spelling (a phase's own
  ``model:``, an inline ``fallback_agent: {provider: claude, model: ...}``),
  read from the parsed document rather than its text. Aliases are allowed
  there and are judged by what they resolve to;
* the static claude default and the settings default;
* every ``CLAUDE_MODEL_ALIAS_TARGETS`` target, and the env that pins the CLI's
  own alias lookups for subagents and delegate sessions.

Retired ids still appear in ``ModelId`` and pricing: a past run is displayed
at its own rate. Selection is what is forbidden, not knowledge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from syn_shared.agents import (
    CLAUDE_MODEL_ALIAS_TARGETS,
    CODEX_MODEL_IDS,
    DEFAULT_CLAUDE_MODEL,
    CodexModelAlias,
    claude_model_pin_env,
    is_retired_claude_model,
)

_ROOT = Path(__file__).resolve().parents[3]
_CODEX_MODELS = {str(m) for m in CODEX_MODEL_IDS} | {str(a) for a in CodexModelAlias}


def _resolved(model: str) -> str:
    """The id ``model`` launches as, without the launch-time refusal."""
    for alias, target in CLAUDE_MODEL_ALIAS_TARGETS.items():
        if model.lower() == alias:
            return str(target)
    return model


def _workflow_models() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted((_ROOT / "workflows").rglob("*")):
        if path.suffix in {".yaml", ".yml"}:
            text = path.read_text()
        elif path.suffix == ".md":
            text = _frontmatter(path.read_text())
        else:
            continue
        relative = str(path.relative_to(_ROOT))
        found.extend((relative, model) for model in _model_values(yaml.safe_load(text)))
    return found


def _model_values(node: object) -> list[str]:
    """Every string under a ``model`` key in a parsed YAML document, at any depth."""
    if isinstance(node, dict):
        return [
            value
            for key, child in node.items()
            for value in ([child] if key == "model" and isinstance(child, str) else [])
            + _model_values(child)
        ]
    if isinstance(node, list):
        return [value for child in node for value in _model_values(child)]
    return []


def _frontmatter(text: str) -> str:
    """A phase prompt's YAML frontmatter, where it may declare ``model:``."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


@pytest.mark.architecture
def test_workflow_yaml_selects_no_retired_model() -> None:
    models = _workflow_models()
    assert models, "found no `model:` in workflows/ - the scan is broken"
    offenders = [
        f"{path}: model: {model}"
        for path, model in models
        if model not in _CODEX_MODELS and is_retired_claude_model(_resolved(model))
    ]
    assert not offenders, "workflows select a retired Claude model:\n" + "\n".join(offenders)


@pytest.mark.architecture
def test_defaults_and_alias_targets_are_allowed() -> None:
    from syn_shared.settings.config import Settings

    selected = {
        "DEFAULT_CLAUDE_MODEL": _resolved(DEFAULT_CLAUDE_MODEL),
        "Settings.syn_default_claude_model": _resolved(
            str(Settings.model_fields["syn_default_claude_model"].default)
        ),
        **{f"alias {a}": str(t) for a, t in CLAUDE_MODEL_ALIAS_TARGETS.items()},
        **claude_model_pin_env(),
    }
    retired = {k: v for k, v in selected.items() if is_retired_claude_model(v)}
    assert not retired, f"a default selects a retired Claude model: {retired}"


_INLINE_FALLBACK = """id: inline-fallback
name: Inline fallback
type: research
classification: standard
phases:
  - id: p
    name: P
    order: 1
    prompt_template: Probe
    model: opus
    fallback_agent: {provider: claude, model: claude-sonnet-4-5}
"""


@pytest.mark.architecture
def test_scan_sees_an_inline_retired_model_after_an_allowed_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allowed primary keeps ``assert models`` green, so a scan that read
    only ``model:`` lines would pass this file. It is a real input shape: the
    production parser and converter keep the inline fallback."""
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
    )

    [phase] = WorkflowDefinition.from_yaml(_INLINE_FALLBACK).phases
    fallback = phase.to_domain().fallback_agent
    assert fallback is not None
    assert fallback.model == "claude-sonnet-4-5"

    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "workflow.yaml").write_text(_INLINE_FALLBACK)
    monkeypatch.setattr(sys.modules[__name__], "_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="retired"):
        test_workflow_yaml_selects_no_retired_model()
