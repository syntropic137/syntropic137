#!/usr/bin/env python3
"""Check, launch and score a versioned eval suite (#967 step 8).

A suite lives in ``evals/<suite-id>/``: ``suite.yaml`` names the workflow and
the models it declares, and ``cases/*.yaml`` holds one case each, of one of
two polarities. A ``defect`` case is a commit that carries a known bug and
what a report must say to have found it: it passes blocked and named. A
``clean`` case is a control, a merged PR head with no known defect: it passes
only certified. ``score`` prints the catch rate over defects and the
false-block rate over controls for each table, because a catch rate alone
cannot tell a careful verifier from one that blocks everything.

ONE STABLE EVAL PER CASE. A run's commit comes from its eval's Baseline, which
holds one SHA per repository and is fixed at create. The cases are one
repository at different commits, so each case is its own eval, and the suite
is a tag on evals: ``suite:<eval_suite>`` plus ``case:<case id>`` names the
case's eval. ``launch`` finds it and creates it only when it is missing, so
every version and every verifier adds runs to the same eval - the eval's run
list is the case's history. What differs between runs goes on the RUN as tags:
``suite-version:<n>`` and ``verifier:<workflow id>``.

    uv run python scripts/eval_suite.py check  [--suite DIR]   # offline dry run
    uv run python scripts/eval_suite.py launch [--suite DIR] [--workflow ID] [--split S] [--api-url URL]
    uv run python scripts/eval_suite.py score  [--suite DIR] [--workflow ID] [--version N] [--split S] [--api-url URL]

SAME CASES, DIFFERENT VERIFIER. A suite lists one or more workflows; each
differs from the others only in who verifies. ``--workflow`` picks one (the
first listed by default), and the suite tag carries it -
``<id>:v<version>:<workflow id>`` - so each workflow's runs are their own
eval set and their own score table. ``check`` validates every listed workflow.

EVERY VERSION KEEPS ITS SCORE. ``suite.yaml`` ``history`` records each earlier
version still in the ledger: its tag exactly as its runs carry it (v1 predates
the workflow suffix: ``verifier-seed-v1:v1``), the workflow it ran and the
cases it held. ``score`` prints one table per version the selected workflow
ran - each version's runs against its own case set, never another's - and
``--version N`` scores one. ``launch`` only ever launches the current version.

TRAIN AND HOLDOUT. Every case declares ``split: train`` or ``split: holdout``,
written once when the case is added. ``--split train`` launches or scores the
train cases only: anything that tunes a verifier (a prompt, a model, a
workflow) reads only those, and the holdout cases are run to report the
result, never to choose it. ``check`` refuses a suite whose holdout share
falls outside 25-35% (rounded outward to whole cases). A case never moves from holdout to train: it has been
seen.

``check`` needs only git. ``launch`` installs the suite's workflow from the
checked-in file (refusing to go on unless the server then holds exactly that
definition), creates any missing case eval and starts real agent runs, which
cost money: never run it from CI. ``score`` reads every run, then records each
verdict on its eval (``POST /evals/{id}/runs/{run}/score``, scorer
``eval_suite.py``, scorer_version the suite version); re-scoring replaces the
eval's current score and the history stays in its events.

INSTALL PROVENANCE. ``launch`` installs with ``version`` = the suite version
(``<n>.0.0``) and ``source_digest`` = sha256 of the exact YAML document it
uploads. The server's install rules then do the rest: a byte-identical
re-launch is a no-op, an archived workflow is restored, and a workflow file
changed without a suite version bump is refused (409, digest mismatch) before
any eval exists. Never install without provenance: once the server records a
version, an install that declares none is refused by design.

THE LAUNCH LEDGER. ``launch`` appends one line per started run to
``<suite>/launches.jsonl`` (commit it: the workspace that launched is
ephemeral). ``score`` scores only the runs that ledger names, and only after
re-reading from the server that the run is still in the eval it launched into,
that the eval pins the case's commit, and that the run used the suite's
workflow. An eval's run list cannot tell a run launched into it from one
attached afterwards - attach never copies the baseline - so a run found only
by tag is reported and never scored.

Exit status: 0 on success (for ``score``: every case scored pass), 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import httpx
import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_shared.settings.dev_tooling import get_dev_api_url

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE = ROOT / "evals" / "verifier-seed-v1"
_SHA = re.compile(r"^[0-9a-f]{40}$")

type Split = Literal["train", "holdout"]
HOLDOUT_SHARE = (0.25, 0.35)
"""The bounds `check` holds a suite's holdout fraction to, rounded outward to whole cases."""


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkflowRef(_Frozen):
    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    """Repo-relative path of the workflow file the suite runs."""
    models: dict[str, str] = Field(min_length=1)
    """Phase id -> the model that phase declares. Must match the workflow file."""


class PastVersion(_Frozen):
    """An earlier suite version whose runs the ledger still records."""

    version: int = Field(ge=1)
    tag: str = Field(min_length=1)
    """The tag its evals and ledger lines carry, verbatim - never recomputed."""
    workflow: str = Field(min_length=1)
    """The one workflow it ran; must be one of the suite's `workflows`."""
    cases: tuple[str, ...] = Field(min_length=1)
    """The case ids it held. Cases added later are not part of its score."""


class Suite(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9._/:-]+$")
    version: int = Field(ge=1)
    goal: str = Field(min_length=1)
    repository: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    workflows: tuple[WorkflowRef, ...] = Field(min_length=1)
    """The verifiers the same cases run under. The first is the default."""
    history: tuple[PastVersion, ...] = ()
    """Earlier versions, so their recorded runs still score against their own cases."""
    eval_suite: str | None = Field(default=None, pattern=r"^[a-z0-9._-]+$")
    """The stable name its case evals are tagged with, ``suite:<eval_suite>``; default `id`.

    Unlike `id` it never carries a version: every version runs into the same evals.
    """

    @property
    def suite_tag(self) -> str:
        return f"suite:{self.eval_suite or self.id}"

    @property
    def current_tag_prefix(self) -> str:
        return f"{self.id}:v{self.version}"

    @field_validator("workflows")
    @classmethod
    def _unique_ids(cls, refs: tuple[WorkflowRef, ...]) -> tuple[WorkflowRef, ...]:
        ids = [r.id for r in refs]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate workflow ids: {sorted(ids)}")
        return refs


