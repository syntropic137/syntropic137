"""`sdlc-implement-v6` is sdlc-implement-v4-precheck plus two added sections (an A/B arm, #2060).

The first is evidence declarations and capability gaps: reviews and fix rounds
name the capability a workspace lacked instead of spending or refusing a round,
integration and mutation evidence is declared in `TASK_RESULT.evidence` for the
platform evidence gate, and `finalize_pr` reads the gate's manifest. The second
(PC-241, found by v5's live check) is that only a check the base branch requires
can hold a certified PR in draft. The preregistration is
`workflows/sdlc/implement-v6/EXPERIMENT.md`.

An A/B is only readable if the arms differ in the one variable, so these tests
pin that, reading the definitions as `POST /workflows` installs them:

- everything but the identity and seven prompts is v4-precheck's, field for field;
- each added section is ONE text, identical in every phase that carries it,
  and removing the added sections gives back v4-precheck's prompt exactly;
- the evidence entry the prompts show is one the platform's parser accepts,
  and the parser refuses the `capability` key the prompts tell agents to leave out;
- finalize never marks a PR ready from a manifest that is not complete and passed.

These are prompt-structure checks. They pin what the prompts say; they cannot
show an agent obeys them. That is what the A/B's mechanism check measures.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.evidence_contract import EvidenceRequest
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
    declared_evidence_from_reported,
)

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"
_V4 = _SDLC / "implement-v4-precheck" / "workflow.yaml"
_V6 = _SDLC / "implement-v6" / "workflow.yaml"

_REVIEWS = ("verify", "reverify", "reverify_2")
_FIXES = ("fix", "fix_2")
_CHANGED = (*_REVIEWS, *_FIXES, "implement", "finalize_pr")

_REVIEW_SECTION = "## Capability gaps and declared evidence"
_FIX_SECTION = "## Capability gaps: report them and stop, never refuse after the work"
_IMPLEMENT_SECTION = "## Declare the mutation evidence you commit"
_FINALIZE_SECTION = "## Read the platform evidence and the capability gaps"
_REQUIRED_REVIEW_SECTION = "## Only a check the base branch requires can hold this PR"
_REQUIRED_FINALIZE_SECTION = "## Only a required check holds the PR in draft"

#: The closed list the orchestrator routes on. Every phase must name the same set.
_CAPABILITIES = ("nested_docker", "database", "event_store", "live_api", "other")

#: Words only the v6 change introduces. A changed finalize hunk naming none of
#: them is a second variable.
_V6_TERMS = (
    "platform evidence",
    "Platform evidence",
    "manifest",
    "Capability gaps",
    "capability",
    "Needs a capable workspace",
    "patch_removal",
    "Required checks",
    "required on the base branch",
    "Not required, not holding",
)


def _load(path: Path) -> WorkflowDefinition:
    return WorkflowDefinition.from_file(path)


def _prompts(path: Path) -> dict[str, str]:
    return {p.id: p.prompt_template or "" for p in _load(path).phases}


def _section(text: str, heading: str) -> str:
    start = text.index(f"{heading}\n")
    end = text.find("\n## ", start + len(heading))
    return text[start : end + 1 if end >= 0 else len(text)]


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_arm_differs_from_v4_only_in_its_identity_and_seven_prompts() -> None:
    v4, v6 = _load(_V4), _load(_V6)
    assert (v4.id, v6.id) == ("sdlc-implement-v4-precheck", "sdlc-implement-v6")

    identity = {"id", "name", "description"}
    assert v4.model_dump(exclude=identity | {"phases"}) == v6.model_dump(
        exclude=identity | {"phases"}
    )
    assert [p.id for p in v4.phases] == [p.id for p in v6.phases]
    for old, new in zip(v4.phases, v6.phases, strict=True):
        drop = {"prompt_template"} if old.id in _CHANGED else set()
        assert old.model_dump(exclude=drop) == new.model_dump(exclude=drop), (
            f"phase {old.id} differs from v4-precheck in more than its prompt"
        )


@pytest.mark.parametrize("phase", _CHANGED)
def test_the_treatment_actually_changed_each_prompt_it_claims(phase: str) -> None:
    assert _prompts(_V4)[phase] != _prompts(_V6)[phase]


@pytest.mark.parametrize(
    ("phases", "heading"),
    [
        (_REVIEWS, _REVIEW_SECTION),
        (_FIXES, _FIX_SECTION),
        (_REVIEWS, _REQUIRED_REVIEW_SECTION),
    ],
    ids=["reviews", "fixes", "required-checks"],
)
def test_each_added_section_is_one_text_wherever_it_appears(
    phases: tuple[str, ...], heading: str
) -> None:
    prompts = _prompts(_V6)
    assert len({_section(prompts[p], heading) for p in phases}) == 1, (
        f"the copies of {heading!r} have drifted apart"
    )
    assert heading not in _prompts(_V4)[phases[0]], "v4-precheck must stay the baseline"


@pytest.mark.parametrize(
    ("phase", "heading"),
    [
        *((p, (_REQUIRED_REVIEW_SECTION, _REVIEW_SECTION)) for p in _REVIEWS),
        *((p, (_FIX_SECTION,)) for p in _FIXES),
        ("implement", (_IMPLEMENT_SECTION,)),
    ],
)
def test_removing_the_added_sections_gives_back_v4_exactly(
    phase: str, heading: tuple[str, ...]
) -> None:
    v6 = _prompts(_V6)[phase]
    for one in heading:
        v6 = v6.replace(_section(v6, one), "", 1)
    assert v6 == _prompts(_V4)[phase]


def test_every_finalize_difference_from_v4_is_about_the_v5_change() -> None:
    old = _prompts(_V4)["finalize_pr"].splitlines()
    new = _prompts(_V6)["finalize_pr"].splitlines()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
        a=old, b=new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        hunk = "\n".join(new[max(0, j1 - 1) : j2 + 1])
        assert any(term in hunk for term in _V6_TERMS), (
            f"finalize_pr: a change unrelated to v6:\n{hunk}"
        )


@pytest.mark.parametrize("phase", (*_REVIEWS, *_FIXES))
def test_every_phase_names_the_same_closed_capability_list(phase: str) -> None:
    heading = _REVIEW_SECTION if phase in _REVIEWS else _FIX_SECTION
    named = re.findall(r"`([a-z_]+)`", _section(_prompts(_V6)[phase], heading))
    assert [c for c in named if c in _CAPABILITIES] and set(_CAPABILITIES) <= set(named)


_EXAMPLE = re.compile(r'"evidence": (\[\{.*?\}\])', re.S)


def _concrete(example: str) -> object:
    """The prompt's example entry with each placeholder filled as an agent would."""
    filled = (
        example.replace('"<owner>/<name>"', '"syntropic137/syntropic137"')
        .replace('"<branch>"', '"feat/x"')
        .replace("<number>", "12")
        .replace('"<the full SHA you checked out>"', '"' + "a" * 40 + '"')
        .replace('"<the full SHA you pushed>"', '"' + "a" * 40 + '"')
    )
    return json.loads(filled)


