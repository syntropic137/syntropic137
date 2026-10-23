"""`sdlc-implement-v7` is sdlc-implement-v4-precheck plus two added sections (an A/B arm, #2060).

The first is evidence declarations and capability gaps: reviews and fix rounds
name the capability a workspace lacked instead of spending or refusing a round,
integration and mutation evidence is declared in `TASK_RESULT.evidence` for the
platform evidence gate, and `finalize_pr` reads the gate's manifest. The second
(PC-241, found by v5's live check) is that only a check the base branch requires
can hold a certified PR in draft. The preregistration is
`workflows/sdlc/implement-v7/EXPERIMENT.md`.

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
from dataclasses import dataclass
from pathlib import Path

import pytest

from syn_domain.contexts.orchestration._shared.evidence_contract import (
    EvidenceKind,
    EvidenceManifest,
    EvidenceRequest,
    EvidenceStepKind,
    PatchRemoval,
    StepOutcome,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_gate import (
    GateInputs,
    SettledStep,
    build_manifest,
    plan_steps,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.evidence_record import (
    declared_evidence_from_reported,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    DeclaredEvidence,
    ObservedHead,
)

pytestmark = pytest.mark.unit

_SDLC = Path(__file__).resolve().parents[2] / "workflows" / "sdlc"
_V4 = _SDLC / "implement-v4-precheck" / "workflow.yaml"
_V7 = _SDLC / "implement-v7" / "workflow.yaml"

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

#: Words only the v7 change introduces. A changed finalize hunk naming none of
#: them is a second variable.
_V7_TERMS = (
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
    v4, v7 = _load(_V4), _load(_V7)
    assert (v4.id, v7.id) == ("sdlc-implement-v4-precheck", "sdlc-implement-v7")

    identity = {"id", "name", "description"}
    assert v4.model_dump(exclude=identity | {"phases"}) == v7.model_dump(
        exclude=identity | {"phases"}
    )
    assert [p.id for p in v4.phases] == [p.id for p in v7.phases]
    for old, new in zip(v4.phases, v7.phases, strict=True):
        drop = {"prompt_template"} if old.id in _CHANGED else set()
        assert old.model_dump(exclude=drop) == new.model_dump(exclude=drop), (
            f"phase {old.id} differs from v4-precheck in more than its prompt"
        )


@pytest.mark.parametrize("phase", _CHANGED)
def test_the_treatment_actually_changed_each_prompt_it_claims(phase: str) -> None:
    assert _prompts(_V4)[phase] != _prompts(_V7)[phase]


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
    prompts = _prompts(_V7)
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
    v7 = _prompts(_V7)[phase]
    for one in heading:
        v7 = v7.replace(_section(v7, one), "", 1)
    assert v7 == _prompts(_V4)[phase]


def test_every_finalize_difference_from_v4_is_about_the_v5_change() -> None:
    old = _prompts(_V4)["finalize_pr"].splitlines()
    new = _prompts(_V7)["finalize_pr"].splitlines()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
        a=old, b=new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        hunk = "\n".join(new[max(0, j1 - 1) : j2 + 1])
        assert any(term in hunk for term in _V7_TERMS), (
            f"finalize_pr: a change unrelated to v7:\n{hunk}"
        )


@pytest.mark.parametrize("phase", (*_REVIEWS, *_FIXES))
def test_every_phase_names_the_same_closed_capability_list(phase: str) -> None:
    heading = _REVIEW_SECTION if phase in _REVIEWS else _FIX_SECTION
    named = re.findall(r"`([a-z_]+)`", _section(_prompts(_V7)[phase], heading))
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
    section = _section(_prompts(_V7)[phase], heading)
    match = _EXAMPLE.search(section)
    assert match, f"{phase} shows no evidence entry"
    declared = declared_evidence_from_reported(_concrete(match.group(1)))
    assert len(declared) == 1
    assert declared[0].request is not None, declared[0]


def _review_example() -> str:
    match = _EXAMPLE.search(_section(_prompts(_V7)["verify"], _REVIEW_SECTION))
    assert match, "verify shows no evidence entry"
    return match.group(1)


def test_the_keys_the_prompts_promise_are_the_contracts_keys() -> None:
    entry = _concrete(_review_example())
    assert isinstance(entry, list) and len(entry) == 1
    assert set(entry[0]) == set(EvidenceRequest.model_fields)
    assert "Use exactly these six keys" in _section(_prompts(_V7)["verify"], _REVIEW_SECTION)
    assert len(EvidenceRequest.model_fields) == 6


def test_a_capability_key_on_an_entry_is_refused_as_the_prompt_says() -> None:
    with_capability = _review_example().replace("}]", ', "capability": "nested_docker"}]')
    declared = declared_evidence_from_reported(_concrete(with_capability))
    assert len(declared) == 1
    assert declared[0].request is None


class TestFinalizeTrustsOnlyACompletePassedManifest:
    def test_the_rule_names_both_plan_shapes_the_gate_produces(self) -> None:
        rule = _flat(_section(_prompts(_V7)["finalize_pr"], _FINALIZE_SECTION))
        assert "**With cleanup:** it has a `remove_mutation_patches` step" in rule
        assert "the branch head is `patch_removal.after_sha`" in rule
        assert (
            "**Without cleanup:** mutation and/or integration steps only, and no `required_check` step"
            in rule
        )
        assert "every check in the required set above is green on the current branch head" in rule
        assert "closes the `ORCHESTRATOR_EVIDENCE` rows its phase declared, and only those" in rule

    def test_a_failed_manifest_holds_draft_even_when_the_report_has_no_handoff_row(self) -> None:
        """Codex #2063 r1: a failed cleanup gate after a `None.` report could reach ready."""
        rule = _flat(_section(_prompts(_V7)["finalize_pr"], _FINALIZE_SECTION))
        assert (
            "**A manifest on the current head that does not pass holds the PR in draft on its own**"
            in rule
        )
        assert "whether or not the report has any handoff row" in rule
        assert "does not make a failed gate ready" in rule
        assert "a file that does not parse as a manifest" in rule

    def test_an_open_handoff_still_never_reaches_gh_pr_ready(self) -> None:
        finalize = _prompts(_V7)["finalize_pr"]
        handoff = _flat(_section(finalize, "## If CERTIFIED and a handoff is open"))
        assert "Keep it a **draft**: never call `gh pr ready` here." in handoff
        assert "Needs a capable workspace" in handoff
        certified = _flat(_section(finalize, "## If CERTIFIED"))
        assert "Follow this section only when no handoff is open" in certified

    def test_the_head_exception_is_only_the_recorded_patch_removal(self) -> None:
        head = _flat(_section(_prompts(_V7)["finalize_pr"], "## Check the head"))
        assert "`patch_removal.after_sha` whose `before_sha` is the certified SHA" in head

    def test_the_count_line_each_review_writes_is_the_one_finalize_copies(self) -> None:
        line = (
            "Capability gaps: nested_docker=<n> database=<n> event_store=<n> live_api=<n> other=<n>"
        )
        for phase in _REVIEWS:
            assert line in _prompts(_V7)[phase], phase
        assert "its `Capability gaps:` line copied verbatim" in _flat(_prompts(_V7)["finalize_pr"])