class Expected(_Frozen):
    files: tuple[str, ...] = Field(min_length=1)
    """Repo-relative paths the bug lives in. A report must name one, by file name."""
    keywords: tuple[tuple[str, ...], ...] = Field(min_length=1)
    """Groups of alternatives. Every group must match; within a group, any one word."""

    @field_validator("keywords")
    @classmethod
    def _no_empty_group(cls, groups: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        if any(not group or not all(word.strip() for word in group) for group in groups):
            raise ValueError("a keyword group is empty or holds an empty word")
        return groups


Polarity = Literal["defect", "clean"]
"""What a case holds: a known escaped bug the verifier must block, or a clean
control it must certify. Clean controls are what make blocking cost something:
without them a verifier that blocks everything is never wrong."""


def _full_sha(value: str) -> str:
    if not _SHA.fullmatch(value):
        raise ValueError(f"{value!r} is not a full 40-character lowercase SHA")
    return value


FullSha = Annotated[str, AfterValidator(_full_sha)]


class _CaseBase(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    source_pr: int = Field(ge=1)
    """The PR the case is cut from: the one that shipped the bug, or, for a case mined
    from a fix, the one that fixed it. Never put it in `task`: the agent could fetch its history."""
    commit: FullSha
    """The SHA the run is pinned to."""
    task: str = Field(min_length=1)
    split: Split
    """`train` cases may tune a verifier; `holdout` cases only measure it. Never moved."""

    @property
    def tag(self) -> str:
        return f"case:{self.id}"


class DefectCase(_CaseBase):
    """A commit carrying a known bug. Passes when the verifier blocks and names it.

    `source_pr` shipped the bug; `commit` is the tree just before its fix.
    """

    polarity: Literal["defect"]
    fix_commit: FullSha
    """Full SHA of the commit that fixed it (the last, when the fix is a series)."""
    first_fix_commit: FullSha | None = None
    """When the fix is a series of commits, the first of them; default `fix_commit`.

    `commit` must be this commit's first parent: the tree just before the fix,
    so the bug is present and nothing of the fix is.
    """
    expected: Expected

    @property
    def fix_start(self) -> str:
        """The first commit of the fix; `commit` must be its first parent."""
        return self.first_fix_commit or self.fix_commit


class CleanCase(_CaseBase):
    """A merged change with no known defect. Passes only when the verifier certifies it.

    `source_pr` is the merged PR; `commit` is its head as merged, the second
    parent of `merge_commit` on main's first-parent chain.
    """

    polarity: Literal["clean"]
    merge_commit: FullSha
    """The mainline merge that took the PR: its second parent must be `commit`."""
    clean_through: FullSha
    """The mainline commit through which later history was read and held no fix of the PR.

    `merge_commit` must be on its first-parent chain, and no commit between
    them may be a fix or revert that names `#<source_pr>`.
    """


Case = Annotated[DefectCase | CleanCase, Field(discriminator="polarity")]
_CASE: TypeAdapter[DefectCase | CleanCase] = TypeAdapter(Case)


class LoadedSuite(_Frozen):
    suite: Suite
    cases: tuple[DefectCase | CleanCase, ...]
    """The cases of the selected version: every case for the current one."""
    workflow: WorkflowRef
    """The one of `suite.workflows` this run of the script launches or scores."""
    version: int
    """The selected version: `suite.version`, or one recorded in `suite.history`."""
    tag: str
    """The tag every eval of this version and workflow carries; the ledger and `score` name it.

    From v2 the workflow is in it, so two verifiers over the same cases never
    share an eval set, a ledger row or a score table. A past version's tag is
    read from `history` verbatim, so its recorded runs keep scoring.
    """

    @property
    def is_current(self) -> bool:
        return self.version == self.suite.version

    @property
    def run_tags(self) -> list[str]:
        """What `launch` tags each run with: the eval is shared, so the run says what it was."""
        return [f"suite-version:{self.version}", f"verifier:{self.workflow.id}"]


def versions_run(suite: Suite, workflow: str) -> list[int]:
    """Every version `workflow` ran or runs, oldest first: what `score` prints by default."""
    past = [h.version for h in suite.history if h.workflow == workflow]
    return [*sorted(past), suite.version]


class DefinitionError(ValueError):
    """The suite's files are malformed or disagree with each other."""


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def declared_models(workflow_file: Path) -> dict[str, str]:
    """Phase id -> declared model, read by the parser the platform itself uses."""
    definition = WorkflowDefinition.from_file(workflow_file)
    models: dict[str, str] = {}
    for phase in definition.phases:
        model = phase.agent.model if phase.agent and phase.agent.model else phase.model
        models[phase.id] = model or "(platform default)"
    return models


def load_suite(
    directory: Path,
    root: Path = ROOT,
    workflow: str | None = None,
    version: int | None = None,
    split: Split | None = None,
) -> LoadedSuite:
    """Parse and cross-check a suite, selecting `workflow`, `version` and `split`.

    `workflow` defaults to the first listed (for a past version: the one it
    ran), `version` to the current one, `split` to every case. Every listed workflow and every
    history entry is checked, not only the selected ones. Raises
    `DefinitionError` naming every problem found.
    """
    try:
        suite = Suite.model_validate(_read_yaml(directory / "suite.yaml"))
        case_files = sorted((directory / "cases").glob("*.yaml"))
        cases = tuple(_CASE.validate_python(_read_yaml(p)) for p in case_files)
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise DefinitionError(str(exc)) from exc

    problems: list[str] = []
    if not cases:
        problems.append(f"{directory}/cases holds no case")
    for path, case in zip(case_files, cases, strict=True):
        if path.stem != case.id:
            problems.append(f"{path.name}: file name must be the case id {case.id!r}")
        if f"#{case.source_pr}" in case.task:
            problems.append(
                f"{case.id}: task names #{case.source_pr}; the agent could fetch the fix"
            )
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        problems.append(f"duplicate case ids: {sorted(ids)}")
    holdout = sum(c.split == "holdout" for c in cases)
    low, high = HOLDOUT_SHARE
    if not math.floor(low * len(cases)) <= holdout <= math.ceil(high * len(cases)):
        problems.append(
            f"{holdout} of {len(cases)} cases are holdout; the share must be {low:.0%}-{high:.0%}"
        )

    for ref in suite.workflows:
        problems.extend(_workflow_problems(ref, root))
    problems.extend(_history_problems(suite, set(ids)))

    # A past version may have run several workflows, one entry each; with no
    # `workflow` given, the first entry listed for it is the default.
    ran = [h for h in suite.history if h.version == version]
    past = next((h for h in ran if workflow is None or h.workflow == workflow), None)
    if version is not None and version != suite.version and not ran:
        known = sorted({h.version for h in suite.history} | {suite.version})
        problems.append(f"version {version} is not one of the suite's {known}")
    if ran and past is None:
        problems.append(f"version {version} ran only {[h.workflow for h in ran]}, not {workflow!r}")
    chosen = past.workflow if past is not None else workflow or suite.workflows[0].id
    selected = next((ref for ref in suite.workflows if ref.id == chosen), None)
    if selected is None:
        problems.append(
            f"workflow {chosen!r} is not one of the suite's {[r.id for r in suite.workflows]}"
        )
    if problems or selected is None:
        raise DefinitionError("\n".join(problems))
    if split is not None:
        cases = tuple(c for c in cases if c.split == split)
    if past is None:
        return LoadedSuite(
            suite=suite,
            cases=cases,
            workflow=selected,
            version=suite.version,
            tag=f"{suite.current_tag_prefix}:{selected.id}",
        )
    return LoadedSuite(
        suite=suite,
        cases=tuple(c for c in cases if c.id in past.cases),
        workflow=selected,
        version=past.version,
        tag=past.tag,
    )


def _history_problems(suite: Suite, case_ids: set[str]) -> list[str]:
    """Where `history` contradicts itself, the current version or the case files."""
    problems: list[str] = []
    runs = [(h.version, h.workflow) for h in suite.history]
    if len(set(runs)) != len(runs):
        problems.append(f"duplicate history version and workflow: {sorted(runs)}")
    tags = [h.tag for h in suite.history]
    if len(set(tags)) != len(tags):
        problems.append(f"duplicate history tags: {sorted(tags)}")
    workflow_ids = {r.id for r in suite.workflows}
    for h in suite.history:
        if h.version >= suite.version:
            problems.append(f"history v{h.version} is not before the current v{suite.version}")
        if h.workflow not in workflow_ids:
            problems.append(f"history v{h.version} ran {h.workflow!r}, not a listed workflow")
        if h.tag.startswith(f"{suite.current_tag_prefix}:"):
            problems.append(f"history v{h.version} tag {h.tag!r} is the current version's")
        if missing := sorted(set(h.cases) - case_ids):
            problems.append(f"history v{h.version} names no such case(s) {missing}")
    return problems


def _workflow_problems(ref: WorkflowRef, root: Path) -> list[str]:
    """Where the suite's record of one workflow disagrees with the workflow file."""
    workflow_file = root / ref.path
    try:
        definition = WorkflowDefinition.from_file(workflow_file)
    except (OSError, ValidationError, ValueError) as exc:
        return [f"workflow {ref.path}: {exc}"]
    problems: list[str] = []
    if definition.id != ref.id:
        problems.append(f"workflow id is {definition.id!r}, suite says {ref.id!r}")
    actual = declared_models(workflow_file)
    if actual != ref.models:
        problems.append(
            f"suite records models {ref.models} for {ref.id}, the workflow declares {actual}; "
            "update both and bump the suite version"
        )
    return problems


# ---------------------------------------------------------------------------
# check: the offline dry run
# ---------------------------------------------------------------------------


def _git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode == 0


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    ).stdout


def _missing_commits(repo: Path, *shas: str) -> list[str]:
    return [
        s for s in dict.fromkeys(shas) if not _git_ok(repo, "cat-file", "-e", f"{s}^{{commit}}")
    ]


def check_commits(loaded: LoadedSuite, repo: Path) -> list[str]:
    """Problems with each case's pinned history in `repo`; empty when every case holds."""
    problems: list[str] = []
    for case in loaded.cases:
        if isinstance(case, DefectCase):
            problems.extend(_defect_problems(case, repo))
        else:
            problems.extend(_clean_problems(case, repo))
    return problems


def _defect_problems(case: DefectCase, repo: Path) -> list[str]:
    """Every SHA is a commit here, the pin is the first parent of the fix's first
    commit (the tree just before the fix, not merely some ancestor of it), that
    commit leads to the fix, every expected file exists at the pin, and the fix
    changes at least one of them - so the files are where the bug lived, not a guess.
    """
    if missing := _missing_commits(repo, case.commit, case.fix_start, case.fix_commit):
        return [f"{case.id}: no such commit {', '.join(missing)} (try `git fetch origin`)"]
    problems: list[str] = []
    parent = _git_out(repo, "rev-parse", f"{case.fix_start}^1").strip()
    if parent != case.commit:
        problems.append(
            f"{case.id}: pins {case.commit[:12]}, but the fix {case.fix_start[:12]}'s "
            f"first parent is {parent[:12] or '(none)'}; pin the tree just before the fix"
        )
    if not _git_ok(repo, "merge-base", "--is-ancestor", case.fix_start, case.fix_commit):
        problems.append(
            f"{case.id}: the fix's first commit {case.fix_start[:12]} is not an ancestor "
            f"of {case.fix_commit[:12]}"
        )
    for path in case.expected.files:
        if not _git_ok(repo, "cat-file", "-e", f"{case.commit}:{path}"):
            problems.append(f"{case.id}: {path} does not exist at {case.commit[:12]}")
    changed = _git_out(repo, "diff", "--name-only", case.commit, case.fix_commit).split()
    if not set(case.expected.files) & set(changed):
        problems.append(f"{case.id}: the fix changes none of {list(case.expected.files)}")
    return problems


#: A later commit that undoes or repairs a clean control: its subject says fix
#: or revert, and its message names the control's PR or one of its SHAs (what
#: `git revert` writes).
_FIX_SUBJECT = re.compile(r"^(fix|revert)\b", re.IGNORECASE)


def _clean_problems(case: CleanCase, repo: Path) -> list[str]:
    """Every SHA is a commit here, the pin is the merge's second parent (the PR
    head exactly as main took it), the merge is on `clean_through`'s first-parent
    chain (a mainline merge, not one inside a branch), and no commit between the
    merge and `clean_through` is a fix or revert naming the PR.
    """
    if missing := _missing_commits(repo, case.commit, case.merge_commit, case.clean_through):
        return [f"{case.id}: no such commit {', '.join(missing)} (try `git fetch origin`)"]
    problems: list[str] = []
    head = _git_out(repo, "rev-parse", "--verify", "-q", f"{case.merge_commit}^2").strip()
    if head != case.commit:
        problems.append(
            f"{case.id}: pins {case.commit[:12]}, but the merge {case.merge_commit[:12]}'s "
            f"second parent is {head[:12] or '(none)'}; pin the PR head the merge took"
        )
    mainline = _git_out(repo, "rev-list", "--first-parent", case.clean_through).split()
    if case.merge_commit not in mainline:
        problems.append(
            f"{case.id}: the merge {case.merge_commit[:12]} is not on the first-parent "
            f"chain of {case.clean_through[:12]}"
        )
        return problems
    reference = re.compile(rf"#{case.source_pr}\b")
    log = _git_out(
        repo, "log", "--format=%H%x00%B%x01", f"{case.merge_commit}..{case.clean_through}"
    )
    for entry in log.split("\x01"):
        sha, _, message = entry.strip().partition("\x00")
        names = reference.search(message) or case.merge_commit in message or case.commit in message
        if sha and _FIX_SUBJECT.match(message) and names:
            problems.append(
                f"{case.id}: {sha[:12]} fixes or reverts #{case.source_pr} after it merged; "
                "a clean control must have no known defect"
            )
    return problems


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

Verdict = Literal["certified", "blocked"]
RunVerdict = Literal["PASS", "FAIL", "ERROR"]
"""What `score` records on the eval: the API's verdict, not the review's."""
SCORER = "eval_suite.py"


class Score(_Frozen):
    polarity: Polarity
    verdict: Verdict | None
    findings: int
    """How many structured blocking findings the report holds."""
    named_file: str | None
    """The expected file the best-matching blocking finding names, by file name."""
    missing_keywords: tuple[tuple[str, ...], ...]
    """Keyword groups no word of which that same finding contains."""

    @property
    def matched(self) -> bool:
        return self.named_file is not None and not self.missing_keywords

    @property
    def passed(self) -> bool:
        """A defect passes blocked and named; a clean control passes only certified."""
        if self.polarity == "clean":
            return self.verdict == "certified"
        return self.verdict == "blocked" and self.matched

    @property
    def false_block(self) -> bool:
        return self.polarity == "clean" and self.verdict == "blocked"


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BLOCKING_HEADING = re.compile(r"^[\W\d]*blocking\b", re.IGNORECASE)
#: A heading that names non-blocking content (``NON-BLOCKING``, ``Not blocking``,
#: ``Nits``) at ANY depth: nothing under it is a blocking finding, even when it
#: is nested inside the ``BLOCKING`` section.
_NON_BLOCKING_HEADING = re.compile(
    r"\b(non[\s-]*blocking|not\s+blocking|nits?|minor)\b", re.IGNORECASE
)
#: The structured fields the verify prompt requires in each finding block.
_FIELD = re.compile(r"^\s*[-*]?\s*(file|defect|why blocking)\s*:\s*(.*)$", re.IGNORECASE)


def blocking_findings(report: str) -> list[str]:
    """The text of each finding under the report's ``BLOCKING`` heading.

    The verify prompt asks for one sub-heading per blocking defect. A finding
    runs from its sub-heading to the next heading at the same depth or
    shallower; the section ends at the next heading as shallow as ``BLOCKING``
    itself (so ``NON-BLOCKING``, a different word, is never read). Text under
    ``BLOCKING`` but outside any sub-heading is not a finding. A ``#`` line
    inside a fenced code block is code, not a heading.
    """
    findings: list[list[str]] = []
    section: int | None = None
    finding: int | None = None
    skip: int | None = None
    fenced = False
    for line in report.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            depth = len(heading.group(1))
            title = heading.group(2).replace("*", "").replace("_", "")
            if skip is not None and depth <= skip:
                skip = None
            if section is not None and depth <= section:
                section = finding = None
            if _NON_BLOCKING_HEADING.search(title):
                # Non-blocking content at any depth is never a finding.
                skip = depth
                finding = None
                continue
            if section is None:
                if _BLOCKING_HEADING.match(title):
                    section = depth
                continue
            if skip is not None:
                continue
            if finding is None or depth <= finding:
                finding = depth
                findings.append([])
        if finding is not None and skip is None:
            findings[-1].append(line)
    return ["\n".join(lines) for lines in findings]


def finding_fields(finding: str) -> dict[str, str]:
    """The ``File``, ``Defect`` and ``Why blocking`` values of one finding block.

    A field's value runs from its label to the next field label, so a
    multi-line ``Defect`` is read whole.
    """
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in finding.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).lower()
            fields[current] = [match.group(2)]
        elif current is not None:
            fields[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in fields.items()}


