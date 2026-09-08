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

WHY IT COUNTS THREE SHAPES AND NOT ONE. Parsing fixed how a shape is *written*
and left open which shapes are *looked for*. On PR #1246 a change that failed
this gate with a ``dict[str, Any]`` passed it by declaring a ``TypedDict`` with
the same string keys - which is still read as ``value["key"]``, still has no
runtime validation, and still fails both halves of the rule in AGENTS.md. The
gate went green; independent review refused the head anyway, on the grounds
that "passing the AST ratchet does not satisfy that requirement; it only shows
the ratchet does not count this spelling". That is the same defect as #1188 one
level up: not a number that moved for a rename, but a number that stayed still
for a shape nobody had listed.

So the subject here is dict-shaped structured state, in the three forms it is
declared in:

1. a str-keyed mapping whose value type constrains nothing - ``dict[str, Any]``
   and every alias of it;
2. a ``TypedDict`` declaration, class-based or functional, whatever its field
   types, because the objection is the string-keyed access and not the erasure;
3. a ``SimpleNamespace``, which declares no fields at all and so tells a type
   checker strictly less than the ``dict[str, Any]`` in (1).

``NamedTuple`` is deliberately absent. It names and types every field and is
read by attribute, so it is what the rule asks people to move toward, not away
from; the reasoning is pinned in the tests so the exclusion stays a decision.

Names are resolved through the module's own renames, so a shape given a second
name - on the import (``from typing import Dict as D``) or by assignment
(``D = dict``) - is the shape it was renamed from. Without that, closing a
spelling only moves the dodge into the line that names the shape, which is
cheaper than any of the spellings above: one line, no import, and nothing for a
reader of the annotation to notice.

See docs/retrospectives/2026-08-17-green-checks-that-check-nothing.md, #1188
and #1248.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Mapping constructors that erase their value type when parameterised with
#: ``Any``/``object``. Matched on the trailing name, so the dotted spellings
#: (``typing.Dict``, ``collections.abc.Mapping``, ``t.Mapping``) resolve here
#: too. ``defaultdict``/``OrderedDict``/``Counter`` are deliberately absent:
#: none appear in this shape anywhere in the packages under budget, and a name
#: nobody uses is a branch the next reader has to rule out for nothing.
MAPPING_NAMES: frozenset[str] = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})

#: A ``TypedDict`` declaration. Counted whatever its fields are annotated with,
#: which is the one place this gate is not about erasure: ``contents: str``
#: constrains the value perfectly and the object is still read as
#: ``value["contents"]``, so it fails "no string-keyed lookups when attribute
#: access is possible" on its own. There is no well-typed ``TypedDict`` for the
#: purposes of this rule, only ones that have not been converted yet.
TYPED_DICT_NAME = "TypedDict"

#: ``types.SimpleNamespace``. Attribute access, so it passes the second half of
#: the rule - and no declared fields at all, so it fails the first half harder
#: than a ``dict[str, Any]`` does: a checker can say nothing whatsoever about
#: ``ns.anything``. It is counted because ``SimpleNamespace(**payload)`` is a
#: one-line way to turn a counted annotation into an uncounted object, which is
#: precisely the move #1248 exists to stop.
NAMESPACE_NAME = "SimpleNamespace"

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
    """One declaration of dict-shaped structured state."""

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


def _renamed_shape(node: ast.AST) -> str | None:
    """The name an assignment renames, or ``None`` when it is not a rename.

    ``D = dict``, ``D: TypeAlias = dict`` and ``type D = dict`` are one line in
    three spellings, and each gives a constructor a second name while writing
    no type at all. The erasure arrives later, at ``D[str, Any]``, and is
    counted there - exactly as it is for ``from typing import Dict as D``.

    ``D = dict[str, Any]`` is not a rename. It is a complete type expression,
    already fully spelled out where it stands, and is counted there like any
    other annotation. The dividing line is whether the right-hand side is a
    bare name: a rename copies a name, an alias writes a type.
    """
    if not isinstance(node, ast.Assign | ast.AnnAssign | ast.TypeAlias):
        return None
    if not isinstance(node.value, ast.Name | ast.Attribute):
        return None
    return _trailing_name(node.value)


