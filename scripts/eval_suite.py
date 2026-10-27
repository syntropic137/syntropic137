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

TWO JUDGES. A blocked defect run is credited by the keyword judge (one
blocking finding names an expected file and every keyword group) and, with
``score --llm-judge``, by an LLM judge too (a pinned 5.x model, majority of three answers,
given the case's ``expected.defect`` root cause, asked whether a finding
identifies THIS defect: match / no_match / unclear, with the finding it quotes). The headline catch rate counts a run caught when
the keyword judge OR the LLM judge says ``match``; ``unclear`` is not caught.
Both judges' rates are printed beside it. An LLM-judged score is recorded
under scorer_version ``<suite version>+llm:<model>@prompt-v<n>``, so it never
silently replaces a keyword-only score's meaning; without ``--llm-judge`` the
scorer and its scorer_version are exactly as before, and nothing calls a model.

INSTALL PROVENANCE. ``launch`` installs with ``version`` = the suite version
and the workflow's install ``revision`` (``<n>.<revision>.0``) and ``source_digest`` = sha256 of the exact YAML document it
uploads. The server's install rules then do the rest: a byte-identical
re-launch is a no-op, an archived workflow is restored, and a workflow file
changed without a suite version or revision bump is refused (409, digest mismatch) before
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
import ast
import hashlib
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Protocol

import httpx
import yaml
from agentic_isolation.harnesses.claude import ClaudeHeadless, ClaudeHeadlessError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from syn_domain.contexts.orchestration import (
    DeclaredModel,
    EvalTag,
    InvalidTagsError,
    TagSet,
    declared_model_tags,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_shared.observed_model import is_model_alias
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
    revision: int = Field(default=0, ge=0)
    """Install revision of the workflow file within the suite version; installed as
    ``<suite version>.<revision>.0``. Raise it for an edit that is not part of the
    experiment (no case, prompt or model), so the server takes it as a new version
    instead of refusing a republish. #1780's ``requires_verdict`` is revision 1.
    """


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
    defect: str | None = Field(default=None, min_length=1)
    """The seeded root cause in prose, for the LLM judge only. Never put it in `task`.
    The LLM judge refuses a case without it: "same root cause" needs the root cause."""

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


EscapeClass = Literal[
    "schema gate covers shape not identity",
    "deny path untested",
    "evidence that cannot run on CI",
]
"""Why verification let a defect through: a recurring kind of escaped miss.

- schema gate covers shape not identity: a gate compares an event's fields and
  never its type or version, so a renamed or re-versioned event passes it.
- deny path untested: the refusal branch of an access check has no test, so a
  change that grants too much passes every test there is.
- evidence that cannot run on CI: the tests that would show the defect skip or
  never run where the change is verified (a real store, a pinned image, Docker).
"""


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
    retired: str | None = Field(default=None, min_length=1)
    """Why the case left the suite, and in which version. A retired case is not part
    of the current version: it is kept so the history versions that held it still
    score their runs against it, as it was. Never re-polarise a case in place."""
    escape_class: EscapeClass | None = None
    """What kind of miss the case is, so escapes can be counted by kind. A label
    only: nothing that loads, launches or scores a case reads it."""

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
    so the bug is present and nothing of the fix is - unless the pin is a
    judged tree (`judged_tree`).
    """
    expected: Expected
    reclassified_from: str | None = Field(default=None, min_length=1)
    """The retired clean control this defect was found in, when the case is that
    control reclassified. Its pin is then the control's own commit, kept so the
    reviewed tree does not change: an ancestor of the fix, not its first parent."""
    certified_in: str | None = Field(
        default=None, pattern=r"^https://github\.com/[^/\s]+/[^/\s]+/pull/\d+#\S+$"
    )
    """The verify record (a PR comment URL) naming `commit` as the head verification
    judged. The pin is then that head: on a PR that merges main before its fix,
    the fix's first parent is the merge, a tree no verifier saw."""

    @property
    def fix_start(self) -> str:
        """The first commit of the fix; `commit` must be its first parent or a judged tree."""
        return self.first_fix_commit or self.fix_commit

    @property
    def judged_tree(self) -> bool:
        """Whether `commit` is a tree a verifier reviewed, kept as reviewed: then it
        need only come before the fix, not be the fix's first parent."""
        return self.reclassified_from is not None or self.certified_in is not None


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
    retired = {c.id for c in cases if c.retired}
    if stray := sorted(retired - {i for h in suite.history for i in h.cases}):
        problems.append(f"retired case(s) {stray} are in no history version: delete them")
    every_case, cases = cases, tuple(c for c in cases if not c.retired)
    if not cases:
        problems.append(f"{directory}/cases holds no case")
    for path, case in zip(case_files, every_case, strict=True):
        if path.stem != case.id:
            problems.append(f"{path.name}: file name must be the case id {case.id!r}")
        if f"#{case.source_pr}" in case.task:
            problems.append(
                f"{case.id}: task names #{case.source_pr}; the agent could fetch the fix"
            )
    for case in every_case:
        if isinstance(case, DefectCase) and case.reclassified_from:
            source = next((c for c in every_case if c.id == case.reclassified_from), None)
            if not (isinstance(source, CleanCase) and source.retired):
                problems.append(
                    f"{case.id}: reclassified_from {case.reclassified_from!r} "
                    "is not a retired clean case"
                )
            elif source.commit != case.commit:
                problems.append(
                    f"{case.id}: pins {case.commit[:12]}, but {source.id} pins "
                    f"{source.commit[:12]}; a reclassified control keeps its pin"
                )
    ids = [c.id for c in every_case]
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
        every_case = tuple(c for c in every_case if c.split == split)
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
        cases=tuple(c for c in every_case if c.id in past.cases),
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
    commit (the tree just before the fix, not merely some ancestor of it) - or,
    for a judged tree, a strict ancestor of it - that commit leads to
    the fix, every expected file exists at the pin, and the fix
    changes at least one of them - so the files are where the bug lived, not a guess.
    """
    if missing := _missing_commits(repo, case.commit, case.fix_start, case.fix_commit):
        return [f"{case.id}: no such commit {', '.join(missing)} (try `git fetch origin`)"]
    problems: list[str] = []
    parent = _git_out(repo, "rev-parse", f"{case.fix_start}^1").strip()
    if case.judged_tree:
        if case.commit == case.fix_start or not _git_ok(
            repo, "merge-base", "--is-ancestor", case.commit, case.fix_start
        ):
            problems.append(
                f"{case.id}: pins {case.commit[:12]}, which is not before the fix "
                f"{case.fix_start[:12]}; a judged tree's pin must precede it"
            )
    elif parent != case.commit:
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


QUIET_DAYS = 30
"""How long after a clean control merged no mainline commit may touch what it changed."""


def _functions(repo: Path, commit: str, path: str) -> dict[str, tuple[str, ...]]:
    """Qualified name (``Class.method``) -> the source of each Python function so named in `path`.

    Every definition is found, wherever it sits (under an ``if``, a ``try``, a
    ``with``); only classes and functions qualify a name. Same-named definitions,
    such as a property's getter and setter, are all kept, in order.
    """
    text = _git_out(repo, "show", f"{commit}:{path}")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    lines = text.splitlines()
    found: dict[str, list[str]] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    first = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                    last = child.end_lineno or child.lineno
                    found.setdefault(name, []).append("\n".join(lines[first - 1 : last]))
                visit(child, f"{name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return {name: tuple(sources) for name, sources in found.items()}


def _changed_functions(repo: Path, commit: str) -> dict[str, set[str]]:
    """Python path -> each function whose source `commit` changes against its first parent.

    A function is changed when its source differs, appears or disappears, so a
    line inserted next to a function is not a change to it and one inserted
    inside it is.
    """
    paths = _git_out(repo, "diff", "--name-only", "--no-renames", f"{commit}^1", commit).split()
    changed: dict[str, set[str]] = {}
    for path in (p for p in paths if p.endswith(".py")):
        before, after = _functions(repo, f"{commit}^1", path), _functions(repo, commit, path)
        if names := {n for n in before.keys() | after.keys() if before.get(n) != after.get(n)}:
            changed[path] = names
    return changed


def _touched(repo: Path, merge: str, until: str) -> list[str]:
    """Each mainline commit after `merge`, up to `until`, that touches what `merge` changed.

    "What it changed" is every Python function whose source the PR changed,
    found again by qualified name in each later commit, so a function that
    moves within its file is still followed. Only Python functions can be found
    again here: a non-Python change is the selector's to read by hand. One line
    per hit.
    """
    functions = _changed_functions(repo, merge)
    hits: list[str] = []
    later = _git_out(repo, "rev-list", "--reverse", "--first-parent", f"{merge}..{until}")
    for commit in later.split():
        for path, names in _changed_functions(repo, commit).items():
            hits.extend(
                f"{commit[:12]} changes {path}:{name}"
                for name in sorted(names & functions.get(path, set()))
            )
    return hits


def _clean_problems(case: CleanCase, repo: Path) -> list[str]:
    """Every SHA is a commit here, the pin is the merge's second parent (the PR
    head exactly as main took it), the merge is on `clean_through`'s first-parent
    chain (a mainline merge, not one inside a branch), no commit between the
    merge and `clean_through` is a fix or revert naming the PR, `clean_through`
    is at least `QUIET_DAYS` after the merge, and no mainline commit in those
    days touches a Python function the PR changed.
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
    merged_at = int(_git_out(repo, "show", "-s", "--format=%ct", case.merge_commit))
    quiet_until = merged_at + QUIET_DAYS * 86400
    if int(_git_out(repo, "show", "-s", "--format=%ct", case.clean_through)) < quiet_until:
        problems.append(
            f"{case.id}: clean_through {case.clean_through[:12]} is under {QUIET_DAYS} days "
            "after the merge; a clean control needs that long untouched"
        )
    window_end = _git_out(
        repo, "rev-list", "-1", "--first-parent", f"--before={quiet_until}", case.clean_through
    ).strip()
    problems.extend(
        f"{case.id}: {hit} within {QUIET_DAYS} days of the merge; "
        "a clean control's code must stay untouched that long"
        for hit in _touched(repo, case.merge_commit, window_end)
    )
    return problems


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