def _normalise(text: str) -> str:
    """Lower case, curly quotes made straight, and ``_``/``-``/runs of space made one space.

    So ``execution_id``, ``execution-id`` and ``execution id`` are one word to
    the keyword tables, and markdown emphasis or code ticks do not split one.
    """
    text = text.lower().replace("\u2019", "'").replace("`", "").replace("*", "")
    return re.sub(r"[\s_\-]+", " ", text)


def _names(text: str, file: str) -> bool:
    """The text names the file by its file name, not as the tail of a longer one."""
    return re.search(rf"(?<![\w.-]){re.escape(Path(file).name)}\b", text) is not None


def score_report(expected: Expected, verdict: Verdict | None, report: str) -> Score:
    """Pass = the run's verdict is blocked AND one blocking finding names the defect.

    Naming it means: within ONE finding under the report's ``BLOCKING``
    heading, one of the expected files appears by file name and every keyword
    group has at least one word (case-insensitive, ``_``/``-``/space alike).
    A file mentioned only in passing - under another heading, or in a different
    finding from the one describing the defect - names nothing.
    """
    findings = blocking_findings(report)
    best: tuple[str | None, tuple[tuple[str, ...], ...]] = (None, expected.keywords)
    for text in findings:
        # The file must be in the finding's File field and the defect in its
        # Defect field: a benign mention in "Why blocking" or a stray line does
        # not name the seed (codex review of #1683).
        fields = finding_fields(text)
        # The seed file may be the finding's File or be named inside its Defect
        # (a verifier often files the entry point and names the root-cause
        # module in the explanation: verifier-seed-v1 first run, shared-esp-stream).
        # It never counts from "Why blocking" alone, where a benign mention lives.
        located = fields.get("file", "") + "\n" + fields.get("defect", "")
        named = next((f for f in expected.files if _names(located, f)), None)
        lowered = _normalise(fields.get("defect", ""))
        missing = tuple(
            g for g in expected.keywords if not any(_normalise(w) in lowered for w in g)
        )
        # The finding that names the file outranks one that does not; then the fewest gaps.
        if (named is None, len(missing)) < (best[0] is None, len(best[1])):
            best = (named, missing)
    return Score(
        polarity="defect",
        verdict=verdict,
        findings=len(findings),
        named_file=best[0],
        missing_keywords=best[1],
    )


