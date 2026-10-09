"""Fitness function: no Linux-only construct outside a module declared Linux-only (PC-145).

macOS is a supported development and self-host platform, but CI and the agent
workspace both run Linux, so a Linux-only construct passes every gate and
breaks only on a developer's Mac. #1809's branch used ``/proc/self/fd`` in a
test and was green everywhere that ran it. This check makes that visible
before review instead of after.

**What counts.** In Python, read through the AST so docstrings, comments and
look-alike names (``_REPO_PATH`` is not ``O_PATH``) are not hits:

* a string or bytes literal (f-string parts included) naming ``/proc`` or
  ``/sys`` as a path, not as part of a longer word or URL segment;
* an attribute, ``from`` import, or bare name from ``LINUX_ONLY_NAMES``
  (``os.O_PATH``, ``os.sched_getaffinity``, ``select.epoll``, a ctypes
  ``libc.prctl`` ...);
* an import of a ``LINUX_ONLY_MODULES`` module (``prctl``, ``inotify`` ...).

In TypeScript/JavaScript, comments are skipped by a small lexer and three
kinds of construct are matched: path literals inside string or template
literals, the Linux-only flags and syscalls a Node binding could expose as
identifiers in code (template ``${...}`` interpolations are code), and an
``import``/``require`` of a ``_SCRIPT_MODULES`` package.

``getattr(os, "sched_getaffinity", None)`` is the portable spelling of a
Linux-only call (it degrades instead of raising) and is deliberately not a hit.

**Scope.** Every Python and TS/JS file tracked by this repository. Submodules
under ``lib/`` are gitlinks here, so ``git ls-files`` never lists them.

**Exceptions.** ``[linux_only_constructs]`` in ``fitness_exceptions.toml``:
an exact tracked path with a ``reason`` saying why the module is Linux-only by
design, e.g. it only ever runs inside the Linux API or workspace container. A
whole module is declared, not a line: the declaration is about where the code
runs. An entry with no reason, naming a missing file, or naming a file with no
hits fails, so the table can only shrink.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import ast
import bisect
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from ci.fitness.conftest import load_exceptions, repo_root

_EXCEPTIONS_SECTION = "linux_only_constructs"

_PYTHON_SUFFIXES = frozenset({".py"})
_SCRIPT_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs"})

#: ``/proc`` or ``/sys`` as a path: not preceded by a path or word character
#: (so not ``/usr/sys`` or ``https://x/sys``) and not followed by one (so not
#: ``/system``).
_PSEUDO_FS = re.compile(r"(?<![\w./-])/(?:proc|sys)(?![\w.-])")

#: The inotify syscalls, shared by both scanners so neither can drop one.
_INOTIFY_CALLS = frozenset(
    {"inotify_init", "inotify_init1", "inotify_add_watch", "inotify_rm_watch"}
)

#: Names that exist only on Linux, wherever they are reached from.
LINUX_ONLY_NAMES = _INOTIFY_CALLS | frozenset(
    {
        # os: open flags and calls macOS does not have
        "O_PATH",
        "O_TMPFILE",
        "O_NOATIME",
        "sched_getaffinity",
        "sched_setaffinity",
        "sched_getscheduler",
        "sched_setscheduler",
        "sched_getparam",
        "sched_setparam",
        "sched_rr_get_interval",
        "memfd_create",
        "pidfd_open",
        "eventfd",
        "splice",
        "copy_file_range",
        "pipe2",
        "getxattr",
        "setxattr",
        "listxattr",
        "removexattr",
        # select / resource / signal
        "epoll",
        "prlimit",
        "pidfd_send_signal",
        # syscalls reached through ctypes or a binding
        "prctl",
        "unshare",
        "setns",
    }
)

#: Top-level modules that only import on Linux.
LINUX_ONLY_MODULES = frozenset(
    {"prctl", "inotify", "inotify_simple", "pyinotify", "asyncinotify", "pyroute2"}
)

#: The subset worth matching as a bare TS/JS identifier. Node exposes none of
#: the os calls above, and generic names (``splice`` is ``Array.prototype``'s)
#: would read every array edit as a syscall.
_SCRIPT_NAMES = _INOTIFY_CALLS | frozenset({"O_PATH", "O_TMPFILE", "O_NOATIME", "prctl"})
_SCRIPT_IDENTIFIER = re.compile(r"\b(?:" + "|".join(sorted(_SCRIPT_NAMES)) + r")\b")

#: npm packages that only build or load on Linux.
_SCRIPT_MODULES = frozenset({"inotify"})

#: Code that makes the string literal right after it a module specifier:
#: ``from "x"``, ``import "x"``, ``require("x")``, ``import("x")``. Not
#: ``Array.from("x")``: the keyword must not follow a member access.
_SPECIFIER_LEAD = re.compile(r"(?<![\w.$])(?:from|import|(?:require|import)\s*\()\s*$")


@dataclass(frozen=True)
class Hit:
    """One Linux-only construct at one line."""

    line: int
    construct: str


def _docstring_nodes(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, owners) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def scan_python(source: str) -> list[Hit]:
    """Every Linux-only construct in a Python module's code."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    hits: list[Hit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            # A bytes path reaches the same filesystem; latin-1 decodes any byte.
            text = node.value.decode("latin-1") if isinstance(node.value, bytes) else node.value
            if id(node) not in docstrings and _PSEUDO_FS.search(text):
                hits.append(Hit(node.lineno, f"path literal {node.value[:60]!r}"))
        elif isinstance(node, ast.Attribute) and node.attr in LINUX_ONLY_NAMES:
            hits.append(Hit(node.lineno, f"attribute .{node.attr}"))
        elif isinstance(node, ast.Name) and node.id in LINUX_ONLY_NAMES:
            hits.append(Hit(node.lineno, f"name {node.id}"))
        elif isinstance(node, ast.Import):
            hits.extend(
                Hit(node.lineno, f"import {alias.name}")
                for alias in node.names
                if alias.name.split(".")[0] in LINUX_ONLY_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in LINUX_ONLY_MODULES:
                hits.append(Hit(node.lineno, f"import from {node.module}"))
            hits.extend(
                Hit(node.lineno, f"import {alias.name}")
                for alias in node.names
                if alias.name in LINUX_ONLY_NAMES
            )
    return hits


@dataclass(frozen=True)
class _Run:
    """A stretch of TS/JS source that is either code or a string-literal body."""

    line: int
    text: str
    is_string: bool


def _lex_script(source: str) -> list[_Run]:
    """Split TS/JS into code runs and string-literal bodies, in source order.

    Comments are dropped. A template literal's text is a string, and each of
    its ``${...}`` interpolations is lexed as code, nested templates included,
    so an identifier inside one is seen. Regex literals are read as code: a
    pseudo-filesystem path in one is still worth a look.
    """
    newlines = [i for i, char in enumerate(source) if char == "\n"]
    runs: list[_Run] = []
    n = len(source)

    def emit(start: int, end: int, *, is_string: bool) -> None:
        runs.append(_Run(bisect.bisect_left(newlines, start) + 1, source[start:end], is_string))

    def quoted(i: int, quote: str) -> int:
        end = i + 1
        while end < n and source[end] != quote:
            if source[end] == "\\":
                end += 1
            elif source[end] == "\n":
                break
            end += 1
        emit(i + 1, end, is_string=True)
        return min(end + 1, n)

    def template(i: int) -> int:
        j = start = i + 1
        while j < n and source[j] != "`":
            if source[j] == "\\":
                j += 2
            elif source.startswith("${", j):
                emit(start, j, is_string=True)
                j = start = code(j + 2, nested=True)
            else:
                j += 1
        emit(start, min(j, n), is_string=True)
        return min(j + 1, n)

    def code(i: int, *, nested: bool) -> int:
        """Lex code from ``i``; nested, stop after the ``}`` closing an interpolation."""
        start, depth = i, 0
        while i < n:
            two, char = source[i : i + 2], source[i]
            if two in ("//", "/*") or char in "'\"`":
                emit(start, i, is_string=False)
                if two == "//":
                    end = source.find("\n", i)
                    i = n if end == -1 else end
                elif two == "/*":
                    end = source.find("*/", i + 2)
                    i = n if end == -1 else end + 2
                else:
                    i = template(i) if char == "`" else quoted(i, char)
                start = i
                continue
            if nested and char == "{":
                depth += 1
            elif nested and char == "}":
                if depth == 0:
                    emit(start, i, is_string=False)
                    return i + 1
                depth -= 1
            i += 1
        emit(start, n, is_string=False)
        return n

    code(0, nested=False)
    return runs


def scan_script(source: str) -> list[Hit]:
    """Every Linux-only construct in a TS/JS module's code."""
    hits: list[Hit] = []
    previous: _Run | None = None
    for run in _lex_script(source):
        if run.is_string:
            for match in _PSEUDO_FS.finditer(run.text):
                line = run.line + run.text.count("\n", 0, match.start())
                hits.append(Hit(line, f"path literal {run.text[:60]!r}"))
            if (
                previous is not None
                and not previous.is_string
                and _SPECIFIER_LEAD.search(previous.text)
                and run.text.split("/")[0] in _SCRIPT_MODULES
            ):
                hits.append(Hit(run.line, f"import {run.text}"))
        else:
            for match in _SCRIPT_IDENTIFIER.finditer(run.text):
                line = run.line + run.text.count("\n", 0, match.start())
                hits.append(Hit(line, f"name {match.group()}"))
        previous = run
    return hits


def scan(path: Path, source: str) -> list[Hit]:
    """Every Linux-only construct in one source file; other file types have none."""
    if path.suffix in _PYTHON_SUFFIXES:
        return scan_python(source)
    if path.suffix in _SCRIPT_SUFFIXES:
        return scan_script(source)
    return []


def _tracked_sources(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    suffixes = _PYTHON_SUFFIXES | _SCRIPT_SUFFIXES
    return [name for name in listed.split("\0") if name and Path(name).suffix in suffixes]


def hits_by_file(root: Path) -> dict[str, list[Hit]]:
    """Every tracked source file with at least one hit, keyed by repo-relative path."""
    found: dict[str, list[Hit]] = {}
    for name in _tracked_sources(root):
        path = root / name
        if not path.is_file():
            continue  # deleted but not yet staged
        hits = scan(path, path.read_text(encoding="utf-8"))
        if hits:
            found[name] = hits
    return found


def declared_linux_only(root: Path) -> dict[str, str]:
    """The exceptions table as path -> reason. An entry with no reason fails here."""
    table: dict[str, object] = load_exceptions(root).get(_EXCEPTIONS_SECTION, {})
    declared: dict[str, str] = {}
    unreasoned: list[str] = []
    for path, entry in table.items():
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if isinstance(reason, str) and reason.strip():
            declared[path] = reason
        else:
            unreasoned.append(path)
    assert not unreasoned, (
        f"[{_EXCEPTIONS_SECTION}] entries need a non-empty `reason` saying why the "
        "module is Linux-only by design:\n  " + "\n  ".join(sorted(unreasoned))
    )
    return declared


@pytest.fixture(scope="module")
def found() -> dict[str, list[Hit]]:
    return hits_by_file(repo_root())


@pytest.mark.architecture
def test_no_linux_only_construct_outside_a_declared_module(found: dict[str, list[Hit]]) -> None:
    declared = declared_linux_only(repo_root())
    violations = [
        f"{path}:{hit.line}: {hit.construct}"
        for path, hits in sorted(found.items())
        if path not in declared
        for hit in hits
    ]
    if violations:
        pytest.fail(
            "Linux-only construct found (PC-145). macOS is a supported dev and "
            "self-host platform and no CI job runs on it. Make it portable, or, if "
            "the module only ever runs inside a Linux container, declare it in "
            f"[{_EXCEPTIONS_SECTION}] of ci/fitness/fitness_exceptions.toml with a "
            "reason:\n  " + "\n  ".join(violations)
        )


@pytest.mark.architecture
def test_no_stale_linux_only_declarations(found: dict[str, list[Hit]]) -> None:
    stale = sorted(set(declared_linux_only(repo_root())) - set(found))
    assert not stale, (
        "These files are declared Linux-only but have no Linux-only construct "
        "(fixed, moved or deleted). Remove them from "
        f"[{_EXCEPTIONS_SECTION}]:\n  " + "\n  ".join(stale)
    )


# Built by concatenation so this file does not match its own scan.
_PROC = "/pr" + "oc"
_SYS = "/s" + "ys"

#: One planted example per form; each must be caught on its own.
PLANTED_PYTHON = {
    "#1809's literal": f'Path(f"{_PROC}/self/fd/{{fd}}").readlink()',
    "bare procfs root": f'"{_PROC}" in source',
    "sysfs": f'open("{_SYS}/fs/cgroup/cpu.stat")',
    "joined path": f'Path("{_PROC}") / "self"',
    "os.O_PATH": "os.open(p, os." + "O_PATH)",
    "os.sched_getaffinity": "os.sched_" + "getaffinity(0)",
    "from-import": "from os import sched_" + "getaffinity",
    "select.epoll": "select." + "epoll()",
    "ctypes prctl": "libc." + "prctl(15, b'x')",
    "inotify module": "import inotify" + "_simple",
    "prctl module": "from " + "prctl import set_name",
    "bytes procfs": f'open(b"{_PROC}/self/fd")',
    "bytes sysfs": f'open(b"{_SYS}/fs/cgroup/cpu.max")',
    "inotify_rm_watch": "libc.inotify" + "_rm_watch(fd, wd)",
}

PLANTED_SCRIPT = {
    "ts literal": f'readFileSync("{_PROC}/self/status")',
    "ts template": f"readlinkSync(`{_PROC}/self/fd/${{fd}}`)",
    "ts single quote": f"existsSync('{_SYS}/class/net')",
    "ts identifier": "os.constants." + "O_PATH",
    "ts interpolated flag": "const x = `${os.constants." + "O_PATH}`;",
    "ts interpolated call": "const x = `${pr" + "ctl(15)}`;",
    "ts second interpolation": "const x = `${safe} and ${pr" + "ctl(15)}`;",
    "ts nested template": "const x = `a ${`b ${os.constants." + "O_PATH}`} c`;",
    "ts inotify_init1": "ino" + "tify_init1();",
    "ts inotify_rm_watch": "libc.ino" + "tify_rm_watch(fd, wd);",
    "ts import from": 'import { watch } from "ino' + 'tify";',
    "ts side-effect import": "import 'ino" + "tify';",
    "ts require": 'const I = require("ino' + 'tify");',
    "ts dynamic import": "await import(`ino" + "tify`);",
}

#: Must stay clean: look-alikes, prose, and the portable spelling.
CLEAN_PYTHON = (
    "_REPO_PATH = Path('.')",
    f'def f():\n    """Reads {_PROC}/self/fd on Linux."""\n',
    f"x = 1  # {_PROC}/uptime",
    'getattr(os, "sched_' + 'getaffinity", None)',
    '"/system/status"',
    '"/usr/sys/x"',
    '"https://example.com/sys/health"',
    '"api/proc/list"',
    "os.sched_yield()",
)

CLEAN_SCRIPT = (
    f"// reads {_PROC}/self/fd on Linux\nconst x = 1;",
    f"/* {_SYS}/fs */ const y = 2;",
    'fetch("/system/info")',
    'const url = "https://x.dev/proc/1";',
    "items.splice(index, 1);",
    "const s = `pr" + "ctl and O_" + "PATH are Linux-only`;",
    "const s = `${safe} uses pr" + "ctl, ${other} does not`;",
    'log("ino' + 'tify");',
    'const m = Array.from("ino' + 'tify");',
    'const s = "watch from"; const m = "ino' + 'tify";',
)


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(PLANTED_PYTHON))
def test_each_planted_python_form_is_caught(name: str) -> None:
    assert scan_python(PLANTED_PYTHON[name]), name


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(PLANTED_SCRIPT))
def test_each_planted_script_form_is_caught(name: str) -> None:
    assert scan_script(PLANTED_SCRIPT[name]), name


@pytest.mark.architecture
@pytest.mark.parametrize("source", CLEAN_PYTHON)
def test_python_look_alikes_stay_clean(source: str) -> None:
    assert scan_python(source) == []


@pytest.mark.architecture
@pytest.mark.parametrize("source", CLEAN_SCRIPT)
def test_script_look_alikes_stay_clean(source: str) -> None:
    assert scan_script(source) == []


@pytest.mark.architecture
def test_script_hit_reports_the_line_it_is_on() -> None:
    source = f"// {_PROC}\nconst a = 1;\nconst b = `x\n{_PROC}/self`;\n"
    assert [hit.line for hit in scan_script(source)] == [4]


@pytest.mark.architecture
def test_script_interpolation_hit_reports_the_line_it_is_on() -> None:
    source = "const a = `x ${safe}\n" + "y ${\n  os.constants.O_" + "PATH}`;\n"
    assert [hit.line for hit in scan_script(source)] == [3]
