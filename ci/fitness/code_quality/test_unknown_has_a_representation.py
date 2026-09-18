"""Fitness function: a value that can be unknown needs a way to say so.

Issue #1341. Three defects found in separate reviews turned out to be one
convention problem: a value that can be **unknown** was represented with a
token that already means something real - ``0``, ``[]`` - so "we could not
find out" arrived at the reader as a measurement. Every collapse pointed the
unsafe way, toward the reading that tells an operator to stop paying
attention.

The sharpest of the three: the telemetry query behind the stall detector
returns ``[]`` when it raises, so the feature built to tell "busy" from
"stuck" reports *stuck* whenever its own telemetry breaks - and "stuck" is
the verdict that tells an operator not to spend money retrying.

## The rule

An **ignorant branch** - one that has just established it does not have the
answer - must not return a value that its own return type reserves for a real
answer.

Ignorance is recognised from a broad ``except`` handler: ``except Exception``
or a bare ``except``. That is the code saying, in its own words, that
something it did not anticipate went wrong, so it does not know.

The return type decides whether the value is a lie. ``list``, ``dict``,
``set``, ``tuple`` and the numbers spend their **entire** vocabulary on real
answers: ``[]`` is the answer "I looked, and there are none", ``0`` is "I
counted, and it was zero". There is no spare value left to mean "I did not
find out". So a handler returning one is asserting something it just admitted
it did not observe, and no caller can tell.

The fix is never to pick a different empty value. It is to give unknown a
representation: widen the type (``list[T] | None``), add a companion
(``telemetry_available: bool``), raise a named error, or return a small sum
type. ``routes/metrics.py`` already does the last-but-one, two lines below one
of the violations - ``MetricsUnavailableError`` exists precisely because "the
usage totals could not be read, so none may be reported".

## Why this shape, and not the wider ones

A rule with a bad false-positive rate does not get fixed, it gets an exception
entry. Three wider shapes were measured against this repo and rejected. Each
has a test below pinning that the gate does **not** see it, so the hole stays
documented rather than being quietly certified closed.

``bool`` returns are out. Measured: 10 broad-except handlers returning
``False``, of which 1 is this defect. The other nine are a function reporting
on *its own attempt* - ``delete()``, ``interrupt_container()``,
``health_check()`` - where the exception genuinely is the answer: the delete
did not land, the sidecar is not responding. Separating those from
``_produced_deliverable()`` needs the meaning of the predicate, not its shape,
so at nine-to-one this half would be silenced rather than fixed.

``str`` returning ``''`` is out, for the opposite reason. Whether ``''`` is a
real answer is a fact about the domain, not the type: the one site in this
repo (``_resolve_installation_id``) uses ``''`` as a deliberate sentinel, and
says so in the log line and in the trigger that skips on it. That IS a
representation for unknown. An empty *container*, by contrast, is a valid
member of its type by construction - a query can always return zero rows - so
for containers the question needs no domain knowledge.

``if <source> is None: return <zero>`` is out. Measured: 91 sites, and the
large majority are ``if not execution_ids: return []`` - a guard where empty
in genuinely means empty out. Narrowing to a subject that is not a parameter
leaves 15, of which roughly a quarter are still correct (``if metadata is
None: return {}`` after a YAML parse, where ``None`` is how the parser spells
an empty document). The separator is whether ``None`` means "the source was
unavailable" or "the source answered, and the answer is nothing" - semantics
the AST does not carry.

That last exclusion has a cost worth stating plainly: **the gate cannot see
one of the three sites in #1341.** ``AgentExecutionHandler._detect_exit_code``
collapses a ``None`` exit code into ``0`` - an externally removed container
reads as clean success - and it does it with no ``except`` block at all, by
falling through to ``return 0`` after a nullable local. Catching that needs
dataflow, not pattern matching. It is fixed on its own PR (#1330);
``test_the_gate_does_not_see_a_fallthrough_zero`` pins that this gate is not
what caught it.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, NamedTuple

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

if TYPE_CHECKING:
    from pathlib import Path

#: Return types whose every value is a real answer. An empty container is a
#: valid member of its own type - "the query matched nothing" - and zero is a
#: valid count, so neither has a value to spare for "I did not find out".
#: Spelled by the top-level name only: ``list[ToolOperation]``,
#: ``dict[str, Decimal]`` and ``collections.abc.Sequence[X]`` are all the same
#: question. ``bool`` and ``str`` are deliberately absent - see the module
#: docstring for the measurements that put them there.
_ANSWER_ONLY_RETURNS = frozenset(
    {
        "list",
        "dict",
        "set",
        "frozenset",
        "tuple",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Collection",
        "Iterable",
        "int",
        "float",
        "Decimal",
    }
)


class IgnorantReturn(NamedTuple):
    """A branch that returned a real-looking answer after admitting it has none."""

    path: str
    line: int
    qualname: str
    returned: str
    annotation: str

    @property
    def key(self) -> str:
        """The exceptions-file key. Qualname, not line: a fix moves the line."""
        return f"{self.path}:{self.qualname}"

    def describe(self) -> str:
        """The finding, in the terms a reader has to distinguish."""
        return (
            f"{self.path}:{self.line} {self.qualname}() -> {self.annotation}\n"
            f"      an exception here returns {self.returned}, which is also what a"
            f" successful empty query returns.\n"
            f"      A caller cannot tell "
            f"{_reading(self.returned)} from {_unknown_reading(self.returned)}."
        )


def _reading(returned: str) -> str:
    """What the returned value claims, in the reader's words."""
    if returned in {"0", "0.0"}:
        return '"I counted, and it was zero"'
    return '"I looked, and there are none"'


