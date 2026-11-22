"""`sdlc-implement-v4-precheck-sonnet-fix` is E3's treatment arm (an A/B arm).

It was cut from `sdlc-implement-v4-precheck` at 995b40fd7 with ONE change:
`fix` and `fix_2` run on Sonnet 5.5 instead of Opus 5.5. The preregistration
is `docs/experiments/2026-10-17-fix-phase-sonnet.md`.

The arm already ran on the deployment, and a workflow id is immutable once it
has run, so its prompts stay what ran. v4-precheck has since gained the #2028
`.mutations/` protections (1c6e058b4, 54a2cfd89) in six prompts. These tests
pin both facts against today's v4-precheck, because CI checks out one commit
and cannot `git show` the cut:

- everything but the identity and the two fix models is v4-precheck's;
- every prompt line the arm has, v4-precheck has, in order;
- every block v4-precheck has that the arm lacks is about mutation evidence.

A later v4-precheck edit that is not about mutations fails here, which is the
point: it is a second difference between the arms that E3 never measured.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"
_V4 = _SDLC / "implement-v4-precheck" / "workflow.yaml"
_ARM = _SDLC / "implement-v4-precheck-sonnet-fix" / "workflow.yaml"

_FIX_PHASES = ("fix", "fix_2")
_ARM_FIX_MODEL = "claude-sonnet-5-5"


def _load(path: Path) -> WorkflowDefinition:
    return WorkflowDefinition.from_file(path)


def test_the_arm_differs_from_v4_precheck_only_in_identity_and_fix_models() -> None:
    v4, arm = _load(_V4), _load(_ARM)
    assert arm.id == "sdlc-implement-v4-precheck-sonnet-fix"

    identity = {"id", "name", "description"}
    assert v4.model_dump(exclude=identity | {"phases"}) == arm.model_dump(
        exclude=identity | {"phases"}
    )
    assert [p.id for p in v4.phases] == [p.id for p in arm.phases]
    for base, treated in zip(v4.phases, arm.phases, strict=True):
        exclude: dict[str, bool | set[str]] = {"prompt_template": True}
        if base.id in _FIX_PHASES:
            exclude["agent"] = {"model"}
            assert treated.agent is not None and base.agent is not None
            assert treated.agent.model == _ARM_FIX_MODEL, f"{base.id} is not on Sonnet 5.5"
            assert base.agent.model != _ARM_FIX_MODEL, "the control must not share the treatment"
        assert base.model_dump(exclude=exclude) == treated.model_dump(exclude=exclude), (
            f"phase {base.id} differs from v4-precheck in more than its prompt"
        )


@pytest.mark.parametrize("phase", [p.id for p in _load(_V4).phases])
def test_the_arm_prompt_is_v4_precheck_minus_only_the_mutation_protections(phase: str) -> None:
    base = {p.id: p.prompt_template or "" for p in _load(_V4).phases}[phase].splitlines()
    arm = {p.id: p.prompt_template or "" for p in _load(_ARM).phases}[phase].splitlines()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=arm, b=base, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        assert tag == "insert", (
            f"{phase}: the arm has text v4-precheck lacks ({tag} arm {i1}:{i2} vs base {j1}:{j2})"
        )
        block = "\n".join(base[j1:j2])
        if not block.strip():
            continue
        assert "mutation" in block.lower(), (
            f"{phase}: v4-precheck gained a non-mutation change E3 never measured:\n{block}"
        )


def test_the_description_names_the_cut_and_the_missing_protections() -> None:
    description = _load(_ARM).description or ""
    assert "995b40fd7" in description
    assert ".mutations" in description