@pytest.mark.parametrize(
    ("phase", "heading"),
    [
        ("verify", _REVIEW_SECTION),
        ("fix", _FIX_SECTION),
        ("implement", _IMPLEMENT_SECTION),
    ],
)
def test_the_example_entry_is_one_the_platform_accepts(phase: str, heading: str) -> None:
    section = _section(_prompts(_V6)[phase], heading)
    match = _EXAMPLE.search(section)
    assert match, f"{phase} shows no evidence entry"
    declared = declared_evidence_from_reported(_concrete(match.group(1)))
    assert len(declared) == 1
    assert declared[0].request is not None, declared[0]


def _review_example() -> str:
    match = _EXAMPLE.search(_section(_prompts(_V6)["verify"], _REVIEW_SECTION))
    assert match, "verify shows no evidence entry"
    return match.group(1)


def test_the_keys_the_prompts_promise_are_the_contracts_keys() -> None:
    entry = _concrete(_review_example())
    assert isinstance(entry, list) and len(entry) == 1
    assert set(entry[0]) == set(EvidenceRequest.model_fields)
    assert "Use exactly these six keys" in _section(_prompts(_V6)["verify"], _REVIEW_SECTION)
    assert len(EvidenceRequest.model_fields) == 6


def test_a_capability_key_on_an_entry_is_refused_as_the_prompt_says() -> None:
    with_capability = _review_example().replace("}]", ', "capability": "nested_docker"}]')
    declared = declared_evidence_from_reported(_concrete(with_capability))
    assert len(declared) == 1
    assert declared[0].request is None


