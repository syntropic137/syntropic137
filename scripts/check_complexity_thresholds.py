#!/usr/bin/env python3
"""The APS `max-loc-file` and `max-cyclomatic` thresholds, for Python, in seconds (#1585).

`just fitness-check` measures these with the Rust aps binary after a full
topology regeneration, which costs minutes in a cold workspace. They are the
two thresholds agents most often fail, so `preflight-agent` checks them here
first, before anything compiles.

This is the SAME measurement, not a lookalike. It reads the thresholds,
excludes and waivers from `fitness.toml` and `fitness-exceptions.toml`, and
reproduces what `apss-dev run code-topology analyze` writes for Python
(lib/agent-paradise-standards-system/.../APS-V1-0001-code-topology):

- Files: the analyzer's directory walk, with its skip rules (`_skipped`).
- Function cyclomatic: 1 + the tree-sitter `decision_nodes` of
  `grammars/python.rs`, mapped onto `ast` (`_decisions`). Subtrees under the
  grammar's `ignored_nodes` (finally, raise) count nothing; nested functions
  and lambdas count toward the function that holds them.
- Module LOC: NOT lines in the file. `modules.json` sums each function's
  total line span (`def` line to last line, nested functions counted again),
  so a file with no functions has no module entry at all.

`scripts/tests/test_check_complexity_thresholds.py` pins the equivalence
against the aps binary on this tree and on an over-limit fixture. APS still
runs in full afterwards (`fitness-agent`); this only fails sooner. TypeScript
is not measured here: those functions are checked by APS alone.

Usage: check_complexity_thresholds.py [ROOT]   (exit 1 on any violation)
"""

from __future__ import annotations

import ast
import os
import sys
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

# The rules this module knows how to measure, and the APS field each one reads.
# A rule whose field changes in fitness.toml means something else now, so it
# fails loudly rather than being measured the old way.
_RULE_FIELDS = {"max-cyclomatic": "metrics.cyclomatic", "max-loc-file": "metrics.lines_of_code"}
_SKIPPED_DIRS = {"target", "node_modules", "__pycache__", "tests", "venv"}


@dataclass(frozen=True)
class Rule:
    id: str
    max: float
    exclude: tuple[str, ...]

    def excludes(self, entity: str) -> bool:
        return any(fnmatchcase(entity, pattern) for pattern in self.exclude)


@dataclass(frozen=True)
class Measurement:
    rule: str
    entity: str
    value: int


@dataclass(frozen=True)
class Violation:
    measurement: Measurement
    limit: float

    def __str__(self) -> str:
        m = self.measurement
        return f"{m.rule}: {m.entity} = {m.value} (limit {self.limit:g})"


def load_rules(root: Path) -> dict[str, Rule]:
    config = tomllib.loads((root / "fitness.toml").read_text())
    rules: dict[str, Rule] = {}
    for raw in config["rules"]["threshold"]:
        if raw["id"] not in _RULE_FIELDS:
            continue
        if raw["field"] != _RULE_FIELDS[raw["id"]]:
            raise SystemExit(f"{raw['id']} now reads {raw['field']!r}; update {__file__}")
        rules[raw["id"]] = Rule(raw["id"], float(raw["max"]), tuple(raw.get("exclude", ())))
    missing = _RULE_FIELDS.keys() - rules.keys()
    if missing:
        raise SystemExit(f"fitness.toml has no {sorted(missing)} rule; update {__file__}")
    return rules


def load_waivers(root: Path) -> dict[tuple[str, str], float]:
    config = tomllib.loads((root / "fitness-exceptions.toml").read_text())
    return {
        (rule, entity): float(entry["value"])
        for rule in _RULE_FIELDS
        for entity, entry in config.get(rule, {}).items()
        if "value" in entry
    }


def _skipped(name: str) -> bool:
    # cli/analyze.rs `filter_entry`, applied to directories and files alike.
    return (
        name.startswith((".", "test_"))
        or name in _SKIPPED_DIRS
        or name.endswith(("_test.rs", "_test.py"))
    )


