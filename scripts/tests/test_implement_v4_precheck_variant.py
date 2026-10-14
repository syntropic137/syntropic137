"""`sdlc-implement-v4-precheck` is sdlc-implement-v3 with ONE change (an A/B arm).

The change is an evidence precheck at the start of verify and every reverify.
It classifies what a workspace cannot fix (FLAKE/INFRA, ORCHESTRATOR_EVIDENCE,
CI_GAP) and hands it to `finalize_pr` instead of spending a repair round on it.
The preregistration is `workflows/sdlc/implement-v4-precheck/EXPERIMENT.md`.

An A/B is only readable if the arms differ in the one variable, so these tests
pin that, reading the definitions as `POST /workflows` installs them:

- everything but the identity and four prompts is v3's, field for field;
- the precheck is ONE text, identical in every review phase that carries it;
- every other line that differs from v3 is about the precheck;
- the safety property holds: a handoff never reaches `gh pr ready`, and only a
  REPAIRABLE item can make a review BLOCKED and so spend a round.

The engine half (two bounded rounds, certified skips to `finalize_pr`) is
covered by registering this id in test_implement_v3_repair_rounds.py.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"
_V3 = _SDLC / "implement-v3" / "workflow.yaml"
_V4 = _SDLC / "implement-v4-precheck" / "workflow.yaml"

#: The phases whose prompts the treatment changes; every other prompt is v3's.
_REVIEWS = ("verify", "reverify", "reverify_2")
_CHANGED = (*_REVIEWS, "finalize_pr")

_PRECHECK = "## Evidence precheck: classify before you block"

#: Words that only the precheck introduces. A changed hunk naming none of them
#: is a second variable.
_PRECHECK_TERMS = (
    "REPAIRABLE",
    "FLAKE/INFRA",
    "ORCHESTRATOR_EVIDENCE",
    "CI_GAP",
    "Precheck:",
    "handoff",
    "Handed to the orchestrator",
)


def _load(path: Path) -> WorkflowDefinition:
    return WorkflowDefinition.from_file(path)


def _prompts(path: Path) -> dict[str, str]:
    return {p.id: p.prompt_template or "" for p in _load(path).phases}


def _section(text: str, heading: str) -> str:
    start = text.index(f"{heading}\n")
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end >= 0 else len(text)]


def _without_precheck(text: str) -> str:
    # The section plus the newline that closed it, so no blank line is left behind.
    section = _section(text, _PRECHECK)
    return text.replace(section + "\n", "", 1)


def test_the_arm_differs_from_v3_only_in_its_identity_and_four_prompts() -> None:
    v3, v4 = _load(_V3), _load(_V4)
    assert (v3.id, v4.id) == ("sdlc-implement-v3", "sdlc-implement-v4-precheck")

    identity = {"id", "name", "description"}
    assert v3.model_dump(exclude=identity | {"phases"}) == v4.model_dump(
        exclude=identity | {"phases"}
    )
    assert [p.id for p in v3.phases] == [p.id for p in v4.phases]
    for old, new in zip(v3.phases, v4.phases, strict=True):
        drop = {"prompt_template"} if old.id in _CHANGED else set()
        assert old.model_dump(exclude=drop) == new.model_dump(exclude=drop), (
            f"phase {old.id} differs from v3 in more than its prompt"
        )


@pytest.mark.parametrize("phase", _CHANGED)
def test_the_treatment_actually_changed_each_prompt_it_claims(phase: str) -> None:
    assert _prompts(_V3)[phase] != _prompts(_V4)[phase]


def test_the_precheck_is_one_text_in_every_review_phase() -> None:
    prompts = _prompts(_V4)
    sections = {phase: _section(prompts[phase], _PRECHECK) for phase in _REVIEWS}
    assert len(set(sections.values())) == 1, "the precheck copies have drifted apart"
    assert _PRECHECK not in _prompts(_V3)["verify"], "v3 must stay the untreated baseline"


@pytest.mark.parametrize("phase", _CHANGED)
def test_every_other_difference_from_v3_is_about_the_precheck(phase: str) -> None:
    old = _prompts(_V3)[phase].splitlines()
    new = _prompts(_V4)[phase]
    new_lines = (_without_precheck(new) if _PRECHECK in new else new).splitlines()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
        a=old, b=new_lines, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        hunk = "\n".join(new_lines[max(0, j1 - 1) : j2 + 1])
        assert any(term in hunk for term in _PRECHECK_TERMS), (
            f"{phase}: a change unrelated to the precheck:\n{hunk}"
        )


class TestOnlyARepairableItemSpendsARound:
    """The precheck's whole claim: a handoff is never a repair round, and never READY."""

    def test_the_verdict_is_blocked_only_for_a_repairable_item(self) -> None:
        precheck = " ".join(_section(_prompts(_V4)["verify"], _PRECHECK).split())
        assert (
            "Your verdict is `blocked` if and only if at least one `REPAIRABLE` item is open"
            in (precheck)
        )
        assert "When every open item is a handoff, the verdict is `certified`" in precheck
        # Unprovable classification falls to the safe side, not to a handoff.
        assert "A class whose required evidence (below) you cannot show is `REPAIRABLE`" in (
            precheck
        )

    def test_each_handoff_class_is_marked_never_a_round(self) -> None:
        table = _section(_prompts(_V4)["verify"], _PRECHECK)
        rows = {
            m.group(1): m.group(2)
            for m in re.finditer(r"^\| `([A-Z_/]+)` \|.*\| ([^|]+) \|$", table, re.M)
        }
        assert set(rows) == {"REPAIRABLE", "FLAKE/INFRA", "ORCHESTRATOR_EVIDENCE", "CI_GAP"}
        assert rows.pop("REPAIRABLE").startswith("yes")
        assert all(cell.strip() == "never" for cell in rows.values()), rows

    def test_a_certified_run_with_an_open_handoff_is_never_marked_ready(self) -> None:
        finalize = _prompts(_V4)["finalize_pr"]
        handoff = _section(finalize, "## If CERTIFIED and a handoff is open")
        verbs = set(re.findall(r"`gh pr (\w+)", handoff))
        assert "comment" in verbs, "the handoffs must be posted where a person sees them"
        assert not verbs & {"ready", "merge", "close"}, verbs
        # The plain CERTIFIED path, which does mark ready, must route here first.
        certified = " ".join(_section(finalize, "## If CERTIFIED").split())
        assert "Follow this section only when no handoff is open" in certified

    def test_a_report_that_is_silent_about_handoffs_counts_as_open(self) -> None:
        # Otherwise a verifier that skipped the precheck certifies to READY.
        rule = " ".join(_section(_prompts(_V4)["finalize_pr"], "## Read the handoffs").split())
        assert "or when the final report has no `## Handed to the orchestrator` section" in rule

    def test_the_metric_line_each_review_writes_is_the_one_finalize_copies(self) -> None:
        line = re.compile(
            r"Precheck: REPAIRABLE=<n> FLAKE_INFRA=<n> ORCHESTRATOR_EVIDENCE=<n> CI_GAP=<n>"
        )
        for phase in _REVIEWS:
            assert line.search(_prompts(_V4)[phase]), phase
        assert "the final report's `Precheck:` line copied verbatim" in " ".join(
            _prompts(_V4)["finalize_pr"].split()
        )
