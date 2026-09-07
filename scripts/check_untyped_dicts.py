"""Ratchet: str-keyed mappings with unconstrained values, counted per package.

``dict[str, Any]`` is structured state with the structure erased. Budgets live
in ``fitness-exceptions.toml`` under ``[untyped-dicts.*]``; every non-zero entry
is grandfathered debt and must ratchet to 0.

WHY THIS IS AN AST PASS AND NOT A REGEX. It used to be a heredoc inside
``just check-untyped-dicts`` that counted one literal string::

    re.findall(r"dict\\[str, (?:Any|object)\\]", py_file.read_text())

That measures spelling, not typing. It missed ``Mapping[str, object]``,
``MutableMapping[str, Any]``, ``Dict[str, Any]``, quoted forward references and
any annotation wrapped across two lines - all of which erase exactly as much as
the one spelling it did see. In the other direction it counted prose: a
``dict[str, Any]`` named in a docstring, a comment or a test fixture string
spent budget that no type checker would ever object to.

Both halves showed up in practice. On PR #1186 the count crossed its ceiling by
one and was brought back under by renaming a single annotation from
``dict[str, object]`` to ``Mapping[str, object]``. That was a good change on its
own merits - the argument is read-only and genuinely wants a ``Mapping`` - which
is the point: the honest edit and the way around the gate were the same edit,
and a text search cannot tell them apart.

Parsing removes the seam. Every spelling below resolves to one shape, and
docstrings and comments are not part of the tree at all.

See docs/retrospectives/2026-08-17-green-checks-that-check-nothing.md and #1188.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Mapping constructors that erase their value type when parameterised with
#: ``Any``/``object``. Matched on the trailing name, so the dotted spellings
#: (``typing.Dict``, ``collections.abc.Mapping``, ``t.Mapping``) resolve here
#: too. ``defaultdict``/``OrderedDict``/``Counter`` are deliberately absent:
#: none appear in this shape anywhere in the packages under budget, and a name
#: nobody uses is a branch the next reader has to rule out for nothing.
MAPPING_NAMES: frozenset[str] = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})

#: Value types that constrain nothing. ``typing.Any`` and a bare ``object`` are
#: the same erasure in different words.
UNCONSTRAINED_VALUES: frozenset[str] = frozenset({"Any", "object"})

#: Directory fragments that are never first-party source. ``.claude/worktrees``
#: holds complete repo copies, so counting them would count the same annotation
#: once per live agent worktree - the false positive that
#: ``check_test_markers`` already shipped once.
EXCLUDED_PATH_FRAGMENTS: tuple[str, ...] = (
    ".venv",
    ".claude/worktrees",
    "node_modules",
    "site-packages",
)


@dataclass(frozen=True)
class Occurrence:
    """One str-keyed mapping with an unconstrained value type."""

    line: int
    text: str


@dataclass(frozen=True)
class Unreadable:
    """A file the counter could not parse, and therefore could not measure."""

    path: Path
    reason: str


def _trailing_name(node: ast.expr) -> str | None:
    """The bare name a type expression refers to, ignoring how it was reached.

    ``Any``, ``typing.Any`` and ``"Any"`` all answer ``"Any"``. A string holding
    something that is not a plain identifier (``"dict[str, Any]"``) answers
    ``None``: it is a nested type expression, handled by descending into it
    rather than by naming it.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip() if node.value.strip().isidentifier() else None
    return None


def _subscript_arguments(node: ast.Subscript) -> list[ast.expr]:
    """The parameters of ``X[a, b]`` as a list; ``X[a]`` yields one element."""
    if isinstance(node.slice, ast.Tuple):
        return list(node.slice.elts)
    return [node.slice]


def _is_untyped_str_mapping(node: ast.Subscript, values: frozenset[str]) -> bool:
    """Whether ``node`` maps ``str`` to one of ``values``."""
    if _trailing_name(node.value) not in MAPPING_NAMES:
        return False
    arguments = _subscript_arguments(node)
    if len(arguments) != 2:
        return False
    key, value = arguments
    return _trailing_name(key) == "str" and _trailing_name(value) in values


class _MappingCollector(ast.NodeVisitor):
    """Collects matching subscripts, including ones hidden inside strings.

    A quoted type is still a type, so strings are parsed and searched in the
    three places the language reads one: an annotation, a type parameter, and a
    ``cast`` target. Strings anywhere else - docstrings, fixtures, log messages
    - are left alone, which is the whole reason this is a parser and not a
    search. Comments are not in the tree at all.
    """

    def __init__(self, values: frozenset[str]) -> None:
        self.values = values
        self.found: list[Occurrence] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_untyped_str_mapping(node, self.values):
            self.found.append(Occurrence(line=node.lineno, text=ast.unparse(node)))
        # Type parameters are a type position: ``list["dict[str, Any]"]`` hides
        # a match that only exists once the string is parsed.
        for argument in _subscript_arguments(node):
            self._descend_into_string(argument)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # ``cast`` is the one place the language expects a type as a value, so
        # ``cast("dict[str, Any]", x)`` and ``cast(dict[str, Any], x)`` are the
        # same annotation. Counting only the second would leave the quotes as a
        # way to spell the type without spending the budget.
        if _trailing_name(node.func) == "cast" and node.args:
            self._descend_into_string(node.args[0])
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._descend_into_string(node.annotation)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        if node.annotation is not None:
            self._descend_into_string(node.annotation)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.returns is not None:
            self._descend_into_string(node.returns)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.returns is not None:
            self._descend_into_string(node.returns)
        self.generic_visit(node)

    def _descend_into_string(self, node: ast.expr) -> None:
        """Search inside a forward reference, reporting hits at its own line.

        A string that does not parse as an expression is not a forward
        reference at all - ``Literal["not python"]`` is the common case - so it
        is left alone rather than raised.
        """
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            return
        try:
            inner = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return
        nested = _MappingCollector(self.values)
        nested.visit(inner)
        self.found.extend(Occurrence(line=node.lineno, text=hit.text) for hit in nested.found)


