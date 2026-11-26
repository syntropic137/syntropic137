"""The installed SDLC workflows give their gate phases 1024 pids (#2227).

A verify phase running ``just preflight-agent`` beside a docs build forked past
the 256-process default, and codex died with "stream ended without a terminal
turn.completed event" (exec-f02a26a13856, exec-36d5ae88e41e). Every phase that
runs the repository's gates asks for the shipped ceiling instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

#: The SDLC workflows installed on the deployment (#2227).
_INSTALLED = (
    "implement-v3",
    "implement-v4-precheck",
    "implement-v4-precheck-sonnet-fix",
    "implement-v7",
    "reverify-pr",
)

#: Phases that run the verification gates or build the change.
_GATE_PHASES = frozenset({"implement", "verify", "fix", "reverify", "fix_2", "reverify_2"})

#: The deployment's default pids ceiling (``SYN_WORKSPACE_PIDS_MAX`` unset):
#: a request above it is refused at install, so the workflows ask for exactly it.
_CEILING = 1024


def _definition(name: str) -> WorkflowDefinition:
    return WorkflowDefinition.from_yaml((_ROOT / "workflows/sdlc" / name / "workflow.yaml").read_text())


@pytest.mark.parametrize("name", _INSTALLED)
def test_every_gate_phase_asks_for_the_ceiling(name: str) -> None:
    gate = [p for p in _definition(name).phases if p.id in _GATE_PHASES]
    assert gate, f"{name} has no gate phases"
    for phase in gate:
        assert phase.resources.pids_limit == _CEILING, (name, phase.id, phase.resources.pids_limit)


@pytest.mark.parametrize("name", _INSTALLED)
def test_other_phases_keep_the_default(name: str) -> None:
    for phase in _definition(name).phases:
        if phase.id not in _GATE_PHASES:
            assert phase.resources.pids_limit is None, (name, phase.id)