class TestOnlyARequiredCheckHoldsACertifiedPrInDraft:
    """PC-241: certified PR #2080 stayed draft on two non-required Vercel statuses."""

    _RULES = "rules/branches/<base>"

    def test_finalize_holds_only_on_a_required_check(self) -> None:
        rule = _flat(_section(_prompts(_V7)["finalize_pr"], _REQUIRED_FINALIZE_SECTION))
        assert (
            "A `FLAKE/INFRA` handoff holds a certified PR in draft only when its check is required on the base branch"
            in rule
        )
        assert "whose check is **not required** is not open" in rule
        assert "It does not keep the PR a draft and gets no rerun" in rule
        assert self._RULES in rule and "required_status_checks" in rule

    def test_finalize_falls_back_to_holding_when_the_required_set_is_unreadable(self) -> None:
        rule = _flat(_section(_prompts(_V7)["finalize_pr"], _REQUIRED_FINALIZE_SECTION))
        assert "keep every `FLAKE/INFRA` row open" in rule
        assert "`Required checks: unreadable`" in rule

    @pytest.mark.parametrize("phase", _REVIEWS)
    def test_a_review_parks_a_non_required_outside_failure_and_still_blocks_its_own(
        self, phase: str
    ) -> None:
        rule = _flat(_section(_prompts(_V7)[phase], _REQUIRED_REVIEW_SECTION))
        assert "not a handoff and not a blocker" in rule
        assert "### Not required, not holding" in rule
        assert "fails because of this diff** is still `REPAIRABLE`" in rule
        assert "treat every check as required" in rule
        assert self._RULES in rule

    def test_the_required_section_comes_before_the_capability_section(self) -> None:
        for phase in _REVIEWS:
            text = _prompts(_V7)[phase]
            assert text.index(_REQUIRED_REVIEW_SECTION) < text.index(_REVIEW_SECTION), phase


