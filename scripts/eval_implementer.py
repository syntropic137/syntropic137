#!/usr/bin/env python3
"""Check, admit and score the IMPLEMENTER eval kind (research #1725).

An implementer case is a real merged fix turned back into a task. The agent
gets the tree just before the fix (``commit``, the merge's first parent) and
the issue's statement of the problem, with the fix's own description of the
solution removed. The tests the fix PR added or changed are HIDDEN: they are
not in the agent's checkout at ``commit``, and they are what scores it.

    uv run python scripts/eval_implementer.py check [--suite DIR]
    uv run python scripts/eval_implementer.py admit [--suite DIR] [--case ID]
    uv run python scripts/eval_implementer.py score --case ID --patch FILE [--suite DIR]
    uv run python scripts/eval_implementer.py prepare --case ID --out DIR [--suite DIR]
    uv run python scripts/eval_implementer.py score --prepared DIR --patch FILE

SCORE. What PASS, FAIL and ERROR mean, and how the hidden tests are defended
against the patch, is ``scripts/implementer_scorer.py``'s docstring: scoring
lives there, standard library only, so the referee can run it in a container.
``prepare`` and ``score --prepared`` are its two halves, network on and then
off; ``scripts/eval_referee.py`` runs them in a throwaway container from the
pinned workspace image, which is how an agent's patch is scored (#2108 S4).
Exit status of ``score``: 0 PASS, 1 FAIL, 2 ERROR.

ADMISSION. A case belongs in the suite only if its hidden tests discriminate:
``admit`` scores the empty patch (must FAIL: the tests catch the bug at the
pin) and the fix's own non-test diff (must PASS: the tests are satisfiable).
A case that does not hold both is not a case. ``check`` is the offline,
git-only half: shapes, SHAs, ancestry, hidden files present at the fix and the
task not naming the fix's PR.

WHERE IT RUNS. ``score`` runs the agent's code, so it never runs on the API
host. ``admit`` runs only the fix's own code and may run on a host.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

import yaml
from eval_suite import ROOT, DefinitionError, Suite, _read_yaml, _workflow_problems
from implementer_scorer import Pin, git, prepare, read_patch, report, score_patch, score_prepared
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEFAULT_SUITE = ROOT / "evals" / "implementer-seed-v1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ImplementerCase(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    source_pr: int = Field(ge=1)
    """The PR that shipped the fix. Never put it in `task`: the agent could fetch it."""
    source_issue: int | None = Field(default=None, ge=1)
    """The issue the task's text is taken from, when there is one."""
    commit: str
    """Full SHA the agent's workspace is pinned to: `fix_commit`'s first parent."""
    fix_commit: str
    """Full SHA of the merge that shipped the fix. The hidden tests are read from here."""
    task: str = Field(min_length=1)
    """The problem as the issue states it, with the fix's description of the solution removed."""
    hidden_tests: tuple[str, ...] = Field(min_length=1)
    """Repo-relative pytest files the fix PR added or changed, run at their `fix_commit` content."""

    @field_validator("commit", "fix_commit")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"{value!r} is not a full 40-character lowercase SHA")
        return value

    def pin(self) -> Pin:
        """What the scorer needs from this case."""
        return Pin(
            id=self.id,
            commit=self.commit,
            fix_commit=self.fix_commit,
            hidden_tests=self.hidden_tests,
        )


class ImplementerSuite(_Frozen):
    suite: Suite
    cases: tuple[ImplementerCase, ...]

    def case(self, case_id: str) -> ImplementerCase:
        for case in self.cases:
            if case.id == case_id:
                return case
        raise DefinitionError(f"no case {case_id!r}; the suite holds {[c.id for c in self.cases]}")


def load_suite(directory: Path, root: Path = ROOT) -> ImplementerSuite:
    """Parse a suite and check it against its workflow file. Raises `DefinitionError`."""
    try:
        suite = Suite.model_validate(_read_yaml(directory / "suite.yaml"))
        case_files = sorted((directory / "cases").glob("*.yaml"))
        cases = tuple(ImplementerCase.model_validate(_read_yaml(p)) for p in case_files)
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
    for ref in suite.workflows:
        problems.extend(_workflow_problems(ref, root))
    if problems:
        raise DefinitionError("\n".join(problems))
    return ImplementerSuite(suite=suite, cases=cases)