JudgeVerdict = Literal["match", "no_match", "unclear"]


class Judgement(_Frozen):
    """One judge's answer to: does a blocking finding identify THIS defect?"""

    judge: str
    """The judge's identity (`KeywordJudge.identity`, `LlmJudge.identity`): part of the score."""
    verdict: JudgeVerdict
    quote: str
    """The finding text it matched, verbatim; empty unless `match`."""
    reason: str


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
    llm: Judgement | None = None
    """The LLM judge's answer; None when the run was scored by keywords alone."""

    @property
    def matched(self) -> bool:
        """The keyword judge's answer. Unchanged by the LLM judge, so stored scores keep their meaning."""
        return self.named_file is not None and not self.missing_keywords

    @property
    def caught(self) -> bool:
        """THE HEADLINE RULE: the keyword judge OR the LLM judge says `match`.

        `unclear` and `no_match` from the LLM judge are not caught. With no LLM
        judgement this is `matched`, exactly as before the judge existed.
        """
        return self.matched or (self.llm is not None and self.llm.verdict == "match")

    @property
    def passed(self) -> bool:
        """A defect passes blocked and named; a clean control passes only certified.

        False with no verdict, but such a run is never a FAIL: `run_verdict`
        makes it ERROR, and ERROR is in no pass, catch or false-block rate.
        """
        if self.polarity == "clean":
            return self.verdict == "certified"
        return self.verdict == "blocked" and self.caught

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


def score_case(case: Case, verdict: Verdict | None, report: str, llm: Judge | None = None) -> Score:
    """Score one run of `case`: a defect by `score_report`, a clean control by its verdict alone.

    A clean control has no defect to name, so its findings are counted but never matched.
    With `llm`, a blocked defect run is also put to the LLM judge and `Score.caught`
    credits either judge; without it the score is the keyword judge's alone.
    """
    if isinstance(case, DefectCase):
        score = score_report(case.expected, verdict, report)
        if llm is None or verdict != "blocked":
            return score
        return score.model_copy(update={"llm": llm.judge(case.expected, blocking_findings(report))})
    return Score(
        polarity="clean",
        verdict=verdict,
        findings=len(blocking_findings(report)),
        named_file=None,
        missing_keywords=(),
    )


# ---------------------------------------------------------------------------
# Judges: does a blocking finding identify THIS defect?
#
# Two answer the same question. The keyword judge is deterministic and is
# `score_report`, unchanged. The LLM judge reads the finding as a reviewer
# would, so a correct finding in other words is credited. The judge is part
# of the eval's identity: its model and prompt version go into the recorded
# scorer_version, so a judge change never mixes with scores taken without it.
# ---------------------------------------------------------------------------


