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

What makes the value a lie is that the type already spends it. ``list``,
``dict``, ``set``, ``tuple`` and the numbers put their **entire** vocabulary
into real answers: ``[]`` is the answer "I looked, and there are none", ``0``
is "I counted, and it was zero". Nothing is left over to mean "I did not find
out", so a handler returning one asserts something it has just admitted it did
not observe, and no caller can tell which it got.

The question is asked of the **value the handler returns**, not of the
signature around it, and that is deliberate. Widening ``list[Row]`` to
``list[Row] | None`` and leaving ``return []`` in place changes the
declaration and nothing else - ``[]`` is a success value of both, and the
reader is exactly as stuck. So the half-fix stays flagged.

Which also says what a whole fix is: return something the answer domain does
not contain. Widen the type *and* return ``None`` against it, add a companion
(``telemetry_available: bool``), raise a named error the caller has to handle,
or return a small sum type. ``routes/metrics.py`` already does the
named-error one, two lines below one of the violations here -
``MetricsUnavailableError`` exists precisely because "the usage totals could
not be read, so none may be reported".

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
from typing import NamedTuple

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

#: Return types whose every value is a real answer. An empty container is a
#: valid member of its own type - "the query matched nothing" - and zero is a
#: valid count, so neither has a value to spare for "I did not find out".
#:
#: This set is the whole scope decision. Read it alongside ``_is_an_answer``,
#: which walks a union into its members so that widening a signature cannot
#: change a verdict on its own. Spelling does not matter: ``Sequence[X]``,
#: ``collections.abc.Sequence[X]`` and ``"list[X]"`` all reduce to one head.
#:
#: ``bool`` and ``str`` are deliberately absent - see the module docstring for
#: the measurements that put them there.
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


def _unquote(annotation: ast.expr) -> ast.expr:
    """A forward reference is the same type as the thing it names.

    ``"list[Row]"`` and ``list[Row]`` are one question. A rule that read the
    spelling would be evaded by an import-cycle workaround, silently.
    """
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return annotation
    return annotation


def _base_name(annotation: ast.expr) -> str:
    """The head of an annotation: ``list`` for ``collections.abc.list[X]``."""
    annotation = _unquote(annotation)
    if isinstance(annotation, ast.Subscript):
        return _base_name(annotation.value)
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Name):
        return annotation.id
    return ast.unparse(annotation)


def _is_an_answer(annotation: ast.expr | None) -> bool:
    """True when the empty-or-zero value returned here is a real answer of this type.

    The question is about the value the handler hands back, not about the
    declaration around it - which is what closes the cheapest green path there
    is. Widening ``list[Row]`` to ``list[Row] | None`` and still returning
    ``[]`` fixes nothing: ``[]`` is a success value of that type either way,
    and the caller is left exactly as unable to tell. So a union is answered
    by its members - ``list[Row] | None`` still admits ``[]`` as an answer -
    and the escape is to return a value the answer domain does not contain,
    which is what ``return None`` against that same widened type does.

    ``dict[str, list[str] | None]`` matches on its head, correctly: the value
    reaching the caller is the outer mapping, and an empty one claims every
    key was looked up and found nothing.
    """
    if annotation is None:
        return False  # Unannotated: nothing declared, so nothing to contradict.
    annotation = _unquote(annotation)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_an_answer(annotation.left) or _is_an_answer(annotation.right)
    if isinstance(annotation, ast.Subscript) and _base_name(annotation.value) == "Optional":
        return _is_an_answer(annotation.slice)
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
        if not _is_an_answer(func.returns):
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


class SeededSite(NamedTuple):
    """One grandfathered site, as the exceptions file records it."""

    key: str
    issue: str

    @property
    def is_tracked(self) -> bool:
        """An entry with no issue is a silence, not a decision."""
        return self.issue.startswith("#")


def _seeded() -> dict[str, SeededSite]:
    """The grandfathered table, keyed by ``<file>:<qualname>``."""
    raw = load_exceptions(repo_root()).get("unknown_has_a_representation", {})
    return {
        key: SeededSite(
            key=key,
            issue=str(entry.get("issue", "")) if isinstance(entry, dict) else "",
        )
        for key, entry in raw.items()
    }


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
        untracked = sorted(site.key for site in _seeded().values() if not site.is_tracked)

        assert not untracked, (
            "Seeded sites without an issue reference: " + ", ".join(untracked) + "\n"
            'Each entry needs `{ issue = "#NNN" }` naming where the fix is tracked.'
        )