def score_case(case: Case, verdict: Verdict | None, report: str) -> Score:
    """Score one run of `case`: a defect by `score_report`, a clean control by its verdict alone.

    A clean control has no defect to name, so its findings are counted but never matched.
    """
    if isinstance(case, DefectCase):
        return score_report(case.expected, verdict, report)
    return Score(
        polarity="clean",
        verdict=verdict,
        findings=len(blocking_findings(report)),
        named_file=None,
        missing_keywords=(),
    )


# ---------------------------------------------------------------------------
# API reads (only the fields this script uses; extra fields ignored)
# ---------------------------------------------------------------------------


class _Read(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _BaselineRepo(_Read):
    repository: str
    commit_sha: str


class _Eval(_Read):
    eval_id: str
    tags: list[str]
    baseline_repos: list[_BaselineRepo]


class _EvalList(_Read):
    evals: list[_Eval]
    total: int


class _RunSummary(_Read):
    execution_id: str


class _RunList(_Read):
    items: list[_RunSummary]
    total: int


class _Phase(_Read):
    phase_id: str
    artifact_id: str | None = None
    model: str | None = None
    requested_model: str | None = None


class _Execution(_Read):
    workflow_execution_id: str
    workflow_id: str
    status: str
    review_verdict: Verdict | None = None
    total_cost_usd: Decimal = Decimal(0)
    total_duration_seconds: float | None = None
    unknown_duration_phase_count: int = 0
    phases: list[_Phase] = Field(default_factory=list)


class _ArtifactContent(_Read):
    content: str | None


class _PhaseDefinition(_Read):
    phase_id: str
    prompt_template: str | None = None
    model: str | None = None


class _Workflow(_Read):
    id: str
    phases: list[_PhaseDefinition]


class _ErrorBody(_Read):
    detail: str


class _Installed(_Read):
    id: str
    status: str


class _Created(_Read):
    eval_id: str
    baseline_repos: list[_BaselineRepo]


class _Started(_Read):
    execution_id: str


class Launch(_Frozen):
    """One run `launch` started: the only association `score` trusts."""

    suite: str
    """The tag of the version launched: `<id>:v<version>:<workflow id>` (v1: `<id>:v1`)."""
    case: str
    eval_id: str
    run_id: str
    commit: str
    workflow_id: str


def launches_path(suite_dir: Path) -> Path:
    return suite_dir / "launches.jsonl"


def read_launches(path: Path) -> list[Launch]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Launch.model_validate_json(line) for line in lines if line.strip()]


