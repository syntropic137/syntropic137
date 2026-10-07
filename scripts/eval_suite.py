#!/usr/bin/env python3
"""Check, launch and score a versioned eval suite (#967 step 8).

A suite lives in ``evals/<suite-id>/``: ``suite.yaml`` names the workflow and
the models it declares, and ``cases/*.yaml`` holds one case each - a commit
that carries a known bug and what a report must say to have found it.

ONE EVAL PER CASE. A run's commit comes from its eval's Baseline, which holds
one SHA per repository and is fixed at create. The cases are one repository at
different commits, so each case is its own eval, and the suite is the set of
evals carrying the suite's tag.

    uv run python scripts/eval_suite.py check  [--suite DIR]   # offline dry run
    uv run python scripts/eval_suite.py launch [--suite DIR] [--api-url URL]
    uv run python scripts/eval_suite.py score  [--suite DIR] [--api-url URL]

``check`` needs only git. ``launch`` creates the evals and starts real agent
runs, which cost money: never run it from CI. ``score`` only reads.

Exit status: 0 on success (for ``score``: every case scored pass), 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_shared.settings.dev_tooling import get_dev_api_url

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE = ROOT / "evals" / "verifier-seed-v1"
_SHA = re.compile(r"^[0-9a-f]{40}$")


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


class Suite(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9._/:-]+$")
    version: int = Field(ge=1)
    goal: str = Field(min_length=1)
    repository: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    workflow: WorkflowRef

    @property
    def tag(self) -> str:
        """The tag every eval of this suite version carries; `score` finds them by it."""
        return f"{self.id}:v{self.version}"


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


class Case(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    source_pr: int = Field(ge=1)
    """The PR that shipped the bug. Never put it in `task`: the agent could fetch the fix."""
    commit: str
    """Full SHA the run is pinned to. The bug is present here."""
    fix_commit: str
    """Full SHA of the commit that fixed it; `commit` must be its ancestor."""
    task: str = Field(min_length=1)
    expected: Expected

    @field_validator("commit", "fix_commit")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        if not _SHA.fullmatch(value):
            raise ValueError(f"{value!r} is not a full 40-character lowercase SHA")
        return value

    @property
    def tag(self) -> str:
        return f"case:{self.id}"


class LoadedSuite(_Frozen):
    suite: Suite
    cases: tuple[Case, ...]


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


def load_suite(directory: Path, root: Path = ROOT) -> LoadedSuite:
    """Parse and cross-check a suite. Raises `DefinitionError` naming every problem found."""
    try:
        suite = Suite.model_validate(_read_yaml(directory / "suite.yaml"))
        case_files = sorted((directory / "cases").glob("*.yaml"))
        cases = tuple(Case.model_validate(_read_yaml(p)) for p in case_files)
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise DefinitionError(str(exc)) from exc

    problems: list[str] = []
    if not cases:
        problems.append(f"{directory}/cases holds no case")
    for path, case in zip(case_files, cases, strict=True):
        if path.stem != case.id:
            problems.append(f"{path.name}: file name must be the case id {case.id!r}")
        if f"#{case.source_pr}" in case.task:
            problems.append(f"{case.id}: task names #{case.source_pr}; the agent could fetch the fix")
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        problems.append(f"duplicate case ids: {sorted(ids)}")

    workflow_file = root / suite.workflow.path
    try:
        definition = WorkflowDefinition.from_file(workflow_file)
    except (OSError, ValidationError, ValueError) as exc:
        problems.append(f"workflow {suite.workflow.path}: {exc}")
    else:
        if definition.id != suite.workflow.id:
            problems.append(f"workflow id is {definition.id!r}, suite says {suite.workflow.id!r}")
        actual = declared_models(workflow_file)
        if actual != suite.workflow.models:
            problems.append(
                f"suite records models {suite.workflow.models}, the workflow declares {actual}; "
                "update both and bump the suite version"
            )
    if problems:
        raise DefinitionError("\n".join(problems))
    return LoadedSuite(suite=suite, cases=cases)


# ---------------------------------------------------------------------------
# check: the offline dry run
# ---------------------------------------------------------------------------


def _git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode == 0


def check_commits(loaded: LoadedSuite, repo: Path) -> list[str]:
    """Problems with each case's pinned history in `repo`; empty when every case holds.

    For each case: both SHAs are commits here, the pin is an ancestor of the
    fix, every expected file exists at the pin, and the fix changes at least
    one of them - so the files are where the bug lived, not a guess.
    """
    problems: list[str] = []
    for case in loaded.cases:
        missing = [s for s in (case.commit, case.fix_commit) if not _git_ok(repo, "cat-file", "-e", f"{s}^{{commit}}")]
        if missing:
            problems.append(f"{case.id}: no such commit {', '.join(missing)} (try `git fetch origin`)")
            continue
        if not _git_ok(repo, "merge-base", "--is-ancestor", case.commit, case.fix_commit):
            problems.append(f"{case.id}: {case.commit[:12]} is not an ancestor of the fix {case.fix_commit[:12]}")
        for path in case.expected.files:
            if not _git_ok(repo, "cat-file", "-e", f"{case.commit}:{path}"):
                problems.append(f"{case.id}: {path} does not exist at {case.commit[:12]}")
        changed = subprocess.run(
            ["git", "-C", str(repo), "diff", "--name-only", case.commit, case.fix_commit],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        if not set(case.expected.files) & set(changed):
            problems.append(f"{case.id}: the fix changes none of {list(case.expected.files)}")
    return problems


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

Verdict = Literal["certified", "blocked"]


class Score(_Frozen):
    verdict: Verdict | None
    named_file: str | None
    """The first expected file the report names, by file name."""
    missing_keywords: tuple[tuple[str, ...], ...]
    """Keyword groups no word of which the report contains."""

    @property
    def matched(self) -> bool:
        return self.named_file is not None and not self.missing_keywords

    @property
    def passed(self) -> bool:
        return self.verdict == "blocked" and self.matched


def score_report(expected: Expected, verdict: Verdict | None, report: str) -> Score:
    """Pass = the run's verdict is blocked AND the report names the defect.

    Naming it means: one of the expected files appears by file name, and every
    keyword group has at least one word in the report (case-insensitive).
    """
    lowered = report.lower()
    named = next((f for f in expected.files if Path(f).name in report), None)
    missing = tuple(g for g in expected.keywords if not any(w.lower() in lowered for w in g))
    return Score(verdict=verdict, named_file=named, missing_keywords=missing)


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
    workflow_execution_id: str


class _RunList(_Read):
    executions: list[_RunSummary]


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


class _Created(_Read):
    eval_id: str
    baseline_repos: list[_BaselineRepo]


class _Started(_Read):
    execution_id: str


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


def score_suite(loaded: LoadedSuite, client: httpx.Client) -> list[ScoredRun]:
    """One row per run of every eval carrying the suite's tag, and one per case with no run."""
    evals = _get(client, _EvalList, "/evals", tag=loaded.suite.tag, page_size=200).evals
    rows: list[ScoredRun] = []
    for case in loaded.cases:
        mine = [e for e in evals if case.tag in e.tags]
        if not mine:
            rows.append(ScoredRun(case=case.id, eval_id="-", run_id=None, status="not launched",
                                  score=None, cost_usd=None, duration="-", models="-"))
        for ev in mine:
            runs = _get(client, _RunList, f"/evals/{ev.eval_id}/runs", page_size=200).executions
            if not runs:
                rows.append(ScoredRun(case=case.id, eval_id=ev.eval_id, run_id=None, status="no run",
                                      score=None, cost_usd=None, duration="-", models="-"))
            for summary in runs:
                run = _get(client, _Execution, f"/executions/{summary.workflow_execution_id}")
                score = score_report(case.expected, run.review_verdict, _report_of(client, run))
                rows.append(ScoredRun(case=case.id, eval_id=ev.eval_id, run_id=run.workflow_execution_id,
                                      status=run.status, score=score, cost_usd=run.total_cost_usd,
                                      duration=_duration_of(run), models=_models_of(run)))
    return rows


