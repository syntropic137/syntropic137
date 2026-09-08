"""Every place this repo names a Python version, and the rule that they agree.

WHY THIS EXISTS (issue #1018). `requires-python = ">=3.12"` let `uv sync` build
the venv on the newest interpreter installed while every CI job pinned 3.12, so
"3149 tests passed locally" was a true statement about a Python CI never runs.
The remedy is a committed `.python-version`, and the guard is this module: a pin
that nothing checks drifts back the moment someone bumps one of the two dozen
other places a version is written down.

WHAT MAKES IT A GUARD AND NOT A GESTURE. The first version of this check read
one regex match per workflow FILE. `ci.yml` has four jobs, each with its own
`setup-python`, and only the first was ever compared - so two jobs disagreeing
inside one file passed. A drift check with a blind spot is worse than none: it
converts an open question into a false all-clear. So this one does not know what
a job, a step or a matrix is. It walks the whole parsed document and reports
every `python-version` it finds, wherever it sits, and the same for the six
other kinds of file that select an interpreter.

WHAT COUNTS AS A DECLARATION. Anything that decides, or constrains, which
interpreter runs this repo's code:

  - `.python-version`      what `uv` reads before falling back to the newest
  - `.github/**/*.yml`     every `python-version:` in the parsed tree
  - `pyproject.toml`       `requires-python` (a floor), ruff `target-version`,
                           mypy `python_version`
  - `pyrightconfig.json`   `pythonVersion`
  - `**/Dockerfile*`       `FROM python:X.Y...`
  - justfile, pre-commit   a command must reach a repo script through `uv run`,
                           the only thing that honours the pin
  - the live interpreter   a gate measured on the wrong Python measures nothing

Discovery is `git ls-files`, so submodules - which pin their own interpreters
and are not this repo's to set - are excluded by construction rather than by a
list someone has to maintain.

A value this cannot compare (`3.x`, `${{ env.PY }}`) is REPORTED, not skipped.
Silently ignoring the one form of declaration a checker does not understand is
how the blind spot got there the first time.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

#: Both spellings GitHub Actions and the Python tools use for the same idea.
_VERSION_KEYS: Final = frozenset({"python-version", "python_version"})

#: A repo-relative `scripts/x.py` in a command, but not `/app/scripts/x.py`,
#: which is a path inside a container and runs that image's interpreter.
_JUST_SCRIPT: Final = re.compile(r"(?<![\w/])((?:[\w.-]+/)*scripts/[\w.-]+\.py)")


@dataclass(frozen=True)
class PythonVersion:
    """One place that states which Python something runs on.

    `stated` is the text as written, so the message can quote the file back at
    the reader. `version` is None when that text does not name a comparable
    interpreter, which is a problem in its own right rather than a reason to
    look away.
    """

    where: str
    stated: str
    version: tuple[int, int] | None
    minimum_only: bool = False


def _minor(text: str | None) -> tuple[int, int] | None:
    """The (major, minor) a version string names, or None if it names none."""
    if text is None:
        return None
    match = re.fullmatch(r"\s*v?(\d+)\.(\d+)(?:\.\d+)?\s*", text)
    return (int(match[1]), int(match[2])) if match else None


def _render(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def _at(node: object, *keys: str) -> object:
    """Follow a path of string keys through parsed JSON/TOML/YAML, or None."""
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _text(node: object) -> str | None:
    return node if isinstance(node, str) else None


def _items(node: object) -> Iterator[object]:
    """The elements of a parsed list, or nothing if it is not one."""
    if isinstance(node, list):
        yield from node


def _scalar_versions(value: object, where: str) -> Iterator[PythonVersion]:
    """One declaration per scalar, descending into lists so matrices are seen."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _scalar_versions(item, f"{where}[{index}]")
        return
    stated = str(value)
    yield PythonVersion(where, stated, _minor(stated))