def _append_launch(path: Path, launch: Launch) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(launch.model_dump_json() + "\n")


class ScoredRun(_Frozen):
    case: str
    eval_id: str
    run_id: str | None
    status: str
    score: Score | None
    cost_usd: Decimal | None
    duration: str
    models: str


def _get[M: BaseModel](client: httpx.Client, model: type[M], path: str, **params: str | int) -> M:
    response = client.get(path, params=params)
    response.raise_for_status()
    return model.model_validate(response.json())


def _report_of(client: httpx.Client, run: _Execution) -> str:
    """Every phase artifact of the run, concatenated: the verify report is among them."""
    texts = [
        _get(client, _ArtifactContent, f"/artifacts/{p.artifact_id}/content").content or ""
        for p in run.phases
        if p.artifact_id
    ]
    return "\n".join(texts)


def _models_of(run: _Execution) -> str:
    return ", ".join(f"{p.phase_id}={p.model or p.requested_model or '?'}" for p in run.phases)


def _duration_of(run: _Execution) -> str:
    if run.total_duration_seconds is None:
        return "-"
    floor = "≥" if run.unknown_duration_phase_count else ""
    return f"{floor}{run.total_duration_seconds:.0f}s"


def _row(case: str, eval_id: str, run_id: str | None, status: str) -> ScoredRun:
    return ScoredRun(
        case=case,
        eval_id=eval_id,
        run_id=run_id,
        status=status,
        score=None,
        cost_usd=None,
        duration="-",
        models="-",
    )


def _launch_problem(
    loaded: LoadedSuite,
    case: Case,
    launch: Launch,
    ev: _Eval,
    member_ids: set[str],
    run: _Execution,
) -> str | None:
    """Why the server no longer backs this ledger line, or None when it does."""
    if launch.run_id not in member_ids:
        return f"not in eval {ev.eval_id} any more"
    # A run not yet moved by the duplicate migration is still in its per-version eval.
    if case.tag not in ev.tags or not {loaded.suite.suite_tag, loaded.tag} & set(ev.tags):
        return f"eval {ev.eval_id} is not tagged {loaded.suite.suite_tag} {case.tag}"
    pinned = [(b.repository, b.commit_sha) for b in ev.baseline_repos]
    if pinned != [(loaded.suite.repository, case.commit)]:
        return f"eval {ev.eval_id} pins {pinned}, the case pins {case.commit[:12]}"
    if run.workflow_id != loaded.workflow.id:
        return f"ran workflow {run.workflow_id}, the suite runs {loaded.workflow.id}"
    return None