class TestFinalizeTrustsOnlyACompletePassedManifest:
    def test_a_manifest_closes_rows_only_when_complete_and_every_step_passed(self) -> None:
        rule = _flat(_section(_prompts(_V6)["finalize_pr"], _FINALIZE_SECTION))
        assert (
            "`complete` is `true`, every step settled `passed`, and the `required_check` step passed on the branch head"
            in rule
        )
        assert "Anything else (a step `failed`, `void` or `unavailable`) leaves them open" in rule
        assert "and only those" in rule

    def test_an_open_handoff_still_never_reaches_gh_pr_ready(self) -> None:
        finalize = _prompts(_V6)["finalize_pr"]
        handoff = _flat(_section(finalize, "## If CERTIFIED and a handoff is open"))
        assert "Keep it a **draft**: never call `gh pr ready` here." in handoff
        assert "Needs a capable workspace" in handoff
        certified = _flat(_section(finalize, "## If CERTIFIED"))
        assert "Follow this section only when no handoff is open" in certified

    def test_the_head_exception_is_only_the_recorded_patch_removal(self) -> None:
        head = _flat(_section(_prompts(_V6)["finalize_pr"], "## Check the head"))
        assert "`patch_removal.after_sha` whose `before_sha` is the certified SHA" in head

    def test_the_count_line_each_review_writes_is_the_one_finalize_copies(self) -> None:
        line = (
            "Capability gaps: nested_docker=<n> database=<n> event_store=<n> live_api=<n> other=<n>"
        )
        for phase in _REVIEWS:
            assert line in _prompts(_V6)[phase], phase
        assert "its `Capability gaps:` line copied verbatim" in _flat(_prompts(_V6)["finalize_pr"])


class TestOnlyARequiredCheckHoldsACertifiedPrInDraft:
    """PC-241: certified PR #2080 stayed draft on two non-required Vercel statuses."""

    _RULES = "rules/branches/<base>"

    def test_finalize_holds_only_on_a_required_check(self) -> None:
        rule = _flat(_section(_prompts(_V6)["finalize_pr"], _REQUIRED_FINALIZE_SECTION))
        assert (
            "A `FLAKE/INFRA` handoff holds a certified PR in draft only when its check is required on the base branch"
            in rule
        )
        assert "whose check is **not required** is not open" in rule
        assert "It does not keep the PR a draft and gets no rerun" in rule
        assert self._RULES in rule and "required_status_checks" in rule

    def test_finalize_falls_back_to_holding_when_the_required_set_is_unreadable(self) -> None:
        rule = _flat(_section(_prompts(_V6)["finalize_pr"], _REQUIRED_FINALIZE_SECTION))
        assert "keep every `FLAKE/INFRA` row open" in rule
        assert "`Required checks: unreadable`" in rule

    @pytest.mark.parametrize("phase", _REVIEWS)
    def test_a_review_parks_a_non_required_outside_failure_and_still_blocks_its_own(
        self, phase: str
    ) -> None:
        rule = _flat(_section(_prompts(_V6)[phase], _REQUIRED_REVIEW_SECTION))
        assert "not a handoff and not a blocker" in rule
        assert "### Not required, not holding" in rule
        assert "fails because of this diff** is still `REPAIRABLE`" in rule
        assert "treat every check as required" in rule
        assert self._RULES in rule

    def test_the_required_section_comes_before_the_capability_section(self) -> None:
        for phase in _REVIEWS:
            text = _prompts(_V6)[phase]
            assert text.index(_REQUIRED_REVIEW_SECTION) < text.index(_REVIEW_SECTION), phase