_REPO = "syntropic137/syntropic137"
_SHA = "a" * 40
_CLEANED = "c" * 40


def _declared(kind: EvidenceKind, test: str, head: str = _SHA) -> DeclaredEvidence:
    return DeclaredEvidence(
        request=EvidenceRequest(
            kind=kind, repository=_REPO, branch="feat/x", pr=42, head_sha=head, tests=(test,)
        )
    )


def _gate(*, patches: bool, head: str = _SHA) -> GateInputs:
    return GateInputs(
        declared=(
            _declared(EvidenceKind.MUTATION, "tests/test_a.py::t", head),
            _declared(EvidenceKind.INTEGRATION, "tests/integration/test_i.py::t", head),
        ),
        observed=(
            ObservedHead(
                repository=_REPO,
                branch="feat/x",
                readable=True,
                head_sha=head,
                mutation_patches_present=patches,
                open_pr_number=42,
            ),
        ),
        repositories=frozenset({_REPO}),
        next_is_final=True,
        certified=True,
    )


def _manifest(
    *, patches: bool, outcome: StepOutcome = StepOutcome.PASSED, head: str = _SHA
) -> EvidenceManifest:
    plan = plan_steps(_gate(patches=patches, head=head))
    settled = [
        SettledStep(
            index=step.index,
            outcome=outcome,
            reason=None if outcome is StepOutcome.PASSED else "x",
            # As EvidenceStepHandler records it: the head each step ran on.
            head_sha_evidenced=step.head_sha,
        )
        for step in plan
    ]
    removed = (
        PatchRemoval(before_sha=head, after_sha=_CLEANED, author="syntropic137")
        if patches and outcome is StepOutcome.PASSED
        else None
    )
    return build_manifest("g-1", plan, settled, removed)


def _finalize_closes(manifest: EvidenceManifest, *, head: str, required_green: bool | None) -> bool:
    """The finalize_pr rule as written, applied to a manifest the real gate builds.

    ``required_green`` is None when the required set was unreadable.
    """
    if any(step.outcome is not StepOutcome.PASSED for step in manifest.steps):
        return False
    kinds = {step.kind for step in manifest.steps}
    if EvidenceStepKind.REMOVE_MUTATION_PATCHES in kinds:
        assert EvidenceStepKind.REQUIRED_CHECK in kinds
        return manifest.patch_removal is not None and manifest.patch_removal.after_sha == head
    assert EvidenceStepKind.REQUIRED_CHECK not in kinds
    return required_green is True