def score_suite(
    loaded: LoadedSuite, client: httpx.Client, launches: list[Launch]
) -> tuple[list[ScoredRun], tuple[str, ...]]:
    """Score every run the launch ledger records for the selected version and workflow.

    Returns one row per launched run (and one per case never launched), and a
    line per run found in a tagged eval that the ledger does not record: those
    were attached, or launched by hand, and say nothing about a pinned start.
    """
    rows: list[ScoredRun] = []
    scored_ids: set[str] = set()
    for case in loaded.cases:
        mine = [x for x in launches if x.suite == loaded.tag and x.case == case.id]
        if not mine:
            rows.append(_row(case.id, "-", None, "not launched"))
        stable = _case_evals(client, loaded, case)
        for launch in mine:
            ev, runs = _eval_holding(client, launch, stable)
            run = _get(client, _Execution, f"/executions/{launch.run_id}")
            scored_ids.add(launch.run_id)
            problem = _launch_problem(loaded, case, launch, ev, {r.execution_id for r in runs}, run)
            if problem:
                rows.append(_row(case.id, ev.eval_id, launch.run_id, f"rejected: {problem}"))
                continue
            score = score_case(case, run.review_verdict, _report_of(client, run))
            _record_score(client, loaded, case, ev.eval_id, run, score)
            rows.append(
                ScoredRun(
                    case=case.id,
                    eval_id=ev.eval_id,
                    run_id=run.workflow_execution_id,
                    status=run.status,
                    score=score,
                    cost_usd=run.total_cost_usd,
                    duration=_duration_of(run),
                    models=_models_of(run),
                )
            )

    # The case evals are shared by every version and verifier: a run another
    # ledger line names belongs to another table, not to "unrecorded".
    ledgered = {x.run_id for x in launches}
    unrecorded: list[str] = []
    for case in loaded.cases:
        for ev in _case_evals(client, loaded, case):
            for summary in _member_runs(client, ev.eval_id):
                if summary.execution_id not in scored_ids | ledgered:
                    unrecorded.append(
                        f"{summary.execution_id} in eval {ev.eval_id}: "
                        "not in the launch ledger, not scored"
                    )
    return rows, tuple(unrecorded)


def _eval_holding(
    client: httpx.Client, launch: Launch, stable: list[_Eval]
) -> tuple[_Eval, list[_RunSummary]]:
    """The eval a ledgered run is in now: the case's stable eval, else the one it launched into.

    A run launched before evals were stable is moved into the stable eval by
    scripts/migrate_eval_suite_duplicates.py; its ledger line still names the
    archived duplicate, and is never edited.
    """
    if len(stable) == 1:
        runs = _member_runs(client, stable[0].eval_id)
        if launch.run_id in {r.execution_id for r in runs}:
            return stable[0], runs
    ev = _get(client, _Eval, f"/evals/{launch.eval_id}")
    return ev, _member_runs(client, ev.eval_id)


def _member_runs(client: httpx.Client, eval_id: str) -> list[_RunSummary]:
    """Every run of the eval, across pages: `total` is the count at any page size."""
    runs: list[_RunSummary] = []
    page = 1
    while True:
        batch = _get(client, _RunList, f"/evals/{eval_id}/runs", page=page, page_size=200)
        runs.extend(batch.items)
        if not batch.items or len(runs) >= batch.total:
            return runs
        page += 1


def _case_evals(client: httpx.Client, loaded: LoadedSuite, case: Case) -> list[_Eval]:
    """The case's stable eval: tagged with the suite and the case (repeated `tag` is AND)."""
    params = httpx.QueryParams(
        [("tag", loaded.suite.suite_tag), ("tag", case.tag), ("page_size", 200)]
    )
    response = client.get("/evals", params=params)
    response.raise_for_status()
    return _EvalList.model_validate(response.json()).evals


def run_verdict(run: _Execution, score: Score) -> RunVerdict:
    """The verdict recorded on the eval. ERROR: the run never finished, so it was not judged."""
    if run.status != "completed":
        return "ERROR"
    return "PASS" if score.passed else "FAIL"


def evidence_of(case: Case, run: _Execution, score: Score) -> str:
    """Why the verdict, as markdown: what the scorer looked for and what it found."""
    head = [f"## {case.id} ({case.polarity})", "", f"- run status: `{run.status}`"]
    tail = [f"- models: {_models_of(run) or '-'}"]
    if isinstance(case, CleanCase):
        return "\n".join(
            [
                *head,
                f"- review verdict: `{score.verdict or 'none'}` "
                "(a clean control passes only `certified`)",
                f"- blocking findings: {score.findings}",
                *tail,
            ]
        )
    missing = "; ".join("/".join(g) for g in score.missing_keywords) or "none"
    return "\n".join(
        [
            *head,
            f"- review verdict: `{score.verdict or 'none'}` (a pass needs `blocked`)",
            f"- blocking findings: {score.findings}",
            f"- expected file named: {f'`{score.named_file}`' if score.named_file else 'no'}"
            f" (one of {', '.join(f'`{f}`' for f in case.expected.files)})",
            f"- keyword groups missing: {missing}",
            *tail,
        ]
    )


def _record_score(
    client: httpx.Client,
    loaded: LoadedSuite,
    case: Case,
    eval_id: str,
    run: _Execution,
    score: Score,
) -> None:
    response = client.post(
        f"/evals/{eval_id}/runs/{run.workflow_execution_id}/score",
        json={
            "verdict": run_verdict(run, score),
            "score": 1.0 if score.passed else 0.0,
            "evidence": evidence_of(case, run, score),
            "scorer": SCORER,
            "scorer_version": str(loaded.version),
        },
    )
    if response.is_error:
        raise RuntimeError(
            f"scoring {run.workflow_execution_id} in eval {eval_id}: "
            f"{response.status_code} {_detail(response)}"
        )