# -- The rule's edges, pinned on synthetic source -----------------------------
#
# Driven through ``find_ignorant_returns`` rather than the repo, so the rule
# stays asserted when the sites it currently finds are fixed. Each "does not
# see" test below pins a hole the module docstring declares, with the
# measurement that put it there - a documented hole gets fixed, a hole
# certified as closed does not.


def _findings(source: str) -> list[IgnorantReturn]:
    return find_ignorant_returns(source, "example.py")


def test_an_empty_list_from_a_broad_except_is_a_violation() -> None:
    """The shape #1341 was written from: a telemetry outage read as a stall."""
    findings = _findings(
        """
async def load_operations(session_id: str) -> list[ToolOperation]:
    try:
        return await query(session_id)
    except Exception:
        logger.exception("failed")
        return []
"""
    )
    assert [f.qualname for f in findings] == ["load_operations"]
    assert findings[0].returned == "[]"


def test_a_zero_count_from_a_broad_except_is_a_violation() -> None:
    """``0`` is the answer "I counted, and it was zero", not "I did not count"."""
    findings = _findings(
        """
def count_tools(execution_id: str) -> int:
    try:
        return fetch_count(execution_id)
    except Exception:
        return 0
"""
    )
    assert [f.returned for f in findings] == ["0"]


def test_a_narrow_except_is_not_a_violation() -> None:
    """Catching a named condition maps a known case onto a value. That is a decision."""
    assert not _findings(
        """
def load(path: str) -> list[str]:
    try:
        return read(path)
    except FileNotFoundError:
        return []
"""
    )


def test_the_fix_this_gate_recommends_makes_it_green() -> None:
    """Widening the container to ``| None`` is the first fix the message names,
    so it has to be the fix that satisfies the rule. If it did not, every site
    would reach for an exception entry instead.

    This is also the legitimate "not found returns None". ``None`` is distinct
    from every real list, and pyright makes each caller narrow before use - so
    whoever wrote the call site was made to think about the absent case. ``[]``
    forces no such branch: it flows into ``len()``, ``for`` and a rendered
    number, and nobody is ever asked.
    """
    before = """
async def load_operations(session_id: str) -> list[ToolOperation]:
    try:
        return await query(session_id)
    except Exception:
        return []
"""
    after = """
async def load_operations(session_id: str) -> list[ToolOperation] | None:
    try:
        return await query(session_id)
    except Exception:
        return None
"""
    assert [f.qualname for f in _findings(before)] == ["load_operations"]
    assert not _findings(after)


def test_widening_the_type_but_still_returning_empty_is_not_a_fix() -> None:
    """The cheapest green path, closed.

    Adding ``| None`` to the signature and leaving ``return []`` in the handler
    changes the declaration and nothing else: ``[]`` is a success value of
    ``list[Row] | None`` exactly as it was of ``list[Row]``, and the caller is
    left just as unable to tell. The gate asks what the handler returns, so
    the half-fix stays flagged and only the whole one goes green.
    """
    half_fixed = """
async def load_operations(session_id: str) -> list[ToolOperation] | None:
    try:
        return await query(session_id)
    except Exception:
        return []
"""
    assert [f.qualname for f in _findings(half_fixed)] == ["load_operations"]


def test_an_optional_wrapper_is_read_through() -> None:
    """``Optional[list[Row]]`` and ``list[Row] | None`` are the same type, so a
    site cannot move between the two spellings to change its verdict.
    """
    assert [
        f.qualname
        for f in _findings(
            """
def load(key: str) -> Optional[list[Row]]:
    try:
        return fetch(key)
    except Exception:
        return []
"""
        )
    ] == ["load"]


def test_a_false_is_not_read_as_a_zero() -> None:
    """``isinstance(False, int)`` is True in Python and ``False == 0``. Without
    a guard, a ``bool`` returned from an ``int`` function would be reported as
    the number zero - a finding about a value the code never wrote.
    """
    assert not _findings(
        """
def count(key: str) -> int:
    try:
        return fetch(key)
    except Exception:
        return False
"""
    )


def test_a_returned_name_is_not_read_as_empty() -> None:
    """Only literals. A name may hold anything, and a gate that guessed would be
    reporting on what it cannot see.
    """
    assert not _findings(
        """
def load(key: str) -> list[str]:
    try:
        return fetch(key)
    except Exception:
        return fallback
"""
    )


def test_a_real_fallback_value_is_not_a_violation() -> None:
    """A handler that returns something distinguishable has already done the work."""
    assert not _findings(
        """
def load(key: str) -> list[str]:
    try:
        return fetch(key)
    except Exception:
        return ["<unavailable>"]
"""
    )