class Judge(Protocol):
    @property
    def identity(self) -> str:
        """What produced the answer, exactly enough that a change to it is a new scorer."""
        ...

    def judge(self, expected: Expected, findings: list[str]) -> Judgement: ...


class KeywordJudge:
    """`score_report`'s file-and-keyword match, as a `Judge`. Deterministic, offline."""

    identity = "keyword"

    def judge(self, expected: Expected, findings: list[str]) -> Judgement:
        report = "\n".join(["# BLOCKING", *findings])
        score = score_report(expected, "blocked", report)
        if score.matched:
            return Judgement(
                judge=self.identity, verdict="match", quote="", reason=f"names {score.named_file}"
            )
        missing = "; ".join("/".join(g) for g in score.missing_keywords)
        return Judgement(
            judge=self.identity,
            verdict="no_match",
            quote="",
            reason=f"file {'named' if score.named_file else 'not named'}; keywords missing: {missing}",
        )


class ModelClient(Protocol):
    """The one call the LLM judge makes. A fake answers in tests: no network there."""

    def complete(self, *, model: str, system: str, prompt: str) -> str: ...


class JudgeError(RuntimeError):
    """The LLM judge could not answer: a disallowed model, a failed call, or an unreadable reply."""


JUDGE_MODEL = "claude-sonnet-5-5"
"""Pinned explicit model id, never an alias: the judge is part of the eval's identity.

The 5.x models reject a non-default temperature with HTTP 400, so the judge is not
made repeatable by sampling settings: it asks `JUDGE_SAMPLES` times and takes the
majority (`LlmJudge`)."""
JUDGE_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})
"""The only model ids the judge may call: explicit 5.x ids, no aliases, no pre-5 model.

The one policy, checked by `require_judge_model` both where a judge is built and
in `HeadlessJudgeClient` before any call reaches the transport."""
JUDGE_SAMPLES = 3
"""Independent answers per judgement. Odd, so two verdicts cannot tie on a two-way split."""
JUDGE_EFFORT = "medium"
"""Pinned `claude --effort`: the model's default is not part of a stable identity."""
JUDGE_PROMPT_VERSION = 5
"""Bump on ANY change to `_JUDGE_SYSTEM`, `_judge_prompt`, what they are given, or how
the answers become a verdict: it is part of the scorer version. v2: the case's
`expected.defect` is required, never inferred. v3: the codex-deliverable-phase-failed
description no longer reads as waiving auth and malformed-stream faults when a
deliverable exists. v4: `claude-sonnet-5-5` replaces the temperature-0 judge; the
verdict is the strict majority of `JUDGE_SAMPLES` schema-constrained answers at
`JUDGE_EFFORT`, `unclear` when there is none. v5: answered through Claude Code
(`claude -p` on its own login) instead of the Messages API; the reply is held to
`_JudgeReply` by the prompt and validation, not by an API-side schema. The transport
moving to agentic-workspace's `ClaudeHeadless` (#2036) changed no prompt or vote."""


def require_judge_model(model: str) -> str:
    """`model` if it is in `JUDGE_MODELS`; a `JudgeError` before any call otherwise."""
    if model not in JUDGE_MODELS:
        raise JudgeError(
            f"the LLM judge never calls {model!r}: allowed models are {sorted(JUDGE_MODELS)}"
        )
    return model


_JUDGE_SYSTEM = """You grade a code reviewer. You are given ONE known defect and the \
reviewer's blocking findings. Answer whether any single finding identifies THIS defect: \
the same root cause, in the same file or an equivalent location. Precision matters more \
than recall. A finding that is vague, names only the area, describes a different bug in \
the same file, or would be true of many changes is NOT a match. Answer "unclear" only \
when a finding plausibly describes the defect but you cannot tell.

Reply with one JSON object and nothing else:
{"verdict": "match" | "no_match" | "unclear", "quote": "<the matching finding's \
sentence, copied verbatim; empty unless match>", "reason": "<one line>"}"""


def _judge_prompt(expected: Expected, findings: list[str]) -> str:
    if expected.defect is None:
        raise JudgeError("the LLM judge needs the case's expected.defect; it never infers it")
    keywords = "\n".join(f"- any of: {', '.join(g)}" for g in expected.keywords)
    blocks = "\n\n".join(f"<finding {i}>\n{f}\n</finding {i}>" for i, f in enumerate(findings, 1))
    return (
        "<defect>\n"
        f"{expected.defect}\n"
        f"Files the fix changed:\n" + "\n".join(f"- {f}" for f in expected.files) + "\n"
        f"Concepts a correct finding expresses, in some words:\n{keywords}\n"
        "</defect>\n\n"
        f"<findings>\n{blocks or '(none)'}\n</findings>"
    )


class _JudgeReply(_Frozen):
    verdict: JudgeVerdict
    quote: str
    reason: str


def _squash(text: str) -> str:
    return " ".join(_normalise(text).split())


class LlmJudge:
    """Asks a pinned model whether a finding identifies the defect, by majority vote.

    The model is asked `JUDGE_SAMPLES` times. A verdict more than half the answers
    give is the judgement; no majority is `unclear`, so a judge that disagrees with
    itself never credits a catch. A `match` whose quote is not in any finding counts
    as an `unclear` answer: the judge must point at what the reviewer wrote, not at
    what it imagines they meant.
    """

    def __init__(self, client: ModelClient, model: str = JUDGE_MODEL) -> None:
        self._client = client
        self._model = require_judge_model(model)

    @property
    def identity(self) -> str:
        return f"llm:{self._model}@prompt-v{JUDGE_PROMPT_VERSION}"

    def judge(self, expected: Expected, findings: list[str]) -> Judgement:
        if not findings:
            return Judgement(
                judge=self.identity, verdict="no_match", quote="", reason="no blocking findings"
            )
        prompt = _judge_prompt(expected, findings)
        answers = [self._answer(prompt, findings) for _ in range(JUDGE_SAMPLES)]
        votes = Counter(a.verdict for a in answers)
        tally = ", ".join(f"{v} {n}/{JUDGE_SAMPLES}" for v, n in votes.most_common())
        verdict, count = votes.most_common(1)[0]
        if count * 2 <= JUDGE_SAMPLES:
            return Judgement(
                judge=self.identity, verdict="unclear", quote="", reason=f"no majority: {tally}"
            )
        chosen = next(a for a in answers if a.verdict == verdict)
        return Judgement(
            judge=self.identity,
            verdict=verdict,
            quote=chosen.quote if verdict == "match" else "",
            reason=f"{chosen.reason} ({tally})",
        )

    def _answer(self, prompt: str, findings: list[str]) -> _JudgeReply:
        """One sample, with a `match` that quotes no finding turned into `unclear`."""
        raw = self._client.complete(model=self._model, system=_JUDGE_SYSTEM, prompt=prompt)
        body = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            reply = _JudgeReply.model_validate_json(body)
        except ValidationError as exc:
            raise JudgeError(f"{self.identity} replied with no readable verdict: {raw!r}") from exc
        if reply.verdict == "match" and (
            not reply.quote.strip() or not any(_squash(reply.quote) in _squash(f) for f in findings)
        ):
            return _JudgeReply(
                verdict="unclear",
                quote="",
                reason=f"quote not found in any finding; judge said: {reply.reason}",
            )
        return reply