def python_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skipped(d))
        found.extend(
            Path(dirpath, f)
            for f in sorted(filenames)
            if f.endswith((".py", ".pyi")) and not _skipped(f)
        )
    return found


def module_id(path: Path, root: Path) -> str:
    # grammars/python.rs `compute_module_path`.
    dotted = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
    for suffix in (".__init__", ".__main__"):
        dotted = dotted.removesuffix(suffix)
    return dotted


def _is_elif(node: ast.If, lines: list[str]) -> bool:
    return lines[node.lineno - 1][node.col_offset :].startswith("elif")


def _decisions(node: ast.AST, lines: list[str]) -> int:
    """Decision points under `node`, as the tree-sitter grammar counts them."""
    if isinstance(node, ast.Raise):
        return 0  # raise_statement is an ignored node
    own = 0
    children: list[ast.AST] = list(ast.iter_child_nodes(node))
    if isinstance(node, ast.If):
        own = 1  # if_statement or elif_clause
        chained_elif = (
            len(node.orelse) == 1
            and isinstance(node.orelse[0], ast.If)
            and _is_elif(node.orelse[0], lines)
        )
        own += bool(node.orelse) and not chained_elif  # else_clause
    elif isinstance(node, ast.For | ast.AsyncFor | ast.While):
        own = 1 + bool(node.orelse)
    elif isinstance(node, ast.Try | ast.TryStar):
        own = len(node.handlers) + bool(node.orelse)
        children = [
            c for c in children if not any(c is f for f in node.finalbody)
        ]  # finally_clause
    elif isinstance(node, ast.BoolOp):
        own = len(node.values) - 1  # one boolean_operator per and/or
    elif isinstance(node, ast.match_case | ast.ListComp | ast.IfExp | ast.Assert):
        own = 1
    return own + sum(_decisions(child, lines) for child in children)


def _cyclomatic(func: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> int:
    # The function node excludes its own decorators (they sit in the parent
    # decorated_definition), but includes defaults and annotations.
    parts = [*func.args.defaults, *(d for d in func.args.kw_defaults if d), *func.body]
    parts += [
        a.annotation
        for a in (*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs)
        if a.annotation
    ]
    parts += [a.annotation for a in (func.args.vararg, func.args.kwarg) if a and a.annotation]
    if func.returns:
        parts.append(func.returns)
    return 1 + sum(_decisions(p, lines) for p in parts)


def measure(root: Path) -> list[Measurement]:
    """Every max-cyclomatic and max-loc-file measurement APS would make for Python under `root`."""
    measurements: list[Measurement] = []
    for path in python_files(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        module = module_id(path, root)
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            raise SystemExit(f"{path}: cannot parse ({e.msg}, line {e.lineno})") from e
        lines = source.splitlines()
        functions = [
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for func in functions:
            measurements.append(
                Measurement(
                    "max-cyclomatic", f"python:{module}::{func.name}", _cyclomatic(func, lines)
                )
            )
        if functions:
            loc = sum(min(f.end_lineno or f.lineno, len(lines)) - f.lineno + 1 for f in functions)
            measurements.append(Measurement("max-loc-file", module, loc))
    return measurements


def find_violations(root: Path) -> list[Violation]:
    """The max-loc-file and max-cyclomatic violations `just fitness-check` would report for Python."""
    rules = load_rules(root)
    waivers = load_waivers(root)
    violations: list[Violation] = []
    for m in measure(root):
        rule = rules[m.rule]
        if m.value <= rule.max or rule.excludes(m.entity):
            continue
        if m.value <= waivers.get((m.rule, m.entity), rule.max):
            continue
        violations.append(Violation(m, rule.max))
    return violations


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    violations = find_violations(root)
    for v in violations:
        print(f"❌ {v}")
    if violations:
        print("Split the file or function; see fitness.toml and fitness-exceptions.toml.")
        return 1
    print("✅ max-loc-file and max-cyclomatic pass for Python (APS confirms in fitness-agent)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