_git = git


def check_commits(loaded: ImplementerSuite, repo: Path) -> list[str]:
    """What git says is wrong with each case: missing SHAs, wrong parent, absent tests."""
    problems: list[str] = []
    for case in loaded.cases:
        missing = [
            sha
            for sha in (case.commit, case.fix_commit)
            if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0
        ]
        if missing:
            problems.append(f"{case.id}: commit(s) {missing} not in {repo}")
            continue
        parent = _git(repo, "rev-parse", f"{case.fix_commit}^1").stdout.strip()
        if parent != case.commit:
            problems.append(f"{case.id}: commit is not fix_commit's first parent ({parent})")
        for path in case.hidden_tests:
            if _git(repo, "cat-file", "-e", f"{case.fix_commit}:{path}").returncode != 0:
                problems.append(f"{case.id}: hidden test {path} is not in fix_commit")
        problems.extend(unstated_contract_problems(case, repo))
    return problems


class Contracts(_Frozen):
    """What a hidden test relies on by exact spelling. A correct fix that spells any
    of them differently fails, so each must be visible to the agent (#2023)."""

    names: frozenset[str]
    """Names imported from a `syn_*` package, and attribute names monkeypatched by string."""
    literals: frozenset[str]
    """Text in `assert "<text>" in ...` and `raises(match=...)` (`not in` needs no statement)."""
    attributes: frozenset[str]
    """Attributes the test reads that the test itself does not define."""
    patched: frozenset[tuple[str, str]]
    """(dotted `syn_*` target, attribute) pairs a test monkeypatches. The attribute
    must exist on that target at the pin: a fixture that patches a name only the
    fix adds errors every test that uses it, whatever the patch does."""


def asserted_contracts(source: str) -> Contracts:
    """Read a hidden test's exact spellings from its AST."""
    tree = ast.parse(source)
    imported = _syn_imports(tree)
    patched: set[tuple[str, str]] = set()
    names: set[str] = set()
    literals: set[str] = set()
    read: set[str] = set()
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("syn_"):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                names.add(node.args[1].value)
                target = _dotted(node.args[0], imported)
                if target is not None:
                    patched.add((target, node.args[1].value))
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "setattr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("syn_")
                and "." in node.args[0].value
            ):
                owner, _, attribute = node.args[0].value.rpartition(".")
                patched.add((owner, attribute))
            for keyword in node.keywords:
                if (
                    keyword.arg == "match"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    literals.add(re.sub(r"\\(.)", r"\1", keyword.value.value))
        elif (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
            and any(isinstance(op, ast.In) for op in node.ops)
        ):
            literals.add(node.left.value)
        if isinstance(node, ast.Attribute):
            (read if isinstance(node.ctx, ast.Load) else defined).add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
    attributes = {a for a in read - defined if not a.startswith("__")}
    return Contracts(
        names=frozenset(names),
        literals=frozenset(literals),
        attributes=frozenset(attributes),
        patched=frozenset(patched),
    )


def _syn_imports(tree: ast.Module) -> dict[str, str]:
    """Local name -> dotted path, for every name the test imports from a `syn_*` package."""
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("syn_"):
            for alias in node.names:
                imported[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("syn_"):
                    continue
                if alias.asname:
                    imported[alias.asname] = alias.name
                else:
                    # `import syn_a.b.c` binds `syn_a`; the rest is reached by attribute.
                    root = alias.name.split(".")[0]
                    imported[root] = root
    return imported


def _dotted(expr: ast.expr, imported: dict[str, str]) -> str | None:
    """The dotted `syn_*` path an expression names, through attribute chains.

    `client_retry` (from-imported), `cr` (`import ... as cr`) and
    `syn_adapters.github.client_retry` (plain `import`) all resolve to
    `syn_adapters.github.client_retry`. Anything rooted elsewhere is None.
    """
    attributes: list[str] = []
    while isinstance(expr, ast.Attribute):
        attributes.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name) or expr.id not in imported:
        return None
    return ".".join([imported[expr.id], *reversed(attributes)])


def _module_names(body: list[ast.stmt]) -> set[str]:
    """Names a module or class body binds, through `if` and `try` blocks."""
    bound: set[str] = set()
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            bound.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.If):
            bound |= _module_names(node.body) | _module_names(node.orelse)
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody):
                bound |= _module_names(block)
            for handler in node.handlers:
                bound |= _module_names(handler.body)
    return bound