class TestFinalizeOnTheGatesRealPlanShapes:
    """Codex #2063 r1: an integration-only plan has no `required_check` step to wait for."""

    def test_the_gate_plans_a_required_check_only_around_a_cleanup(self) -> None:
        with_cleanup = {s.kind for s in _manifest(patches=True).steps}
        without = {s.kind for s in _manifest(patches=False).steps}
        assert {
            EvidenceStepKind.REMOVE_MUTATION_PATCHES,
            EvidenceStepKind.REQUIRED_CHECK,
        } <= with_cleanup
        assert EvidenceStepKind.REQUIRED_CHECK not in without
        assert EvidenceStepKind.INTEGRATION in without

    def test_a_passed_plan_without_cleanup_closes_on_green_required_checks(self) -> None:
        manifest = _manifest(patches=False)
        assert _finalize_closes(manifest, head=_SHA, required_green=True)
        assert not _finalize_closes(manifest, head=_SHA, required_green=False)
        assert not _finalize_closes(manifest, head=_SHA, required_green=None)

    def test_a_passed_plan_with_cleanup_closes_only_on_the_cleaned_head(self) -> None:
        manifest = _manifest(patches=True)
        assert _finalize_closes(manifest, head=_CLEANED, required_green=None)
        assert not _finalize_closes(manifest, head=_SHA, required_green=True)

    @pytest.mark.parametrize("patches", [True, False])
    @pytest.mark.parametrize(
        "outcome", [StepOutcome.FAILED, StepOutcome.VOID, StepOutcome.UNAVAILABLE]
    )
    def test_any_step_not_passed_never_closes(self, patches: bool, outcome: StepOutcome) -> None:
        manifest = _manifest(patches=patches, outcome=outcome)
        assert not _finalize_closes(manifest, head=_CLEANED, required_green=True)


def _evidenced_head(manifest: EvidenceManifest) -> str | None:
    """`patch_removal.after_sha` when present, else the head its steps ran on."""
    if manifest.patch_removal is not None:
        return manifest.patch_removal.after_sha
    heads = {step.head_sha for step in manifest.steps if step.head_sha is not None}
    return heads.pop() if len(heads) == 1 else None


def _finalize_holds_draft(
    manifests: list[EvidenceManifest], *, head: str, declared: bool, open_rows: int
) -> bool:
    """The finalize_pr rule as written: what holds a certified PR in draft."""
    if open_rows:
        return True
    current = [m for m in manifests if _evidenced_head(m) == head]
    if declared and not manifests:
        return True
    return any(not _finalize_closes(m, head=head, required_green=True) for m in current)


_FIXED = "f" * 40


class TestFinalizeJudgesTheCurrentHeadAndAMissingManifest:
    """Codex #2063 r2: a missing manifest failed open; a superseded failure held forever."""

    def test_the_prompt_separates_no_gate_from_a_missing_manifest(self) -> None:
        rule = _flat(_section(_prompts(_V7)["finalize_pr"], _FINALIZE_SECTION))
        assert "**No manifest, nothing declared:** there was no gate to run" in rule
        assert (
            "**No manifest, but evidence was declared:** the declared evidence is unproven" in rule
        )
        assert "A missing manifest is never a pass" in rule
        assert "even when the report's handoff section is `None.`" in rule
        assert "Platform evidence: declared, no manifest" in rule

    def test_the_prompt_retires_manifests_on_an_earlier_head(self) -> None:
        rule = _flat(_section(_prompts(_V7)["finalize_pr"], _FINALIZE_SECTION))
        assert (
            "`patch_removal.after_sha` when it has one, otherwise the `head_sha` its steps ran on"
            in rule
        )
        assert (
            "Only a manifest that evidences the current branch head can pass or hold the PR" in rule
        )
        assert "Superseded evidence" in rule

    def test_declared_evidence_with_no_manifest_and_a_none_section_holds_draft(self) -> None:
        assert _finalize_holds_draft([], head=_SHA, declared=True, open_rows=0)
        assert not _finalize_holds_draft([], head=_SHA, declared=False, open_rows=0)

    def test_a_failure_on_s_is_superseded_by_a_passed_gate_on_t(self) -> None:
        failed_on_s = _manifest(patches=False, outcome=StepOutcome.FAILED, head=_SHA)
        passed_on_t = _manifest(patches=False, head=_FIXED)
        assert _evidenced_head(failed_on_s) == _SHA
        assert _evidenced_head(passed_on_t) == _FIXED
        assert not _finalize_holds_draft(
            [failed_on_s, passed_on_t], head=_FIXED, declared=True, open_rows=0
        )
        assert _finalize_holds_draft([failed_on_s], head=_SHA, declared=True, open_rows=0)