def _unknown_reading(returned: str) -> str:
    """What actually happened, which the value does not say."""
    return '"I could not find out"'


def _empty_literal(node: ast.expr) -> str | None:
    """The spelling of a zero-value literal, or None when it is a real value.

    Only literals. A returned *name* may hold anything, and a gate that guessed
    would be reporting on what it could not see.
    """
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return None  # ``False`` is out of scope - see the module docstring.
        if isinstance(value, (int, float)) and value == 0:
            return repr(value)
        return None
    if isinstance(node, ast.List) and not node.elts:
        return "[]"
    if isinstance(node, ast.Dict) and not node.keys:
        return "{}"
    if isinstance(node, ast.Set) and not node.elts:
        return "set()"
    if isinstance(node, ast.Tuple) and not node.elts:
        return "()"
    if (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and isinstance(node.func, ast.Name)
        and node.func.id in {"list", "dict", "set", "tuple", "frozenset"}
    ):
        return f"{node.func.id}()"
    return None


def _admits_none(annotation: ast.expr | None) -> bool:
    """True when the type already carries a token outside the answer domain.

    ``X | None`` is not this defect. ``None`` is distinct from every real ``X``,
    and pyright makes every caller narrow before use - so whoever wrote the call
    site was made to think about the absent case. ``[]`` and ``0`` force no such
    branch: they flow into ``len()``, ``for`` and a rendered number, and nobody
    is ever asked.
    """
    if annotation is None:
        return True  # Unannotated: nothing declared, so nothing to contradict.
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return True
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _admits_none(annotation.left) or _admits_none(annotation.right)
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return True
    return _base_name(annotation) in {"Optional", "Any", "object", "None"}


def _base_name(annotation: ast.expr) -> str:
    """The head of an annotation: ``list`` for ``collections.abc.list[X]``."""
    if isinstance(annotation, ast.Subscript):
        return _base_name(annotation.value)
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Name):
        return annotation.id
    return ast.unparse(annotation)


def _answers_only(annotation: ast.expr | None) -> bool:
    """True when every value of this return type is a real answer."""
    if annotation is None or _admits_none(annotation):
        return False
    return _base_name(annotation) in _ANSWER_ONLY_RETURNS


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """True for ``except Exception`` and bare ``except`` - the code saying it does not know.

    A narrow ``except FileNotFoundError`` is a deliberate mapping of a named
    condition onto a value, which is a decision, not an absence of one.
    """
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Tuple):
        return any(_is_broad_name(e) for e in handler.type.elts)
    return _is_broad_name(handler.type)


def _is_broad_name(node: ast.expr) -> bool:
    return _base_name(node) in {"Exception", "BaseException"}