def render(loaded: LoadedSuite, rows: list[ScoredRun]) -> str:
    header = ("case", "run id", "status", "verdict", "matched", "pass", "cost", "duration", "models")
    lines = [header]
    for r in rows:
        s = r.score
        lines.append((
            r.case,
            r.run_id or "-",
            r.status,
            (s.verdict or "none") if s else "-",
            ("yes" if s.matched else f"no{'' if s.named_file else ' (file)'}"
             f"{' (keywords: ' + '; '.join('/'.join(g) for g in s.missing_keywords) + ')' if s.missing_keywords else ''}")
            if s else "-",
            ("PASS" if s.passed else "FAIL") if s else "-",
            f"${r.cost_usd:.2f}" if r.cost_usd is not None else "-",
            r.duration,
            r.models,
        ))
    widths = [max(len(row[i]) for row in lines) for i in range(len(header))]
    table = "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in lines)
    passed = sum(1 for r in rows if r.score and r.score.passed)
    return (f"suite {loaded.suite.tag}  workflow {loaded.suite.workflow.id}  "
            f"declared models {loaded.suite.workflow.models}\n\n{table}\n\n{passed}/{len(rows)} passed")


# ---------------------------------------------------------------------------
# launch
# ---------------------------------------------------------------------------


def launch_suite(loaded: LoadedSuite, client: httpx.Client) -> list[str]:
    """Create one pinned eval per case and start its run. Returns a line per case."""
    s = loaded.suite
    out: list[str] = []
    for case in loaded.cases:
        response = client.post("/evals", json={
            "name": f"{s.id} v{s.version}: {case.id}",
            "goal": s.goal,
            "starting_workflow_id": s.workflow.id,
            "baseline_repos": [{"repository": s.repository, "requested_ref": case.commit}],
            "tags": [s.tag, case.tag, f"workflow:{s.workflow.id}"],
        })
        response.raise_for_status()
        created = _Created.model_validate(response.json())
        pinned = [b.commit_sha for b in created.baseline_repos]
        if pinned != [case.commit]:
            raise RuntimeError(f"{case.id}: eval {created.eval_id} pinned {pinned}, expected {case.commit}")
        response = client.post(f"/workflows/{s.workflow.id}/execute", json={
            "task": case.task,
            "repos": [s.repository],
            "eval_id": created.eval_id,
        })
        response.raise_for_status()
        started = _Started.model_validate(response.json())
        out.append(f"{case.id}: eval {created.eval_id} @ {case.commit[:12]} -> run {started.execution_id}")
    return out