def test_a_dotted_or_quoted_container_annotation_is_still_a_container() -> None:
    """``Sequence[X]``, ``collections.abc.Sequence[X]`` and ``"list[X]"`` are one question.

    A rule that measured the spelling would be evaded by an import style, which
    is the #1188 defect: a number that moves, or stays still, for a rename.
    """
    dotted = _findings(
        """
def load(key: str) -> collections.abc.Sequence[Row]:
    try:
        return fetch(key)
    except Exception:
        return []
"""
    )
    quoted = _findings(
        """
def load(key: str) -> "list[Row]":
    try:
        return fetch(key)
    except Exception:
        return []
"""
    )
    assert [f.qualname for f in dotted] == ["load"]
    assert [f.qualname for f in quoted] == ["load"]


def test_a_nested_function_is_read_against_its_own_return_type() -> None:
    """An inner handler belongs to the inner contract, not the outer one.

    Attributing it outwards would report the wrong return type for the wrong
    value - and here it would invent a violation, since the outer function is
    Optional and the inner one is not.
    """
    findings = _findings(
        """
def outer(key: str) -> list[Row] | None:
    def inner() -> list[Row]:
        try:
            return fetch(key)
        except Exception:
            return []
    return inner()
"""
    )
    assert [f.qualname for f in findings] == ["outer.inner"]


def test_a_method_is_keyed_by_its_class() -> None:
    """The exceptions key is a qualname, so two methods of the same name in one
    file are separate entries - and a fix that moves a line keeps its key.
    """
    findings = _findings(
        """
class ArtifactCollector:
    def collect(self) -> list[str]:
        try:
            return self._collect()
        except Exception:
            return []
"""
    )
    assert findings[0].key == "example.py:ArtifactCollector.collect"


def test_the_message_names_the_site_and_what_a_reader_cannot_tell() -> None:
    """The failure text is the deliverable: the fix is always to add a
    representation for unknown, so the message has to point at the confusion.
    """
    finding = _findings(
        """
def load(key: str) -> list[Row]:
    try:
        return fetch(key)
    except Exception:
        return []
"""
    )[0]
    described = finding.describe()
    assert "example.py:6" in described
    assert "load()" in described
    assert "an exception here returns [], which is also what a successful empty query returns" in (
        described
    )
    assert "I could not find out" in described


# -- Holes this gate declares, each with the reason it stays open -------------


def test_the_gate_does_not_see_a_bool_return() -> None:
    """Measured 10 sites, 1 genuine. The other nine are a function reporting on
    its own attempt, where the exception IS the answer. At nine-to-one this
    half would be silenced rather than fixed.
    """
    assert not _findings(
        """
async def health_check(self) -> bool:
    try:
        return await probe()
    except Exception:
        return False
"""
    )


def test_the_gate_does_not_see_an_empty_string_return() -> None:
    """Whether ``''`` is a real answer is a fact about the domain, not the type.
    The one site in this repo uses it as a documented sentinel for exactly the
    unknown this rule is about.
    """
    assert not _findings(
        """
async def resolve_installation_id(repo: str) -> str:
    try:
        return str(await lookup(repo))
    except Exception:
        return ""
"""
    )


def test_the_gate_does_not_see_a_none_guard() -> None:
    """Measured 91 sites; most are ``if not ids: return []``, where empty in
    genuinely means empty out. The separator is whether ``None`` means "the
    source was unavailable" or "the source answered, and the answer is
    nothing" - semantics the AST does not carry.
    """
    assert not _findings(
        """
async def get_session_tools(proj: Projection, session_id: str) -> list[Any]:
    pool = get_pool(proj)
    if pool is None:
        return []
    return await query(pool, session_id)
"""
    )


def test_the_gate_does_not_see_a_fallthrough_zero() -> None:
    """``AgentExecutionHandler._detect_exit_code``, one of #1341's own three
    sites: a ``None`` exit code becomes ``0``, so an externally removed
    container reads as clean success. There is no except block - the zero
    arrives by falling through past a nullable local, which needs dataflow
    rather than pattern matching. Fixed on PR #1330 (#1319), not by this gate.
    """
    assert not _findings(
        """
def _detect_exit_code(workspace: ManagedWorkspace) -> int:
    stream_exit_code = workspace.last_stream_exit_code
    if stream_exit_code is not None and stream_exit_code != 0:
        return stream_exit_code
    return 0
"""
    )