def _functions(tree: ast.Module) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function with its qualname, so a method is named by its class."""
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append((f"{prefix}{child.name}", child))
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def find_ignorant_returns(source: str, path: str) -> list[IgnorantReturn]:
    """Every answer-shaped value returned from a broad except handler.

    Public because the test that pins this gate's behaviour drives it directly
    on source text, which is the only way to keep the rule's edges asserted
    without depending on what happens to be in the repo today.
    """
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    findings: list[IgnorantReturn] = []
    for qualname, func in _functions(tree):
        if not _answers_only(func.returns):
            continue
        annotation = ast.unparse(func.returns) if func.returns else "?"
        for handler in _broad_handlers(func):
            for stmt in ast.walk(handler):
                if not isinstance(stmt, ast.Return) or stmt.value is None:
                    continue
                returned = _empty_literal(stmt.value)
                if returned is None:
                    continue
                findings.append(
                    IgnorantReturn(
                        path=path,
                        line=stmt.lineno,
                        qualname=qualname,
                        returned=returned,
                        annotation=annotation,
                    )
                )
    return sorted(findings, key=lambda f: f.line)


def _broad_handlers(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.ExceptHandler]:
    """Broad handlers belonging to this function, not to one nested inside it.

    A nested function has its own return type; attributing its handlers here
    would report the wrong contract for the wrong value.
    """
    handlers: list[ast.ExceptHandler] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(child, ast.ExceptHandler):
                if _is_broad(child):
                    handlers.append(child)
                continue
            walk(child)

    walk(func)
    return handlers


def _seeded() -> dict[str, object]:
    return load_exceptions(repo_root()).get("unknown_has_a_representation", {})


def _scan() -> list[IgnorantReturn]:
    root = repo_root()
    findings: list[IgnorantReturn] = []
    for py_file in production_files(root):
        rp = rel_path(py_file, root)
        findings.extend(find_ignorant_returns(py_file.read_text(encoding="utf-8"), rp))
    return findings


pytestmark = [pytest.mark.architecture, pytest.mark.unit]


class TestUnknownHasARepresentation:
    def test_no_new_answer_shaped_value_from_a_broad_except(self) -> None:
        """A handler that does not know must not return a value that claims to."""
        seeded = _seeded()
        unseeded = [f for f in _scan() if f.key not in seeded]

        if unseeded:
            joined = "\n\n  ".join(f.describe() for f in unseeded)
            pytest.fail(
                f"{len(unseeded)} branch(es) return a real-looking answer after"
                " catching an exception:\n\n"
                f"  {joined}\n\n"
                "The fix is not a different empty value - every value of these"
                " return types is already\n"
                "an answer. Give unknown a representation: widen the type"
                " (`list[T] | None`), add a\n"
                "companion field (`telemetry_available: bool`), raise a named"
                " error the caller must\n"
                "handle (see `MetricsUnavailableError` in routes/metrics.py), or"
                " return a sum type.\n"
                "See #1341 and the docstring of this module."
            )

    def test_no_stale_seeded_sites(self) -> None:
        """A fixed site must lose its entry in the same diff that fixes it.

        Otherwise the table grants standing permission to reintroduce exactly
        the defect it recorded, and nothing reports that it has gone stale.
        """
        live = {f.key for f in _scan()}
        stale = sorted(key for key in _seeded() if key not in live)

        if stale:
            joined = "\n  ".join(stale)
            pytest.fail(
                f"{len(stale)} seeded site(s) no longer violate the rule:\n"
                f"  {joined}\n\n"
                "Delete them from [unknown_has_a_representation] in"
                " ci/fitness/fitness_exceptions.toml.\n"
                "A ratchet that keeps paid-off entries is not a ratchet."
            )

    def test_every_seeded_site_names_an_issue(self) -> None:
        """Seeded debt is tracked debt. An entry with no issue is a silence."""
        entries = _seeded()
        missing = sorted(
            key
            for key, value in entries.items()
            if not (isinstance(value, dict) and str(value.get("issue", "")).startswith("#"))
        )
        assert not missing, (
            "Seeded sites without an issue reference: " + ", ".join(missing) + "\n"
            'Each entry needs `{ issue = "#NNN" }` naming where the fix is tracked.'
        )