def _ratio(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "-"


def rates(rows: list[ScoredRun]) -> str:
    """The catch rate over defect cases and the false-block rate over clean controls.

    Over scored runs only; a run with no verdict is in the denominator and is
    neither a catch nor a false block. A table with no clean controls says so:
    its catch rate alone cannot tell a careful verifier from one that blocks all.
    """
    scores = [r.score for r in rows if r.score]
    defects = [s for s in scores if s.polarity == "defect"]
    clean = [s for s in scores if s.polarity == "clean"]
    caught = sum(1 for s in defects if s.passed)
    blocked = sum(1 for s in clean if s.false_block)
    return f"catch rate (defect cases blocked and named): {_ratio(caught, len(defects))}\n" + (
        f"false-block rate (clean controls blocked): {_ratio(blocked, len(clean))}"
        if clean
        else "false-block rate: not measured, no clean control in this version"
    )


def render(loaded: LoadedSuite, rows: list[ScoredRun], unrecorded: tuple[str, ...] = ()) -> str:
    header = (
        "case",
        "polarity",
        "run id",
        "status",
        "verdict",
        "matched",
        "pass",
        "cost",
        "duration",
        "models",
    )
    lines = [header]
    for r in rows:
        s = r.score
        lines.append(
            (
                r.case,
                s.polarity if s else "-",
                r.run_id or "-",
                r.status,
                (s.verdict or "none") if s else "-",
                (
                    "-"
                    if s.polarity == "clean"
                    else "yes"
                    if s.matched
                    else f"no{'' if s.findings else ' (no blocking findings)'}"
                    f"{'' if s.named_file or not s.findings else ' (file)'}"
                    f"{' (keywords: ' + '; '.join('/'.join(g) for g in s.missing_keywords) + ')' if s.missing_keywords else ''}"
                )
                if s
                else "-",
                ("PASS" if s.passed else "FAIL") if s else "-",
                f"${r.cost_usd:.2f}" if r.cost_usd is not None else "-",
                r.duration,
                r.models,
            )
        )
    widths = [max(len(row[i]) for row in lines) for i in range(len(header))]
    table = "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in lines
    )
    passed = sum(1 for r in rows if r.score and r.score.passed)
    return (
        f"suite {loaded.tag}  version {loaded.version}  workflow {loaded.workflow.id}  "
        f"declared models {loaded.workflow.models}\n\n{table}\n\n{passed}/{len(rows)} passed\n"
        + rates(rows)
        + "".join(f"\nignored: {line}" for line in unrecorded)
    )


# ---------------------------------------------------------------------------
# launch
# ---------------------------------------------------------------------------


def _read_back(client: httpx.Client, path: str, attempts: int = 30) -> _Workflow:
    """Read a just-installed workflow back, waiting out read-model lag.

    The install is accepted before the workflow read model applies it, so an
    immediate GET can 404. Retry 404s for up to ``attempts`` seconds; any other
    status, or a 404 that outlasts the wait, is raised.
    """
    for attempt in range(attempts):
        response = client.get(path)
        if response.status_code != 404 or attempt == attempts - 1:
            response.raise_for_status()
            return _Workflow.model_validate(response.json())
        time.sleep(1)
    raise AssertionError("unreachable")


def _basic_auth() -> httpx.BasicAuth | None:
    """Basic auth for a deployed API (gateway), from the same variables the CLI reads.

    Local dev APIs need none; a selfhost gateway refuses unauthenticated calls.
    """
    user, password = os.environ.get("SYN_API_USER"), os.environ.get("SYN_API_PASSWORD")
    return httpx.BasicAuth(user, password) if user and password else None


def _detail(response: httpx.Response) -> str:
    """The API's error detail, or the raw body when it sent none."""
    try:
        body = _ErrorBody.model_validate(response.json())
    except (ValueError, ValidationError):
        return response.text
    return body.detail


def _workflow_document(loaded: LoadedSuite, root: Path) -> str:
    """The suite's workflow as one YAML document, its prompt files inlined.

    The server has no base directory and refuses a `prompt_file`, so they are
    resolved here by the same domain code `WorkflowDefinition.from_file` uses.
    """
    path = root / loaded.workflow.path
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    WorkflowDefinition._resolve_prompt_files(data, path.parent)  # pyright: ignore[reportPrivateUsage]
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


class Provenance(_Frozen):
    """What `launch` declares when it installs: the suite version and the document's digest."""

    version: str
    source_digest: str


def install_provenance(loaded: LoadedSuite, document: str) -> Provenance:
    """Deterministic install provenance for the suite's workflow document.

    The version is the suite's, so changing a listed workflow without bumping
    the suite reuses a version under a new digest, which the server refuses as
    a republish. The digest covers the uploaded bytes, prompts inlined, so a
    prompt-file edit changes it too.
    """
    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    return Provenance(version=f"{loaded.suite.version}.0.0", source_digest=f"sha256:{digest}")


def install_workflow(loaded: LoadedSuite, client: httpx.Client, root: Path = ROOT) -> str:
    """Install the suite's workflow, then prove the server holds exactly it.

    Install is load-or-create with explicit provenance (`install_provenance`):
    a byte-identical reinstall is a no-op and an archived template is restored,
    so this is safe on every launch. A 409 (same version, other content) stops
    the launch with the server's reason. The read-back is what makes the
    suite's recorded workflow and models true of the runs: a server whose
    definition differs in a phase, a prompt or a model is refused before any
    eval exists.
    """
    w = loaded.workflow
    document = _workflow_document(loaded, root)
    provenance = install_provenance(loaded, document)
    response = client.post(
        "/workflows/from-yaml",
        params={"version": provenance.version, "source_digest": provenance.source_digest},
        content=document.encode("utf-8"),
        headers={"content-type": "application/yaml"},
    )
    if response.status_code == 409:
        raise RuntimeError(
            f"server refused to install {w.id} as version {provenance.version} "
            f"({provenance.source_digest}): {_detail(response)}. If {w.path} changed, "
            "bump the suite version; no eval was created"
        )
    response.raise_for_status()
    installed = _Installed.model_validate(response.json())
    if installed.id != w.id:
        raise RuntimeError(f"installed workflow {installed.id!r}, the suite runs {w.id!r}")

    local = WorkflowDefinition.from_file(root / w.path)
    want = {p.id: (p.prompt_template, w.models[p.id]) for p in local.phases}
    server = _read_back(client, f"/workflows/{w.id}")
    have = {p.phase_id: (p.prompt_template, p.model) for p in server.phases}
    if have != want:
        differs = sorted(k for k in want.keys() | have.keys() if want.get(k) != have.get(k))
        raise RuntimeError(
            f"server definition of {w.id} differs from {w.path} "
            f"in phase(s) {differs} (prompt or model); no eval was created"
        )
    return (
        f"workflow {w.id}: {installed.status} as {provenance.version} "
        f"({provenance.source_digest[:19]}), server definition matches {w.path}"
    )