def judge_problems(loaded: LoadedSuite) -> list[str]:
    """Defect cases the LLM judge cannot score: those with no `expected.defect`."""
    return [
        f"{c.id}: no expected.defect"
        for c in loaded.cases
        if isinstance(c, DefectCase) and c.expected.defect is None
    ]


class JudgeTransportError(JudgeError):
    """The judge's model call gave no answer. The cause is the transport's own error."""


@dataclass(frozen=True)
class HeadlessJudgeClient:
    """`ModelClient` for the judge over agentic-workspace's `ClaudeHeadless` (`claude -p`).

    The judge's policy is enforced here, before the transport sees the call: the model
    must be an allowed id (`require_judge_model`), and every way the transport gives
    no answer becomes a `JudgeTransportError` with the transport's error as its cause,
    never a reply. How the CLI is run on its OAuth login, and never on an API key, is
    `ClaudeHeadless`'s to keep (lib/agentic-workspace, `harnesses/claude/headless.py`).
    """

    transport: ModelClient = field(default_factory=lambda: ClaudeHeadless(effort=JUDGE_EFFORT))

    def complete(self, *, model: str, system: str, prompt: str) -> str:
        model = require_judge_model(model)
        try:
            return self.transport.complete(model=model, system=system, prompt=prompt)
        except (ClaudeHeadlessError, OSError) as exc:
            raise JudgeTransportError(
                f"the LLM judge got no answer from {model}: {type(exc).__name__}: {exc}"
            ) from exc


def scorer_version(loaded: LoadedSuite, llm: Judge | None) -> str:
    """The suite version, plus the LLM judge's identity when one scored.

    Keyword-only scoring keeps the plain suite version it always recorded, so
    stored scores keep their meaning; an LLM-judged score is a different scorer.
    """
    return str(loaded.version) if llm is None else f"{loaded.version}+{llm.identity}"