def _yaml_versions(node: object, where: str) -> Iterator[PythonVersion]:
    """Every `python-version` anywhere in a parsed YAML document.

    Structure-blind on purpose. A job, a matrix, a composite action's `runs`
    and a reusable workflow's `inputs` are all just mappings, and a checker
    that knows which of them to look in is a checker that misses the next one.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{where}.{key}"
            if str(key) in _VERSION_KEYS:
                yield from _scalar_versions(value, child)
            else:
                yield from _yaml_versions(value, child)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _yaml_versions(item, f"{where}[{index}]")


def _pyproject_versions(document: object, where: str) -> Iterator[PythonVersion]:
    requires = _text(_at(document, "project", "requires-python"))
    if requires is not None:
        floor = re.search(r">=\s*(\d+\.\d+)", requires)
        yield PythonVersion(
            f"{where} requires-python",
            requires,
            _minor(floor[1]) if floor else None,
            minimum_only=True,
        )

    target = _text(_at(document, "tool", "ruff", "target-version"))
    if target is not None:
        digits = re.fullmatch(r"py(\d)(\d+)", target)
        yield PythonVersion(
            f"{where} ruff target-version",
            target,
            _minor(f"{digits[1]}.{digits[2]}") if digits else None,
        )

    mypy = _text(_at(document, "tool", "mypy", "python_version"))
    if mypy is not None:
        yield PythonVersion(f"{where} mypy python_version", mypy, _minor(mypy))


def _dockerfile_versions(body: str, where: str) -> Iterator[PythonVersion]:
    for number, line in enumerate(body.splitlines(), start=1):
        match = re.match(r"\s*FROM\s+(?:.*/)?python:(\S+)", line, re.IGNORECASE)
        if match:
            tag = match[1]
            yield PythonVersion(f"{where}:{number}", f"python:{tag}", _minor(tag.split("-")[0]))


def _declarations_in(path: Path, where: str) -> Iterator[PythonVersion]:
    """Every version `path` declares, decided by what kind of file it is."""
    name = path.name
    if name == ".python-version":
        yield PythonVersion(where, path.read_text().strip(), _minor(path.read_text().strip()))
    elif where.startswith(".github/") and path.suffix in {".yml", ".yaml"}:
        yield from _yaml_versions(yaml.safe_load(path.read_text()), where)
    elif name == "pyproject.toml":
        yield from _pyproject_versions(tomllib.loads(path.read_text()), where)
    elif name == "pyrightconfig.json":
        stated = _text(_at(json.loads(path.read_text()), "pythonVersion"))
        if stated is not None:
            yield PythonVersion(f"{where} pythonVersion", stated, _minor(stated))
    elif name.startswith("Dockerfile"):
        yield from _dockerfile_versions(path.read_text(), where)


def tracked_files(repo_root: Path) -> list[str]:
    """Every file git tracks, repo-relative.

    `git ls-files` rather than a walk: it excludes `.venv`, build output and -
    the reason it matters here - submodule contents, which pin their own
    interpreters. A prune list would have to be remembered; this cannot drift.
    """
    listing = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return listing.stdout.split()


def declared_python_versions(repo_root: Path) -> list[PythonVersion]:
    """Every Python version this repo's tracked files name."""
    return [
        declaration
        for relative in tracked_files(repo_root)
        for declaration in _declarations_in(repo_root / relative, relative)
    ]


def running_python_version() -> tuple[int, int]:
    """The interpreter this process is running on."""
    major, minor, *_ = platform.python_version_tuple()
    return (int(major), int(minor))