def stable_eval(loaded: LoadedSuite, case: Case, client: httpx.Client) -> _Created:
    """The case's one eval: found by `suite:` + `case:` tags, created once if missing.

    Refuses to go on when two evals carry the tags (run the duplicate
    migration first) or when the one found pins another commit.
    """
    s = loaded.suite
    found = _case_evals(client, loaded, case)
    if len(found) > 1:
        raise RuntimeError(
            f"{case.id}: {len(found)} evals tagged {s.suite_tag} {case.tag} "
            f"({', '.join(e.eval_id for e in found)}); run scripts/migrate_eval_suite_duplicates.py"
        )
    if found:
        created = _Created(eval_id=found[0].eval_id, baseline_repos=found[0].baseline_repos)
    else:
        response = client.post(
            "/evals",
            json={
                "name": f"{s.eval_suite or s.id}: {case.id}",
                "goal": s.goal,
                "baseline_repos": [{"repository": s.repository, "requested_ref": case.commit}],
                "tags": [s.suite_tag, case.tag],
            },
        )
        response.raise_for_status()
        created = _Created.model_validate(response.json())
    pinned = [b.commit_sha for b in created.baseline_repos]
    if pinned != [case.commit]:
        raise RuntimeError(
            f"{case.id}: eval {created.eval_id} pinned {pinned}, expected {case.commit}"
        )
    return created


def launch_suite(
    loaded: LoadedSuite, client: httpx.Client, ledger: Path, root: Path = ROOT
) -> list[str]:
    """Install the workflow, then start one run per case in the case's stable eval.

    The eval is found by its tags and created only when missing. Each started
    run is appended to `ledger` as it starts, so a launch that dies part way
    still records the runs it began.
    """
    s, w = loaded.suite, loaded.workflow
    out = [install_workflow(loaded, client, root)]
    for case in loaded.cases:
        created = stable_eval(loaded, case, client)
        response = client.post(
            f"/workflows/{w.id}/execute",
            json={
                "task": case.task,
                "repos": [s.repository],
                "eval_id": created.eval_id,
                "tags": loaded.run_tags,
            },
        )
        response.raise_for_status()
        started = _Started.model_validate(response.json())
        _append_launch(
            ledger,
            Launch(
                suite=loaded.tag,
                case=case.id,
                eval_id=created.eval_id,
                run_id=started.execution_id,
                commit=case.commit,
                workflow_id=w.id,
            ),
        )
        out.append(
            f"{case.id}: eval {created.eval_id} @ {case.commit[:12]} -> run {started.execution_id}"
        )
    return out


def describe_launch(loaded: LoadedSuite) -> list[str]:
    """What `launch` would send, one line per case. Writes nothing."""
    s, w = loaded.suite, loaded.workflow
    others = [r.id for r in s.workflows if r.id != w.id]
    return [
        f"workflow {w.id} (models {w.models}); also runnable with --workflow: "
        f"{', '.join(others) or '(none)'}",
        f"first: POST /workflows/from-yaml {w.path} (prompts inlined) as version "
        f"{loaded.suite.version}.0.0 with its sha256 digest, then "
        f"GET /workflows/{w.id} must match its phases, prompts and models {w.models}",
    ] + [
        f"{c.id}: GET /evals?tag={s.suite_tag}&tag={c.tag}, else POST /evals baseline "
        f"{s.repository}@{c.commit} with those tags; then POST /workflows/{w.id}/execute "
        f"with that eval_id and tags {loaded.run_tags}; run recorded in launches.jsonl"
        for c in loaded.cases
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("check", "launch", "score"))
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument(
        "--repo", type=Path, default=ROOT, help="git checkout holding the pinned commits"
    )
    parser.add_argument(
        "--workflow",
        default=None,
        help="which of the suite's workflows to launch or score (default: the first listed)",
    )
    parser.add_argument(
        "--version",
        type=int,
        default=None,
        help="score this version only (default: every version the workflow ran)",
    )
    parser.add_argument(
        "--split",
        choices=("train", "holdout"),
        default=None,
        help="launch or score only these cases (default: all); tune on train only",
    )
    parser.add_argument("--api-url", default=None, help="defaults to DEV__API_URL / localhost")
    parser.add_argument(
        "--launches",
        type=Path,
        default=None,
        help="launch ledger launch appends to and score reads (default <suite>/launches.jsonl)",
    )
    args = parser.parse_args(argv)

    to_score: list[LoadedSuite] = []
    try:
        loaded = load_suite(args.suite, workflow=args.workflow, split=args.split)
        if args.command == "score":
            versions = (
                [args.version]
                if args.version is not None
                else versions_run(loaded.suite, loaded.workflow.id)
            )
            to_score = [
                load_suite(args.suite, workflow=loaded.workflow.id, version=v, split=args.split)
                for v in versions
            ]
    except DefinitionError as exc:
        print(f"❌ {args.suite}:\n{exc}", file=sys.stderr)
        return 1
    if args.version is not None and args.command != "score":
        print(
            "❌ --version selects what `score` reads; launch runs the current version only",
            file=sys.stderr,
        )
        return 1

    if args.command in ("check", "launch"):
        problems = check_commits(loaded, args.repo)
        if problems:
            print("❌ " + "\n❌ ".join(problems), file=sys.stderr)
            return 1
        print(f"✅ {loaded.tag}: {len(loaded.cases)} case(s), every pinned commit and file checked")
        if args.command == "check":
            print("\n".join(describe_launch(loaded)))
            return 0

    ledger: Path = args.launches or launches_path(args.suite)
    with httpx.Client(
        base_url=args.api_url or get_dev_api_url(), timeout=60, auth=_basic_auth()
    ) as client:
        if args.command == "launch":
            print("\n".join(launch_suite(loaded, client, ledger)))
            print(f"recorded in {ledger}: commit it, `score` reads only the runs it names")
            return 0
        launches = read_launches(ledger)
        tables = [(v, *score_suite(v, client, launches)) for v in to_score]
    print("\n\n".join(render(v, rows, unrecorded) for v, rows, unrecorded in tables))
    return (
        0
        if all(rows and all(r.score and r.score.passed for r in rows) for _, rows, _ in tables)
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