def _patched_absent_at_pin(
    repo: Path, commit: str, patched: frozenset[tuple[str, str]]
) -> frozenset[tuple[str, str]]:
    """The monkeypatch targets whose attribute the pin does not define.

    A target is a module (`client_retry`) or a class in one
    (`syn_adapters.github.client.GitHubAppClient`). A target whose module the pin
    does not have at all is new in the fix, so its interface is the task's to
    state and the import check covers it; it is not reported here.
    """
    if not patched:
        return frozenset()
    files = set(_git(repo, "ls-tree", "-r", "--name-only", commit).stdout.splitlines())

    def source_of(dotted: str) -> str | None:
        rel = dotted.replace(".", "/")
        for path in sorted(files):
            if path.endswith((f"/src/{rel}.py", f"/src/{rel}/__init__.py")):
                return _git(repo, "show", f"{commit}:{path}").stdout
        return None

    absent: set[tuple[str, str]] = set()
    for target, attribute in patched:
        module = source_of(target)
        if module is not None:
            body = ast.parse(module).body
        else:
            owner, _, cls = target.rpartition(".")
            parent = source_of(owner) if owner else None
            if parent is None:
                continue
            classes = [
                n for n in ast.parse(parent).body if isinstance(n, ast.ClassDef) and n.name == cls
            ]
            if not classes:
                continue
            body = classes[0].body
        if attribute not in _module_names(body):
            absent.add((target, attribute))
    return frozenset(absent)