def disagreements(declarations: Iterable[PythonVersion]) -> list[str]:
    """Every way the places that name a Python version fail to name one Python.

    Two rules, and no privileged source. Everything that SELECTS an interpreter
    must name the same one - the pin, each CI step, each image, the type
    checkers, the interpreter this runs on - because "which Python is this
    repo" has exactly one answer or it has none. Everything that merely
    CONSTRAINS it, which today means `requires-python`, must admit that answer;
    a floor below it is a supported-version claim, not drift.
    """
    declarations = list(declarations)
    problems = [
        f"{item.where} says {item.stated!r}, which is not a Python version this "
        f"gate can compare. Name a concrete major.minor there, or nothing "
        f"downstream can tell whether it agrees."
        for item in sorted(declarations, key=lambda item: item.where)
        if item.version is None
    ]

    selects: list[tuple[tuple[int, int], str]] = [
        (item.version, item.where)
        for item in declarations
        if item.version is not None and not item.minimum_only
    ]
    if not selects:
        return problems

    chosen = sorted({version for version, _ in selects})
    if len(chosen) > 1:
        groups = (
            f"{_render(version)} ({', '.join(sorted(w for v, w in selects if v == version))})"
            for version in chosen
        )
        problems.append(
            "this repo names more than one Python interpreter: "
            + "; ".join(groups)
            + ". Everything that runs Python must name the same one, or no local "
            "run is evidence about any other."
        )
        return problems

    (agreed,) = chosen
    problems.extend(
        f"{item.where} requires Python {item.stated}, above the {_render(agreed)} "
        f"everything else names, so `uv sync` cannot satisfy both."
        for item in sorted(declarations, key=lambda item: item.where)
        if item.minimum_only and item.version is not None and item.version > agreed
    )
    return problems


def _unpinned_uv_projects(tracked: Iterable[str]) -> list[str]:
    """uv projects with a lockfile but no pin of their own.

    `uv` stops looking for `.python-version` at the project root, so the root
    file never reaches a nested project - `just feedback-install` is a second
    `uv sync` and had no pin at all. A project with no pin declares nothing,
    which is why `disagreements` cannot see it: there is no version to compare.
    """
    files = set(tracked)
    return [
        f"{lock} is a uv project with no .python-version beside it, so `uv sync` "
        f"there resolves to the newest interpreter installed rather than the one "
        f"the rest of the repo names."
        for lock in sorted(files)
        if lock.endswith("uv.lock") and lock.replace("uv.lock", ".python-version") not in files
    ]


def _command_lines(repo_root: Path) -> Iterator[tuple[str, str]]:
    """Every command this repo spells out that might run one of its scripts.

    Two files, one shape. The justfile is the documented entry point and the
    pre-commit config is the one that fires without being asked; both are lists
    of shell commands, so both are read as such rather than each growing its
    own rule.
    """
    justfile = repo_root / "justfile"
    if justfile.is_file():
        for number, line in enumerate(justfile.read_text().splitlines(), start=1):
            if not line.lstrip().startswith("#"):
                yield (f"justfile line {number}", line)

    config = repo_root / ".pre-commit-config.yaml"
    if not config.is_file():
        return
    for repo in _items(_at(yaml.safe_load(config.read_text()), "repos")):
        for hook in _items(_at(repo, "hooks")):
            entry = _text(_at(hook, "entry"))
            if entry is not None:
                yield (f".pre-commit-config.yaml hook {_text(_at(hook, 'id'))!r}", entry)


def _scripts_run_outside_uv(commands: Iterable[tuple[str, str]]) -> list[str]:
    """Commands that run one of this repo's scripts without `uv run`.

    The pin only binds through `uv`; a bare `python3 scripts/x.py` runs whatever
    is first on PATH, and a pre-commit hook with `language: python` builds its
    own venv from that same interpreter. Either is the #1018 defect wearing a
    different hat: a gate whose result describes a Python nobody chose. Paths
    beginning with `/` are inside a container and run that image's interpreter,
    which the Dockerfile declaration already covers.
    """
    return [
        f"{where} runs {match[1]} without `uv run`, so it uses whatever python "
        f"is on PATH rather than the pinned interpreter."
        for where, command in commands
        if "uv run" not in command
        for match in _JUST_SCRIPT.finditer(command)
    ]


def interpreter_problems(repo_root: Path) -> list[str]:
    """Every way this repo fails to run on exactly one Python interpreter."""
    tracked = tracked_files(repo_root)
    running = PythonVersion(
        "the interpreter running this check",
        _render(running_python_version()),
        running_python_version(),
    )
    return [
        *disagreements([*declared_python_versions(repo_root), running]),
        *_unpinned_uv_projects(tracked),
        *_scripts_run_outside_uv(_command_lines(repo_root)),
    ]