def _follow(name: str, renames: Mapping[str, str]) -> str:
    """The original name at the end of a chain of renames.

    ``D = dict`` followed by ``E = D`` is two lines and hides exactly as well
    as one, so the walk continues until it runs out of renames. A chain that
    closes on itself (``a = b`` beside ``b = a``) renames nothing and stops
    where it closes rather than spinning.
    """
    seen = {name}
    while (original := renames.get(name)) is not None and original not in seen:
        seen.add(original)
        name = original
    return name


def _renames(tree: ast.Module) -> Mapping[str, str]:
    """Every rename in a module, as local name -> the name it renames.

    ``_trailing_name`` answers what a type is *called at the point of use*,
    which is why the dotted spellings resolve. It cannot see a rename, and
    ``from typing import Dict as D`` leaves ``D[str, Any]`` matching nothing
    here. Undoing renames first is what stops "close a spelling, the dodge
    moves to the line that names the shape".

    Both statements that can rename a shape are read, because closing one and
    leaving the other open just moves the dodge again: ``import ... as`` and
    the assignment forms in ``_renamed_shape``. Assignment is the cheaper of
    the two - it needs no import at all - so it is the one a ratchet under
    pressure meets first.

    Every rename is recorded, not only the ones landing on a name this gate
    cares about, because that is what lets a chain resolve without depending on
    the order the statements appear in. An entry that resolves to nothing costs
    nothing; only the names below are ever looked up. Dotted module imports
    keep their last segment (``import collections.abc as c`` records
    ``c -> abc``) on the same reasoning. ``ast.walk`` rather than ``tree.body``
    because a function-local rename renames just as effectively as a top-level
    one.
    """
    renames: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                if alias.asname is not None:
                    renames[alias.asname] = alias.name.rpartition(".")[2]
        elif (original := _renamed_shape(node)) is not None:
            # The names a rename binds are its targets, which are the only
            # names it stores to - true of all three assignment spellings
            # without having to take each of them apart.
            for target in ast.walk(node):
                if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                    renames[target.id] = original
    return {name: _follow(name, renames) for name in renames}


def _subscript_arguments(node: ast.Subscript) -> list[ast.expr]:
    """The parameters of ``X[a, b]`` as a list; ``X[a]`` yields one element."""
    if isinstance(node.slice, ast.Tuple):
        return list(node.slice.elts)
    return [node.slice]


