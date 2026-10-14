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
- the safety property is stated: a handoff never reaches `gh pr ready`, and
  only a REPAIRABLE item can make a review BLOCKED and so spend a round.

These are prompt-structure checks. They pin what the prompts say; they cannot
show an agent obeys them. That is what the A/B's mechanism check measures.

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


#: A `gh pr <verb>` command as Markdown writes it, wrapped across lines or not.
_GH_PR = re.compile(r"`gh\s+pr\s+(\w+)")
#: Words that, immediately before the command, make it a prohibition.
_PROHIBITION = re.compile(r"\b(?:never|do not|don't)(?:\s+\w+)?\s*$", re.I)
_SHIPPING_VERBS = frozenset({"ready", "merge", "close"})


def _instructed_shipping_commands(text: str) -> list[str]:
    """Every `gh pr ready|merge|close` in `text` that is not directly prohibited.

    Whitespace is normalised first, so a command wrapped over a line break is
    seen, and every occurrence is checked, so a valid prohibition earlier in
    the section cannot hide an unsafe instruction later in it.
    """
    flat = " ".join(text.split())
    unsafe: list[str] = []
    for m in _GH_PR.finditer(flat):
        if m.group(1) not in _SHIPPING_VERBS:
            continue
        clause = re.split(r"[.:;!?]", flat[: m.start()])[-1]
        if not _PROHIBITION.search(clause):
            unsafe.append(f"{clause.strip()} `gh pr {m.group(1)}")
    return unsafe


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
        verbs = set(_GH_PR.findall(" ".join(handoff.split())))
        assert "comment" in verbs, "the handoffs must be posted where a person sees them"
        assert _instructed_shipping_commands(handoff) == []
        # The explicit policy, not merely the absence of a command.
        assert "Keep it a **draft**: never call `gh pr ready` here." in " ".join(handoff.split())
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


class TestTheDraftGuardSeesWhatItGuards:
    """`_instructed_shipping_commands` against reversals of the real prohibition.

    Each case edits the shipped handoff section, so a guard that only matched
    the unwrapped form, or only the first command, goes red here.
    """

    _REAL = "Keep it a **draft**: never call `gh pr\nready` here."

    @pytest.fixture
    def handoff(self) -> str:
        finalize = _prompts(_V4)["finalize_pr"]
        section = _section(finalize, "## If CERTIFIED and a handoff is open")
        assert self._REAL in section, "the wrapped prohibition these cases edit has moved"
        return section

    def test_the_shipped_prohibition_is_not_an_instruction(self, handoff: str) -> None:
        assert _instructed_shipping_commands(handoff) == []

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            pytest.param(
                _REAL,
                "Publish open handoffs: always call `gh pr\nready <n>` here.",
                id="wrapped-reversal",
            ),
            pytest.param(
                _REAL,
                _REAL + " Then call `gh pr ready <n>`.",
                id="later-instruction-after-a-valid-prohibition",
            ),
            pytest.param(
                "1. Act on the handoffs you can, once each:\n",
                "1. Act on the handoffs you can, once each:\n   - when all pass: `gh pr\n     ready <n>`;\n",
                id="second-list-item",
            ),
        ],
    )
    def test_a_reversal_is_caught(self, handoff: str, old: str, new: str) -> None:
        assert old in handoff
        assert _instructed_shipping_commands(handoff.replace(old, new, 1)) != []


class TestThePrecheckRulesVerificationAskedFor:
    """The two transitions round 1 of verification found ambiguous (B1, B2)."""

    @pytest.fixture
    def precheck(self) -> str:
        return " ".join(_section(_prompts(_V4)["verify"], _PRECHECK).split())

    def test_a_file_missing_from_an_xdist_log_is_not_a_ci_gap(self, precheck: str) -> None:
        assert "a file name missing from a CI log is not proof that CI omitted the test" in (
            precheck
        )
        assert "it is not a `CI_GAP` and not a repair round" in precheck
        assert "Only the static question can show a test is omitted" in precheck
        # Service-dependent checks keep the strict per-file CI evidence.
        assert "still needs its per-file CI line on this SHA" in precheck

    def test_a_repeated_external_failure_stays_a_handoff_with_no_second_rerun(
        self, precheck: str
    ) -> None:
        assert "one rerun per failing step, ever" in precheck
        assert "still `FLAKE/INFRA`, status `base defect: no more reruns`" in precheck
        assert "never `REPAIRABLE` and never a repair round" in precheck
        assert "nobody requests a second rerun" in precheck
        # Terminal closure: the base going green closes it, and nothing in the
        # bullet may grant this SHA another rerun. Every "rerun" there must be
        # one of the two refusals, so "then one rerun on this SHA" fails.
        bullet = precheck.split("status `base defect: no more reruns`. ", 1)[1]
        bullet = bullet.split("The PR stays a draft until then.", 1)[0]
        assert (
            "What closes it is the same check green on the default branch, "
            "and nothing on this SHA: it gets no further rerun here." in bullet
        )
        assert {m for m in re.findall(r"(\w+) (\w+) rerun\b", bullet)} <= {
            ("a", "second"),
            ("no", "further"),
        }
        # The contrary case: the PR's own code under an unchanged test.
        assert "exercises code this PR changed), it is `REPAIRABLE`" in precheck
        finalize = " ".join(_prompts(_V4)["finalize_pr"].split())
        assert "`base defect: no more reruns` gets no rerun at all" in finalize