def describe_launch(loaded: LoadedSuite) -> list[str]:
    """What `launch` would send, one line per case. Writes nothing."""
    s = loaded.suite
    return [
        f"{c.id}: POST /evals baseline {s.repository}@{c.commit} tags [{s.tag}, {c.tag}]; "
        f"then POST /workflows/{s.workflow.id}/execute with that eval_id"
        for c in loaded.cases
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "launch", "score"))
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--repo", type=Path, default=ROOT, help="git checkout holding the pinned commits")
    parser.add_argument("--api-url", default=None, help="defaults to DEV__API_URL / localhost")
    args = parser.parse_args(argv)

    try:
        loaded = load_suite(args.suite)
    except DefinitionError as exc:
        print(f"❌ {args.suite}:\n{exc}", file=sys.stderr)
        return 1

    if args.command in ("check", "launch"):
        problems = check_commits(loaded, args.repo)
        if problems:
            print("❌ " + "\n❌ ".join(problems), file=sys.stderr)
            return 1
        print(f"✅ {loaded.suite.tag}: {len(loaded.cases)} case(s), every pinned commit and file checked")
        if args.command == "check":
            print("\n".join(describe_launch(loaded)))
            return 0

    with httpx.Client(base_url=args.api_url or get_dev_api_url(), timeout=60) as client:
        if args.command == "launch":
            print("\n".join(launch_suite(loaded, client)))
            return 0
        rows = score_suite(loaded, client)
    print(render(loaded, rows))
    return 0 if rows and all(r.score and r.score.passed for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