@dataclass(frozen=True)
class _Answer:
    """One `gh api` call as a phase sees it: a list of check names, or an HTTP error."""

    contexts: tuple[str, ...] = ()
    status: int = 200


def _required_set(rules: _Answer, classic: _Answer) -> frozenset[str] | None:
    """The rule the v7 prompts state, as a decision table. None is `unreadable`.

    The rules endpoint is the source. Classic protection adds its checks when it
    answers, and a 404 or 403 from it (the App token's answer on a ruleset
    repository) is a note, not a failure. Anything else fails closed.
    """
    if rules.status != 200:
        return None
    if classic.status == 200:
        return frozenset(rules.contexts) | frozenset(classic.contexts)
    if classic.status in (403, 404):
        return frozenset(rules.contexts)
    return None


class TestRequiredSetReadsRulesetsFirst:
    """v7: v6 failed closed on every run because the App token gets 403 from classic protection."""

    @pytest.mark.parametrize("phase", (*_REVIEWS, "finalize_pr"))
    def test_every_phase_reads_all_ruleset_pages_and_classic_as_a_second_source(
        self, phase: str
    ) -> None:
        text = _prompts(_V7)[phase]
        assert "gh api --paginate repos/<owner>/<name>/rules/branches/<base>" in text
        assert "branches/<base>/protection/required_status_checks --jq '.contexts[]'" in text
        flat = _flat(text)
        assert "The rules command is the source" in flat
        assert "when it answers, the required set is the **union** of both outputs" in flat

    @pytest.mark.parametrize("phase", (*_REVIEWS, "finalize_pr"))
    def test_each_phase_states_the_three_cases(self, phase: str) -> None:
        flat = _flat(_prompts(_V7)[phase])
        assert (
            "A 404 or a 403 from the classic command means classic protection is not readable"
            in flat
        )
        assert "use the rules output alone: that is still a readable answer" in flat
        assert "Only a failure of the rules command" in flat
        assert "makes the set **unreadable**" in flat
        assert "other than a 404 from the classic one" not in flat, "v6's rule is gone"

    def test_ruleset_answer_and_classic_403_is_readable(self) -> None:
        """exec-ea452869d0b1's inputs: v6 called this unreadable."""
        assert _required_set(_Answer(("CI Success",)), _Answer(status=403)) == {"CI Success"}
        assert _required_set(_Answer(("CI Success",)), _Answer(status=404)) == {"CI Success"}

    def test_a_failed_ruleset_read_is_unreadable_whatever_classic_says(self) -> None:
        for classic in (_Answer(("B",)), _Answer(status=403), _Answer(status=404)):
            assert _required_set(_Answer(status=500), classic) is None
            assert _required_set(_Answer(status=403), classic) is None

    def test_classic_200_is_unioned(self) -> None:
        assert _required_set(_Answer(("A",)), _Answer(("B",))) == {"A", "B"}

    def test_any_other_classic_error_is_unreadable(self) -> None:
        assert _required_set(_Answer(("A",)), _Answer(status=502)) is None