def find_untyped_mappings(
    source: str, *, values: frozenset[str] = UNCONSTRAINED_VALUES
) -> list[Occurrence]:
    """Every str-keyed mapping with an unconstrained value type in ``source``.

    One occurrence per written type expression, wherever it appears: an
    annotation, a type alias, a ``cast`` target, a base class. Nesting is
    searched, so ``list[dict[str, Any]]`` is one. A mapping whose value type is
    itself a mapping is not erased by that - ``dict[str, dict[str, Any]]`` is
    one, the inner one - because ``dict`` is a constraint even when what it
    contains is not.

    An alias is counted where it is defined and not where it is used, because
    the definition is the one place a fix has to happen: typing
    ``D = dict[str, Any]`` fixes every reference to ``D`` at once. Counting the
    references instead would make the number track how popular a type is rather
    than how much erasure there is, and would inflate the debt of exactly the
    codebase that had centralised it well.

    ``values`` is the set of value types treated as constraining nothing.
    ADR-063's boundary gate widens it to include ``str``, because a
    ``dict[str, str]`` crossing a context boundary smuggles domain identity
    just as effectively. The ratchet itself uses the default.

    Raises ``SyntaxError`` if ``source`` does not parse. Callers must not
    swallow it: a file that cannot be measured has an unknown count, not a
    count of zero.
    """
    collector = _MappingCollector(values)
    collector.visit(ast.parse(source))
    return collector.found


def contains_untyped_mapping(
    node: ast.expr, *, values: frozenset[str] = UNCONSTRAINED_VALUES
) -> bool:
    """Whether a type expression contains a str-keyed mapping erased to ``values``.

    The node-level entry to the same definition ``find_untyped_mappings`` uses,
    for callers that have already parsed and hold a single annotation. Quoted
    and nested spellings are followed here too, so a caller cannot be fooled by
    a form the ratchet would have caught.
    """
    collector = _MappingCollector(values)
    collector.visit(node)
    return bool(collector.found)


def is_excluded(path: Path | str) -> bool:
    """True when a path lies under a directory that is not first-party source."""
    text = Path(path).as_posix()
    return any(fragment in text for fragment in EXCLUDED_PATH_FRAGMENTS)


@dataclass(frozen=True)
class PackageScan:
    """What a package measured, and what it could not."""

    name: str
    count: int
    allowed: int
    issue: str
    unreadable: tuple[Unreadable, ...] = ()

    @property
    def exceeded(self) -> bool:
        return self.count > self.allowed

    def render(self) -> str:
        if self.exceeded:
            return f"  FAIL {self.name}: {self.count} occurrences (threshold: {self.allowed}) [{self.issue}]"
        if self.allowed > 0:
            return f"  WARN {self.name}: {self.count}/{self.allowed} - tech debt, ratchet to 0 [{self.issue}]"
        return f"  ok {self.name}: clean"


def scan_package(name: str, root: Path, allowed: int, issue: str) -> PackageScan:
    """Count every first-party ``*.py`` under ``root``.

    A file that cannot be read or parsed is recorded, never skipped. Silently
    dropping it would report an improvement whenever a file broke, which is the
    one direction a ratchet must never be able to move by accident.
    """
    count = 0
    unreadable: list[Unreadable] = []
    for py_file in sorted(root.rglob("*.py")):
        if is_excluded(py_file):
            continue
        try:
            count += len(find_untyped_mappings(py_file.read_text()))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            unreadable.append(Unreadable(path=py_file, reason=f"{type(exc).__name__}: {exc}"))
    return PackageScan(
        name=name,
        count=count,
        allowed=allowed,
        issue=issue,
        unreadable=tuple(unreadable),
    )


def main() -> int:
    config = tomllib.loads(Path("fitness-exceptions.toml").read_text())
    entries = config.get("untyped-dicts", {})
    if not entries:
        print("  No [untyped-dicts.*] entries in fitness-exceptions.toml")
        return 0

    scans = [
        scan_package(
            name=name,
            root=Path(entry["path"]),
            allowed=int(entry.get("value", 0) or 0),
            issue=str(entry.get("issue", "")),
        )
        for name, entry in entries.items()
    ]
    for scan in scans:
        print(scan.render())

    unreadable = [file for scan in scans for file in scan.unreadable]
    for file in unreadable:
        print(f"  UNREADABLE {file.path}: {file.reason}")

    if unreadable:
        print(
            "\nA file that will not parse has an unknown count, not a count of"
            " zero. Fix the file - the ratchet cannot measure the package until"
            " you do."
        )
        return 1
    if any(scan.exceeded for scan in scans):
        print("\nRatchet exceeded! Reduce untyped dicts or lower value in fitness-exceptions.toml.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
