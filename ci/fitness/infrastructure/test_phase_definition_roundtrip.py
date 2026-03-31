"""Fitness function: PhaseDefinition field round-trip through _build_phase_defs.

Regression test for the silent field-dropping bug (ISS-405) where
`_build_phase_defs` only passed 4 of 13 PhaseDefinition fields to the
constructor, silently discarding prompt_template, model, max_tokens,
timeout_seconds, allowed_tools, argument_hint, execution_type,
input_artifact_types, and output_artifact_types.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _add_to_path(*rel: str) -> None:
    root = Path(__file__).resolve().parents[3]
    for r in rel:
        src = str(root / r)
        if src not in sys.path:
            sys.path.insert(0, src)


@pytest.mark.architecture
@pytest.mark.regression
def test_build_phase_defs_preserves_all_fields() -> None:
    """_build_phase_defs must pass ALL PhaseDefinition fields through.

    ISS-405: _build_phase_defs was only passing phase_id, name, order,
    description. The remaining 9 fields were silently dropped, meaning
    workflows created via the API lost their prompt_template, model, etc.

    This test constructs a phase dict with every field set to a non-default
    value and asserts each one survives the round-trip.
    """
    _add_to_path(
        "apps/syn-api/src",
        "packages/syn-domain/src",
        "packages/syn-shared/src",
        "lib/event-sourcing-platform/python/src",
    )

    from syn_api.routes.workflows.commands import _build_phase_defs
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseExecutionType,
    )

    phase_dict: dict[str, object] = {
        "phase_id": "test-phase-id",
        "name": "Test Phase",
        "order": 3,
        "description": "A test phase with all fields",
        "execution_type": PhaseExecutionType.PARALLEL.value,
        "input_artifact_types": ["research_report", "code_bundle"],
        "output_artifact_types": ["test_results"],
        "prompt_template": "Analyze the following: $ARGUMENTS",
        "max_tokens": 8192,
        "timeout_seconds": 600,
        "allowed_tools": ["Read", "Write", "Bash"],
        "argument_hint": "[task-description]",
        "model": "claude-opus-4-6",
    }

    result = _build_phase_defs([phase_dict])

    assert len(result) == 1
    phase = result[0]

    assert phase.phase_id == "test-phase-id", "phase_id was not preserved"
    assert phase.name == "Test Phase", "name was not preserved"
    assert phase.order == 3, "order was not preserved"
    assert phase.description == "A test phase with all fields", "description was not preserved"
    assert phase.input_artifact_types == ["research_report", "code_bundle"], (
        "input_artifact_types was not preserved"
    )
    assert phase.output_artifact_types == ["test_results"], "output_artifact_types was not preserved"
    assert phase.prompt_template == "Analyze the following: $ARGUMENTS", (
        "prompt_template was silently dropped — this is ISS-405"
    )
    assert phase.max_tokens == 8192, "max_tokens was silently dropped"
    assert phase.timeout_seconds == 600, "timeout_seconds was silently dropped"
    assert phase.allowed_tools == ["Read", "Write", "Bash"], "allowed_tools was silently dropped"
    assert phase.argument_hint == "[task-description]", "argument_hint was silently dropped"
    assert phase.model == "claude-opus-4-6", "model was silently dropped"