class _DictShapedStateCollector(ast.NodeVisitor):
    """Collects the three declaration shapes, including ones hidden in strings.

    A quoted type is still a type, so strings are parsed and searched in the
    three places the language reads one: an annotation, a type parameter, and a
    ``cast`` target. Strings anywhere else - docstrings, fixtures, log messages
    - are left alone, which is the whole reason this is a parser and not a
    search. Comments are not in the tree at all.

    ``renames`` comes from the enclosing module. It is empty when the caller
    handed over a bare expression instead of a module, because a rename cannot
    be undone without the statement that made it - a limitation of that input,
    not a second definition of the shape.
    """

    def __init__(self, values: frozenset[str], renames: Mapping[str, str]) -> None:
        self.values = values
        self.renames = renames
        self.found: list[Occurrence] = []

    def _name(self, node: ast.expr) -> str | None:
        """``_trailing_name``, with any rename undone."""
        name = _trailing_name(node)
        return None if name is None else self.renames.get(name, name)

    def _is_untyped_str_mapping(self, node: ast.Subscript) -> bool:
        """Whether ``node`` maps ``str`` to one of ``self.values``."""
        if self._name(node.value) not in MAPPING_NAMES:
            return False
        arguments = _subscript_arguments(node)
        if len(arguments) != 2:
            return False
        key, value = arguments
        return self._name(key) == "str" and self._name(value) in self.values

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_untyped_str_mapping(node):
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
        if self._name(node.func) == "cast" and node.args:
            self._descend_into_string(node.args[0])
        # ``P = TypedDict("P", {...})`` declares the same thing as the class
        # body below, one keystroke away from it.
        if self._name(node.func) == TYPED_DICT_NAME and node.args:
            self.found.append(
                Occurrence(
                    line=node.lineno,
                    text=f"{TYPED_DICT_NAME}({ast.unparse(node.args[0])})",
                )
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """A ``TypedDict`` is counted where it is declared, not where it is used.

        Same rule as an alias, for the same reason: replacing the declaration
        with a dataclass repairs every reference at once, so the declaration is
        the only place a fix can happen. Counting references would measure how
        popular the type is instead of how much debt there is.
        """
        if any(self._name(base) == TYPED_DICT_NAME for base in node.bases):
            self.found.append(
                Occurrence(line=node.lineno, text=f"class {node.name}({TYPED_DICT_NAME})")
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._note_namespace(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._note_namespace(node)
        self.generic_visit(node)

    def _note_namespace(self, node: ast.Name | ast.Attribute) -> None:
        """Every written ``SimpleNamespace`` counts - annotation or construction.

        Unlike an alias or a ``TypedDict`` there is no declaration to attribute
        it to: each construction invents its own ad-hoc shape, so each is a
        separate place the erasure has to be repaired. An ``import`` is not a
        use and does not count, because it names no shape on its own.

        A name being *bound* is not a use either, for the same reason and with
        more force now that renames resolve: without this, ``NS =
        SimpleNamespace`` would count twice, once for the name it copies and
        once for the name it defines, which resolves to the same shape.
        """
        if not isinstance(node.ctx, ast.Load):
            return
        if self._name(node) == NAMESPACE_NAME:
            self.found.append(Occurrence(line=node.lineno, text=NAMESPACE_NAME))

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
        nested = _DictShapedStateCollector(self.values, self.renames)
        nested.visit(inner)
        self.found.extend(Occurrence(line=node.lineno, text=hit.text) for hit in nested.found)


def find_dict_shaped_state(
    source: str, *, values: frozenset[str] = UNCONSTRAINED_VALUES
) -> list[Occurrence]:
    """Every declaration of dict-shaped structured state in ``source``.

    The three shapes are listed in the module docstring. For an erased mapping
    it is one occurrence per written type expression, wherever it appears: an
    annotation, a type alias, a ``cast`` target, a base class. Nesting is
    searched, so ``list[dict[str, Any]]`` is one. A mapping whose value type is
    itself a mapping is not erased by that - ``dict[str, dict[str, Any]]`` is
    one, the inner one - because ``dict`` is a constraint even when what it
    contains is not.

    An alias, and equally a ``TypedDict``, is counted where it is defined and
    not where it is used, because the definition is the one place a fix has to
    happen: typing ``D = dict[str, Any]`` fixes every reference to ``D`` at
    once. Counting the references instead would make the number track how
    popular a type is rather than how much erasure there is, and would inflate
    the debt of exactly the codebase that had centralised it well.

    ``values`` is the set of value types treated as constraining nothing.
    ADR-063's boundary gate widens it to include ``str``, because a
    ``dict[str, str]`` crossing a context boundary smuggles domain identity
    just as effectively. The ratchet itself uses the default. It does not reach
    ``TypedDict``, whose fault is not erasure - see ``TYPED_DICT_NAME``.

    Raises ``SyntaxError`` if ``source`` does not parse. Callers must not
    swallow it: a file that cannot be measured has an unknown count, not a
    count of zero.
    """
    tree = ast.parse(source)
    collector = _DictShapedStateCollector(values, _renames(tree))
    collector.visit(tree)
    return collector.found


def contains_dict_shaped_state(
    node: ast.expr, *, values: frozenset[str] = UNCONSTRAINED_VALUES
) -> bool:
    """Whether a type expression declares dict-shaped structured state.

    The node-level entry to the same definition ``find_dict_shaped_state``
    uses, for callers that have already parsed and hold a single annotation.
    Quoted and nested spellings are followed here too, so a caller cannot be
    fooled by a form the ratchet would have caught.

    Two shapes are unreachable from an expression and so never answer true
    here: a ``TypedDict`` declaration is a statement, and a rename cannot be
    undone without the module that made it. An annotation naming a
    ``TypedDict`` is not itself the declaration, so this is the same answer
    ``find_dict_shaped_state`` gives for that line.
    """
    collector = _DictShapedStateCollector(values, {})
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
            count += len(find_dict_shaped_state(py_file.read_text()))
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