def _attributes_at_pin(
    repo: Path, commit: str, attributes: frozenset[str]
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Which of `attributes` code at the pin defines or reads, and what went unsearched.

    A bare word is not enough: `unsettled` existed at a pin only as an unrelated
    local variable while the hidden test read `error.unsettled`. Submodules are
    searched at their gitlinks. One with no local clone cannot be searched, so its
    path is returned and the check reports itself incomplete instead of passing.
    """
    if not attributes:
        return frozenset(), ()
    names = "|".join(sorted(re.escape(a) for a in attributes))
    pattern = rf"\.(?:{names})\b|\bdef (?:{names})\b|^\s+(?:{names})\s*:\s*[A-Za-z_\[]"
    word = re.compile(rf"(?:{names})\b")

    def found_in(at: Path, sha: str) -> set[str]:
        out = _git(at, "grep", "-h", "-o", "-P", pattern, sha, "--", "*.py").stdout
        return {m.group(0) for m in word.finditer(out)}

    seen = found_in(repo, commit)
    unsearched: list[str] = []
    modules = _git(repo, "config", "--blob", f"{commit}:.gitmodules", "--get-regexp", r"\.path$")
    for line in modules.stdout.splitlines():
        _, path = line.split(maxsplit=1)
        parts = _git(repo, "ls-tree", commit, path).stdout.split()
        if len(parts) < 3 or parts[1] != "commit":
            continue
        sub = repo / path
        if (sub / ".git").exists():
            seen |= found_in(sub, parts[2])
        else:
            unsearched.append(path)
    return frozenset(seen & attributes), tuple(unsearched)


def unstated_contract_problems(case: ImplementerCase, repo: Path) -> list[str]:
    """Spellings a hidden test needs that are neither in the task nor at the pin."""
    problems: list[str] = []
    for path in case.hidden_tests:
        shown = _git(repo, "show", f"{case.fix_commit}:{path}")
        if shown.returncode != 0:
            continue
        found = asserted_contracts(shown.stdout)
        for name in sorted(found.names):
            seen = _git(repo, "grep", "-q", "-w", "-F", name, case.commit, "--", ".")
            if name not in case.task and seen.returncode != 0:
                problems.append(f"{case.id}: {path} needs name {name!r}, absent from task and pin")
        for literal in sorted(found.literals):
            seen = _git(repo, "grep", "-q", "-F", literal, case.commit, "--", ".")
            if literal not in case.task and seen.returncode != 0:
                problems.append(
                    f"{case.id}: {path} asserts text {literal!r}, absent from task and pin"
                )
        unpatchable = frozenset(p for p in found.patched if p[1] not in case.task)
        for target, attribute in sorted(_patched_absent_at_pin(repo, case.commit, unpatchable)):
            problems.append(
                f"{case.id}: {path} monkeypatches {target}.{attribute}, which the pin does not"
                " define and the task never states"
            )
        unstated = frozenset(a for a in found.attributes if a not in case.task)
        at_pin, unsearched = _attributes_at_pin(repo, case.commit, unstated)
        missing = unstated - at_pin
        if missing and unsearched:
            problems.append(
                f"{case.id}: {path} reads {sorted(missing)!r}, not found, and submodule(s)"
                f" {', '.join(unsearched)} could not be searched (no local clone):"
                " the contract check is incomplete; run `git submodule update --init`"
            )
            continue
        for attribute in sorted(missing):
            problems.append(
                f"{case.id}: {path} reads attribute {attribute!r}, absent from task and pin"
            )
    return problems


def fix_patch(case: ImplementerCase, repo: Path) -> str:
    """The fix's own change without its hidden tests: the reference solution."""
    excluded = [f":(exclude){path}" for path in case.hidden_tests]
    return _git(repo, "diff", "--binary", case.commit, case.fix_commit, "--", ".", *excluded).stdout


def admit(case: ImplementerCase, repo: Path) -> list[str]:
    """Why the case does not discriminate: empty if its hidden tests FAIL at the pin and PASS at the fix."""
    problems: list[str] = []
    for label, patch, required in (
        ("the pin", "", "FAIL"),
        ("the fix", fix_patch(case, repo), "PASS"),
    ):
        run = score_patch(case.pin(), patch, repo)
        last = run.detail.strip().splitlines()[-1] if run.detail.strip() else ""
        print(f"{case.id}: {run.outcome} at {label}: {last}")
        if run.outcome != required:
            problems.append(
                f"{case.id}: hidden tests at {label} must {required}, got {run.outcome}\n{run.detail}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("command", choices=["check", "admit", "score", "prepare"])
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--repo", type=Path, default=ROOT, help="git repository holding every pin")
    parser.add_argument(
        "--case", help="case id (score, prepare: required; admit: default every case)"
    )
    parser.add_argument("--patch", type=Path, help="score: the agent's unified diff")
    parser.add_argument("--out", type=Path, help="prepare: a fresh directory to prepare")
    parser.add_argument(
        "--prepared", type=Path, help="score: a directory `prepare` built; never syncs"
    )
    args = parser.parse_args(argv)

    if args.command == "score" and args.prepared is not None:
        if args.patch is None:
            parser.error("score --prepared needs --patch")
        return report(score_prepared(args.prepared, read_patch(args.patch)))
    try:
        loaded = load_suite(args.suite)
        if args.command == "score":
            if args.case is None or args.patch is None:
                parser.error("score needs --case and --patch, or --prepared and --patch")
            pin = loaded.case(args.case).pin()
            return report(score_patch(pin, read_patch(args.patch), args.repo))
        if args.command == "prepare":
            if args.case is None or args.out is None:
                parser.error("prepare needs --case and --out")
            failed = prepare(loaded.case(args.case).pin(), args.repo, args.out)
            if failed is not None:
                return report(failed)
            print(f"prepared {args.case} in {args.out}")
            return 0
        problems = check_commits(loaded, args.repo)
        if args.command == "admit" and not problems:
            chosen = [loaded.case(args.case)] if args.case else list(loaded.cases)
            for case in chosen:
                found = admit(case, args.repo)
                print(f"{case.id}: {'admitted' if not found else 'NOT admitted'}")
                problems.extend(found)
    except DefinitionError as exc:
        print(f"suite definition is invalid:\n{exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"{loaded.suite.id} v{loaded.suite.version}: {len(loaded.cases)} case(s) OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
