"""#2227: the phases of `sdlc-implement-v4-precheck` that run the full gates get 1024 pids.

exec-f02a26a13856's verify phase ran `just preflight-agent` and the docs build
side by side; each sizes its worker pool from the HOST's cores (#2163), and
together they used up the 256-pid default. Read here through the real parser
and down to the domain phase the engine provisions from, so a key the parser
dropped would fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_shared.settings.workspace import DEFAULT_WORKSPACE_PIDS_LIMIT

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"

#: Every arm compared with v4-precheck, which must hold the limit equal so the
#: limit is not a second variable between them.
_ARMS = (
    "implement-v3",
    "implement-v4-precheck",
    "implement-v4-precheck-sonnet-fix",
    "implement-v7",
)
_GATE_PHASES = {"implement", "verify", "fix", "reverify", "fix_2", "reverify_2"}
_HEADROOM = 1024


def _pids(arm: str) -> dict[str, int]:
    definition = WorkflowDefinition.from_file(_SDLC / arm / "workflow.yaml")
    return {
        phase.phase_id: phase.resources.pids_limit_or(DEFAULT_WORKSPACE_PIDS_LIMIT)
        for phase in definition.get_domain_phases()
    }


@pytest.mark.parametrize("arm", _ARMS)
def test_every_gate_phase_gets_the_headroom(arm: str) -> None:
    pids = _pids(arm)

    assert {p: pids[p] for p in _GATE_PHASES if p in pids} == dict.fromkeys(
        _GATE_PHASES & pids.keys(), _HEADROOM
    )


def test_v4_precheck_has_every_gate_phase() -> None:
    assert _pids("implement-v4-precheck").keys() >= _GATE_PHASES


@pytest.mark.parametrize("arm", _ARMS)
def test_phases_that_run_no_gates_keep_the_default(arm: str) -> None:
    pids = _pids(arm)

    assert {p: n for p, n in pids.items() if p not in _GATE_PHASES} == dict.fromkeys(
        pids.keys() - _GATE_PHASES, DEFAULT_WORKSPACE_PIDS_LIMIT
    )