def scorer_protocol(loaded: LoadedSuite, llm: Judge | None) -> str:
    """The tag-safe id of the scoring protocol a `--trials` cohort declares (`scorer:<id>`).

    The server judges a trial for its cohort only when the score's
    scorer_version equals the cohort's `scorer:` tag, so this is also the
    scorer_version a trial is scored under. `scorer_version` is not used for
    trials: the LLM spelling holds `+` and `@`, which are not tag characters.
    Keyword-only, it is the same plain suite version.
    """
    if llm is None:
        return str(loaded.version)
    return re.sub(r"[^a-z0-9._-]+", "-", f"{loaded.version}-{llm.identity}".lower())


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
    tags: list[str] = Field(default_factory=list)


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
    batch: str | None = None
    """`launch --trials`: the batch this trial was launched in; None for a single run."""
    trial: int | None = None
    """`launch --trials`: the trial's index within its batch, from 1."""
    scorer: str | None = None
    """`launch --trials`: the scoring protocol id the trial's cohort declared (`scorer:` tag).

    `score` records the trial's score under exactly this scorer_version, or the
    server never judges it for its cohort.
    """


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
    warning: str | None = None
    """Where the report's own `VERDICT:` line and the engine's verdict disagree."""

    @property
    def verdict(self) -> RunVerdict | None:
        """The verdict `score` records; None for a run never scored (not launched, rejected)."""
        return run_verdict(self.status, self.score) if self.score else None


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
    loaded: LoadedSuite, client: httpx.Client, launches: list[Launch], llm: Judge | None = None
) -> tuple[list[ScoredRun], tuple[str, ...]]:
    """Score every run the launch ledger records for the selected version and workflow.

    With `llm`, each blocked defect run is also put to the LLM judge (see `Score.caught`).

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
            protocol = scorer_protocol(loaded, llm)
            if launch.scorer is not None and launch.scorer != protocol:
                rows.append(
                    _row(
                        case.id,
                        ev.eval_id,
                        launch.run_id,
                        f"rejected: launched for scorer {launch.scorer}, scoring as {protocol}; "
                        "score it with the judge it was launched for",
                    )
                )
                continue
            report = _report_of(client, run)
            score = score_case(case, run.review_verdict, report, llm)
            version = launch.scorer or scorer_version(loaded, llm)
            _record_score(client, loaded, case, ev.eval_id, run, score, version)
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
                    warning=verdict_mismatch(run.review_verdict, report),
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
    """The case's active stable eval: tagged with the suite and the case (repeated `tag` is AND).

    An archived eval is not the case's: the duplicate migration archives what it folds.
    """
    params = httpx.QueryParams(
        [
            ("tag", loaded.suite.suite_tag),
            ("tag", case.tag),
            ("status", "active"),
            ("page_size", 200),
        ]
    )
    response = client.get("/evals", params=params)
    response.raise_for_status()
    return _EvalList.model_validate(response.json()).evals


def run_verdict(status: str, score: Score) -> RunVerdict:
    """The verdict recorded on the eval: ERROR when the run was not judged.

    A run is judged only when it completed AND the engine recorded a review
    verdict. A completed run with none (#1780) failed to report, it did not
    review badly, so it is ERROR, never FAIL, whatever its report text says.
    """
    if status != "completed" or score.verdict is None:
        return "ERROR"
    return "PASS" if score.passed else "FAIL"


_REPORT_VERDICT = re.compile(r"^\W*VERDICT:\W*(\w+)", re.MULTILINE)


def verdict_mismatch(engine: Verdict | None, report: str) -> str | None:
    """A warning when the report's first `VERDICT:` line disagrees with the engine.

    For a human to read only: the score never comes from the report text, since
    the engine verdict is what the workflow actually reported (#1780).
    """
    said = _REPORT_VERDICT.search(report)
    if said is None or said.group(1).lower() == engine:
        return None
    return f"report says VERDICT: {said.group(1)}, engine recorded {engine or 'no verdict'}"


def evidence_of(case: Case, run: _Execution, score: Score) -> str:
    """Why the verdict, as markdown: what the scorer looked for and what it found."""
    head = [
        f"## {case.id} ({case.polarity})",
        "",
        f"- run status: `{run.status}`",
        f"- recorded: `{run_verdict(run.status, score)}` (ERROR: not completed, or no review verdict)",
    ]
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
            f"- keyword judge: {'match' if score.matched else 'no match'}",
            *(
                [
                    f"- LLM judge (`{score.llm.judge}`): `{score.llm.verdict}`: {score.llm.reason}",
                    *([f"  - matched: {score.llm.quote!r}"] if score.llm.quote else []),
                ]
                if score.llm
                else []
            ),
            f"- caught (keyword OR LLM `match`; `unclear` is not): {'yes' if score.caught else 'no'}",
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
    version: str,
) -> None:
    response = client.post(
        f"/evals/{eval_id}/runs/{run.workflow_execution_id}/score",
        json={
            "verdict": run_verdict(run.status, score),
            "score": 1.0 if score.passed else 0.0,
            "evidence": evidence_of(case, run, score),
            "scorer": SCORER,
            "scorer_version": version,
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

    Over judged runs only (PASS or FAIL), as the API's pass rate: an ERROR run
    was not judged, so it is in no denominator. A table with no clean controls
    says so: its catch rate alone cannot tell a careful verifier from one that
    blocks all.
    """
    scores = [r.score for r in rows if r.score and r.verdict != "ERROR"]
    defects = [s for s in scores if s.polarity == "defect"]
    clean = [s for s in scores if s.polarity == "clean"]
    caught = sum(1 for s in defects if s.passed)
    blocked = sum(1 for s in clean if s.false_block)
    has_clean = any(r.score and r.score.polarity == "clean" for r in rows)
    judged_by_llm = any(s.llm for s in defects)
    by_judge = (
        "  keyword judge alone: "
        f"{_ratio(sum(1 for s in defects if s.verdict == 'blocked' and s.matched), len(defects))}\n"
        "  LLM judge alone: "
        f"{_ratio(sum(1 for s in defects if s.verdict == 'blocked' and s.llm and s.llm.verdict == 'match'), len(defects))}"
        f" ({sum(1 for s in defects if s.llm and s.llm.verdict == 'unclear')} unclear)\n"
        if judged_by_llm
        else ""
    )
    headline = (
        "catch rate (defect cases blocked and named; keyword OR LLM match, unclear not caught): "
        if judged_by_llm
        else "catch rate (defect cases blocked and named): "
    )
    return f"{headline}{_ratio(caught, len(defects))}\n{by_judge}" + (
        f"false-block rate (clean controls blocked): {_ratio(blocked, len(clean))}"
        if has_clean
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
        "llm",
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
                s.llm.verdict if s and s.llm else "-",
                r.verdict or "-",
                f"${r.cost_usd:.2f}" if r.cost_usd is not None else "-",
                r.duration,
                r.models,
            )
        )
    widths = [max(len(row[i]) for row in lines) for i in range(len(header))]
    table = "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in lines
    )
    verdicts = [r.verdict for r in rows]
    judged = sum(1 for v in verdicts if v in ("PASS", "FAIL"))
    errors = verdicts.count("ERROR")
    return (
        f"suite {loaded.tag}  version {loaded.version}  workflow {loaded.workflow.id}  "
        f"declared models {loaded.workflow.models}\n\n{table}\n\n"
        f"{verdicts.count('PASS')}/{judged} passed (ERROR excluded, as in the API)"
        f"{f'; {errors} ERROR' if errors else ''}"
        f"{f'; {len(rows) - judged - errors} not scored' if len(rows) > judged + errors else ''}\n"
        + rates(rows)
        + "".join(f"\nwarning: {r.case} {r.run_id}: {r.warning}" for r in rows if r.warning)
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

    The version is the suite's, with the workflow's install `revision` as the
    minor, so changing a listed workflow without bumping either reuses a
    version under a new digest, which the server refuses as a republish. The digest covers the uploaded bytes, prompts inlined, so a
    prompt-file edit changes it too.
    """
    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    return Provenance(
        version=f"{loaded.suite.version}.{loaded.workflow.revision}.0",
        source_digest=f"sha256:{digest}",
    )


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
            "bump the suite version (or, for an edit outside the experiment, the workflow's "
            "revision); no eval was created"
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


def stable_key(loaded: LoadedSuite, case: Case) -> str:
    """What names the case's one eval to the server: the suite and the case tag (#1920)."""
    return f"{loaded.suite.suite_tag}\n{case.tag}"


def create_stable_eval(loaded: LoadedSuite, case: Case, client: httpx.Client) -> httpx.Response:
    """POST the case's eval under its `stable_key`: idempotent, however many launches race.

    The server derives the eval id from the key, so every caller writes the same
    stream and the event store admits one create; the others get that eval back.
    """
    s = loaded.suite
    return client.post(
        "/evals",
        json={
            "stable_key": stable_key(loaded, case),
            "name": f"{s.eval_suite or s.id}: {case.id}",
            "goal": s.goal,
            "baseline_repos": [{"repository": s.repository, "requested_ref": case.commit}],
            "tags": [s.suite_tag, case.tag],
        },
    )


def stable_eval(loaded: LoadedSuite, case: Case, client: httpx.Client) -> _Created:
    """The case's one eval: found by `suite:` + `case:` tags, created once if missing.

    The tag lookup only saves a request and keeps an eval made before #1920
    in use. It reads a projection, so two launches can both miss: that is
    safe because the create is keyed by `stable_key`, not by this read.
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
        created = _Created(
            eval_id=found[0].eval_id, baseline_repos=found[0].baseline_repos, tags=found[0].tags
        )
    else:
        response = create_stable_eval(loaded, case, client)
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
        f"{c.id}: GET /evals?tag={s.suite_tag}&tag={c.tag}, else POST /evals keyed by suite+case, baseline "
        f"{s.repository}@{c.commit} with those tags; then POST /workflows/{w.id}/execute "
        f"with that eval_id and tags {loaded.run_tags}; run recorded in launches.jsonl"
        for c in loaded.cases
    ]


# ---------------------------------------------------------------------------
# k trials per case (#2108, docs/plans/20261026_eval-k-trials.md sections 5, 8, 9)
# ---------------------------------------------------------------------------

DEFAULT_TRIALS = 3
"""`--trials` with no count: k = 3 (plan section 15 leaves 3 vs 5 for holdout to the owner)."""


def roster_tags(loaded: LoadedSuite, case: Case) -> list[str]:
    """What `register` writes onto a case's eval: the roster of `loaded.version` (plan 5.1).

    Version tags accumulate, so a case in v7 and v8 carries both. Split and
    polarity never change, so a disagreeing tag is refused, never replaced.
    """
    return [
        f"{EvalTag.SUITE_VERSION}:{loaded.version}",
        f"{EvalTag.SPLIT}:{case.split}",
        f"{EvalTag.POLARITY}:{case.polarity}",
    ]


def _roster_conflicts(case: Case, tags: list[str]) -> list[str]:
    problems: list[str] = []
    for prefix, want in ((EvalTag.SPLIT, case.split), (EvalTag.POLARITY, case.polarity)):
        have = sorted({t.removeprefix(f"{prefix}:") for t in tags if t.startswith(f"{prefix}:")})
        if have and have != [want]:
            problems.append(
                f"{case.id}: its eval is tagged {prefix}:{have}, the case file says {want}"
            )
    return problems


def register_roster(loaded: LoadedSuite, client: httpx.Client) -> list[str]:
    """Create every case's stable eval and tag it with the roster. Idempotent.

    Every eval is found or created and checked before any tag is written, so a
    split or polarity conflict anywhere writes nothing at all.
    """
    found = [(case, stable_eval(loaded, case, client)) for case in loaded.cases]
    if problems := [p for case, ev in found for p in _roster_conflicts(case, ev.tags)]:
        raise RuntimeError("roster conflicts, nothing tagged:\n  " + "\n  ".join(problems))
    out: list[str] = []
    for case, ev in found:
        missing = [t for t in roster_tags(loaded, case) if t not in ev.tags]
        if missing:
            response = client.post(f"/evals/{ev.eval_id}/tags", json={"tags": missing})
            if response.is_error:
                raise RuntimeError(
                    f"tagging {case.id} (eval {ev.eval_id}): "
                    f"{response.status_code} {_detail(response)}"
                )
        out.append(f"{case.id}: eval {ev.eval_id} " + (f"+{missing}" if missing else "rostered"))
    return out


_GIT_INTEGRATE = re.compile(r"\bgit\s+(merge|pull|rebase)(?![\w-])([^\n`;&|)]*)")
_DEFAULT_BRANCH = re.compile(
    r"(?<![\w/-])(?:origin/)?(?:main|master|HEAD|<base>|<default[ _-]?branch>)(?![\w/-])"
    r"|\$\{?\w*(?:BASE|DEFAULT)\w*\}?",
    re.IGNORECASE,
)
_PROSE_INTEGRATE = re.compile(
    r"\b(?:merge|rebase(?:\s+(?:onto|on))?)\s+`?origin/(?:main|master|HEAD|<base>)`?",
    re.IGNORECASE,
)


def default_branch_integrations(prompt: str) -> list[str]:
    """Every command in `prompt` that moves a checkout onto the default branch (plan section 9).

    `git pull` in any form (it integrates the upstream), and `git merge` or
    `git rebase` naming the default branch (`origin/main`, `origin/<base>`,
    `$BASE`...), and prose asking for one ("merge `origin/main` into your
    branch"). `git merge --abort` and `git merge-base` move nothing, and a
    prohibition that names no default branch ("do not fetch, pull...") is
    not an instruction to integrate.
    """
    hits: list[str] = []
    for match in _GIT_INTEGRATE.finditer(prompt):
        verb, rest = match.group(1), match.group(2)
        if verb == "pull" or _DEFAULT_BRANCH.search(rest):
            hits.append(match.group(0).strip())
    commands = [m.span() for m in _GIT_INTEGRATE.finditer(prompt)]
    for match in _PROSE_INTEGRATE.finditer(prompt):
        if not any(start <= match.start() < end for start, end in commands):
            hits.append(match.group(0).strip())
    return hits


def pin_safety_problems(ref: WorkflowRef, root: Path = ROOT) -> list[str]:
    """Where a suite workflow's prompts would move a run off its pinned baseline."""
    definition = WorkflowDefinition.from_file(root / ref.path)
    return [
        f"workflow {ref.id} phase {phase.id}: `{hit}` moves the run off its pinned baseline; "
        "an eval subject must stay on the pin (#2055)"
        for phase in definition.phases
        for hit in default_branch_integrations(phase.prompt_template or "")
    ]


def alias_problems(loaded: LoadedSuite) -> list[str]:
    """Declared models a `--trials` cohort cannot carry: aliases, or no model at all.

    A cohort's `model:` tags are checked against what each phase observed,
    which is always an explicit id, so an alias would mismatch every trial.
    """
    return [
        f"workflow {loaded.workflow.id} phase {phase}: declares {model!r}, not an explicit "
        "model id; replace it in the workflow and suite.yaml and bump the suite version"
        for phase, model in loaded.workflow.models.items()
        if is_model_alias(model) or model == "(platform default)"
    ]


def trial_problems(loaded: LoadedSuite, root: Path = ROOT) -> list[str]:
    """Why the selected workflow cannot be measured with `--trials`; empty when it can."""
    return alias_problems(loaded) + pin_safety_problems(loaded.workflow, root)


def declared(loaded: LoadedSuite) -> list[DeclaredModel]:
    return [DeclaredModel(phase, model) for phase, model in loaded.workflow.models.items()]


def cohort_tags(loaded: LoadedSuite, protocol: str) -> list[str]:
    """The launch tags every trial of the cohort carries (plan 5.2); the trial tag is per run."""
    return [
        *loaded.run_tags,
        f"{EvalTag.SCORER}:{protocol}",
        *declared_model_tags(declared(loaded)),
    ]


def new_batch() -> str:
    """A batch id: the UTC launch time, tag-safe and sortable."""
    return time.strftime("%Y%m%dt%H%M%Sz", time.gmtime())


class _CohortKey(_Read):
    suite_version: str
    workflow_id: str
    workflow_version: str
    models_digest: str
    scorer_protocol: str


class _CaseMetrics(_Read):
    eval_id: str
    n: int
    c: int
    pending: int
    infra_error_count: int
    trials_short: int
    exhausted: bool
    pass_at_k_display: str
    pass_hat_k_display: str
    flaky: bool | None


class _Bounds(_Read):
    display: str


class _Coverage(_Read):
    roster_size: int
    complete: int
    short: int
    never_launched: int


class _CohortMetrics(_Read):
    cohort: _CohortKey
    cases: list[_CaseMetrics]
    coverage: _Coverage
    mean_pass_at_k_display: str
    mean_pass_hat_k_display: str
    partial: bool
    flaky_cases: list[str]
    pass_at_k_bounds: _Bounds
    pass_hat_k_bounds: _Bounds
    infra_error_count: int
    base_mismatch_count: int
    treatment_mismatch_count: int


class _Comparison(_Read):
    a: _CohortKey
    b: _CohortKey
    paired_cases: list[str]
    coverage_complete: bool
    a_only: int
    b_only: int
    both: int
    neither: int
    mcnemar_p: float


class _SetMetrics(_Read):
    suite: str
    version: str
    k: int
    cohorts: list[_CohortMetrics]
    comparison: _Comparison | None = None
    not_a_trial_count: int


def set_metrics(
    loaded: LoadedSuite, client: httpx.Client, k: int, split: Split | None = None
) -> _SetMetrics:
    """The server's figures for this suite version's roster: `GET /eval-sets/metrics`."""
    params: dict[str, str | int] = {
        "suite": loaded.suite.suite_tag.removeprefix(f"{EvalTag.SUITE}:"),
        "version": str(loaded.version),
        "k": k,
    }
    if split is not None:
        params["split"] = split
    return _get(client, _SetMetrics, "/eval-sets/metrics", **params)


def own_cohort(loaded: LoadedSuite, metrics: _SetMetrics, protocol: str) -> _CohortMetrics | None:
    """This launch's cohort in the server's answer; None when it has launched nothing yet.

    Matched on every declared part. Two blocks that differ only in workflow
    version are refused: a top-up cannot tell which treatment it continues.
    """
    digest = declared_model_tags(declared(loaded))[0].removeprefix(f"{EvalTag.MODELS}:")
    want = (str(loaded.version), loaded.workflow.id, digest, protocol)
    mine = [
        c
        for c in metrics.cohorts
        if (
            c.cohort.suite_version,
            c.cohort.workflow_id,
            c.cohort.models_digest,
            c.cohort.scorer_protocol,
        )
        == want
    ]
    if len(mine) > 1:
        versions = sorted(c.cohort.workflow_version for c in mine)
        raise RuntimeError(
            f"{len(mine)} cohorts of {loaded.workflow.id} under scorer {protocol} "
            f"(workflow versions {versions}); bump the suite version instead of topping up"
        )
    return mine[0] if mine else None


def top_up_counts(cohort: _CohortMetrics | None, evals: dict[str, str]) -> dict[str, int]:
    """Trials to launch per case id: exactly the server's `trials_short`. Refused while any is pending.

    The server's count already reserves a pending trial, but a top-up started
    while trials run would launch against figures about to change: refused.
    An exhausted case reports 0 short, so it launches none.
    """
    if cohort is None:
        raise RuntimeError("this cohort has launched nothing yet: launch --trials K first")
    if pending := [c.eval_id for c in cohort.cases if c.pending]:
        raise RuntimeError(
            f"{len(pending)} case(s) have pending trials ({', '.join(pending)}); "
            "top up after they finish and are scored, nothing launched"
        )
    short = {c.eval_id: c.trials_short for c in cohort.cases}
    return {case: short.get(eval_id, 0) for case, eval_id in evals.items()}


def launch_trials(
    loaded: LoadedSuite,
    client: httpx.Client,
    ledger: Path,
    k: int,
    *,
    roster: LoadedSuite | None = None,
    split: Split | None = None,
    top_up: bool = False,
    llm: Judge | None = None,
    root: Path = ROOT,
) -> list[str]:
    """Register the roster, then launch k trials per case (or the server's shortfall) as one cohort.

    `roster` is the whole version (default `loaded`): a `--split` launch still
    registers every case, so the roster never depends on which split ran first.
    Each run is tagged with the cohort key and `trial:<batch>/<i>`, and gets
    one ledger line as it starts, so a launch that dies part way still records
    what it began.
    """
    if problems := trial_problems(loaded, root):
        raise RuntimeError("cannot measure with --trials:\n  " + "\n  ".join(problems))
    protocol = scorer_protocol(loaded, llm)
    batch = new_batch()
    tags = cohort_tags(loaded, protocol)
    try:
        TagSet([*tags, f"{EvalTag.TRIAL}:{batch}/{k}"])
    except InvalidTagsError as exc:
        raise RuntimeError(f"cohort tags are not valid tags: {exc}") from exc

    out = register_roster(roster or loaded, client)
    evals = {case.id: stable_eval(loaded, case, client).eval_id for case in loaded.cases}
    if top_up:
        metrics = set_metrics(loaded, client, k, split)
        counts = top_up_counts(own_cohort(loaded, metrics, protocol), evals)
    else:
        counts = dict.fromkeys(evals, k)
    out.append(install_workflow(loaded, client, root))
    s, w = loaded.suite, loaded.workflow
    for case in loaded.cases:
        if not counts[case.id]:
            out.append(f"{case.id}: no trial short, none launched")
        for i in range(1, counts[case.id] + 1):
            response = client.post(
                f"/workflows/{w.id}/execute",
                json={
                    "task": case.task,
                    "repos": [s.repository],
                    "eval_id": evals[case.id],
                    "tags": [*tags, f"{EvalTag.TRIAL}:{batch}/{i}"],
                },
            )
            response.raise_for_status()
            started = _Started.model_validate(response.json())
            _append_launch(
                ledger,
                Launch(
                    suite=loaded.tag,
                    case=case.id,
                    eval_id=evals[case.id],
                    run_id=started.execution_id,
                    commit=case.commit,
                    workflow_id=w.id,
                    batch=batch,
                    trial=i,
                    scorer=protocol,
                ),
            )
            out.append(f"{case.id}: trial {batch}/{i} -> run {started.execution_id}")
    return out


def _eval_names(loaded: LoadedSuite, client: httpx.Client) -> dict[str, str]:
    """Eval id to case id, for labelling the server's rows."""
    return {
        ev.eval_id: case.id for case in loaded.cases for ev in _case_evals(client, loaded, case)
    }


def render_metrics(metrics: _SetMetrics, case_of: dict[str, str]) -> str:
    """The server's figures, as the server computed them. Nothing here is a calculation.

    `case_of` maps an eval id to its case id, for the row labels only.
    """
    lines = [f"## {metrics.suite} v{metrics.version}, k = {metrics.k} (GET /eval-sets/metrics)"]
    if not metrics.cohorts:
        lines.append("no cohort has launched into this roster")
    for c in metrics.cohorts:
        key = c.cohort
        lines += [
            "",
            f"### {key.workflow_id} {key.workflow_version or '(unversioned)'}, "
            f"models {key.models_digest[:12]}, scorer {key.scorer_protocol}",
            f"coverage {c.coverage.complete}/{c.coverage.roster_size} complete, "
            f"{c.coverage.short} short, {c.coverage.never_launched} never launched"
            + (" (partial: the means are descriptive)" if c.partial else ""),
            f"pass@k {c.mean_pass_at_k_display} (bounds {c.pass_at_k_bounds.display}); "
            f"pass^k {c.mean_pass_hat_k_display} (bounds {c.pass_hat_k_bounds.display})",
            f"infra errors {c.infra_error_count}, base mismatches {c.base_mismatch_count}, "
            f"treatment mismatches {c.treatment_mismatch_count}, "
            f"flaky {', '.join(case_of.get(e, e) for e in c.flaky_cases) or 'none'}",
            "",
            "| case | n | pass | pending | infra | short | pass@k | pass^k | flaky |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for m in c.cases:
            short = "exhausted" if m.exhausted else str(m.trials_short)
            lines.append(
                f"| {case_of.get(m.eval_id, m.eval_id)} | {m.n} | {m.c} | {m.pending} | "
                f"{m.infra_error_count} | {short} | {m.pass_at_k_display} | "
                f"{m.pass_hat_k_display} | {'yes' if m.flaky else '-'} |"
            )
    if cmp := metrics.comparison:
        lines += [
            "",
            f"### paired: {cmp.a.workflow_id} vs {cmp.b.workflow_id}",
            f"{len(cmp.paired_cases)} paired; a only {cmp.a_only}, b only {cmp.b_only}, "
            f"both {cmp.both}, neither {cmp.neither}; McNemar p = {cmp.mcnemar_p:.3g}"
            + ("" if cmp.coverage_complete else " (coverage incomplete: inconclusive)"),
        ]
    if metrics.not_a_trial_count:
        lines.append(f"\n{metrics.not_a_trial_count} member run(s) are not trials of any cohort")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("check", "register", "launch", "score"))
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
        "--llm-judge",
        action="store_true",
        help=(
            f"score: also ask the LLM judge ({JUDGE_MODEL}, majority of {JUDGE_SAMPLES}, "
            f"prompt v{JUDGE_PROMPT_VERSION}); "
            "runs through the logged-in `claude` CLI (claude -p). Recorded under a scorer_version naming the judge. "
            "Omit to score offline by keywords alone"
        ),
    )
    parser.add_argument(
        "--launches",
        type=Path,
        default=None,
        help="launch ledger launch appends to and score reads (default <suite>/launches.jsonl)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        nargs="?",
        const=DEFAULT_TRIALS,
        default=None,
        metavar="K",
        help=(
            f"k trials per case (default {DEFAULT_TRIALS}): launch k runs per case as one "
            "cohort; score then prints the server's pass@k / pass^k; check refuses model "
            "aliases"
        ),
    )
    parser.add_argument(
        "--top-up",
        action="store_true",
        help="launch --trials: launch only the server's trials_short per case; "
        "refused while any trial is pending",
    )
    args = parser.parse_args(argv)
    if args.top_up and not (args.command == "launch" and args.trials):
        print("❌ --top-up is for `launch --trials K`", file=sys.stderr)
        return 1
    if args.trials is not None and args.trials < 1:
        print("❌ --trials K needs K >= 1", file=sys.stderr)
        return 1

    to_score: list[LoadedSuite] = []
    try:
        loaded = load_suite(args.suite, workflow=args.workflow, split=args.split)
        # The roster is the whole version, whichever split a launch runs.
        roster = load_suite(args.suite, workflow=loaded.workflow.id)
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
        problems += [p for ref in loaded.suite.workflows for p in pin_safety_problems(ref)]
        if args.trials is not None:
            problems += alias_problems(loaded)
        if problems:
            print("❌ " + "\n❌ ".join(problems), file=sys.stderr)
            return 1
        print(f"✅ {loaded.tag}: {len(loaded.cases)} case(s), every pinned commit and file checked")
        if args.command == "check":
            print("\n".join(describe_launch(loaded)))
            return 0

    llm: Judge | None = None
    if args.llm_judge and (args.command == "score" or args.trials is not None):
        if problems := [p for v in to_score for p in judge_problems(v)]:
            print("❌ the LLM judge cannot score:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        llm = LlmJudge(HeadlessJudgeClient())
    ledger: Path = args.launches or launches_path(args.suite)
    with httpx.Client(
        base_url=args.api_url or get_dev_api_url(), timeout=60, auth=_basic_auth()
    ) as client:
        if args.command == "register":
            try:
                print("\n".join(register_roster(roster, client)))
            except RuntimeError as exc:
                print(f"❌ {exc}", file=sys.stderr)
                return 1
            return 0
        if args.command == "launch":
            if args.trials is None:
                print("\n".join(launch_suite(loaded, client, ledger)))
            else:
                try:
                    out = launch_trials(
                        loaded,
                        client,
                        ledger,
                        args.trials,
                        roster=roster,
                        split=args.split,
                        top_up=args.top_up,
                        llm=llm,
                    )
                except RuntimeError as exc:
                    print(f"❌ {exc}", file=sys.stderr)
                    return 1
                print("\n".join(out))
            print(f"recorded in {ledger}: commit it, `score` reads only the runs it names")
            return 0
        launches = read_launches(ledger)
        tables = [(v, *score_suite(v, client, launches, llm)) for v in to_score]
        figures = (
            [
                (set_metrics(v, client, args.trials, args.split), _eval_names(v, client))
                for v in to_score
            ]
            if args.trials is not None
            else []
        )
    print("\n\n".join(render(v, rows, unrecorded) for v, rows, unrecorded in tables))
    for metrics, names in figures:
        print("\n" + render_metrics(metrics, names))
    return (
        0
        if all(rows and all(r.score and r.score.passed for r in rows) for _, rows, _ in tables)
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
