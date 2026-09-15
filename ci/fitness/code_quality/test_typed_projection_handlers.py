"""Fitness function: projection event handlers accept a typed payload (#1268).

A projection's event handlers are dispatched by name off an event envelope,
and every dispatch path flattens the event with ``model_dump()`` first
(``checkpoint.py``, ``projection_adapters.py``). So the handler receives a
dict, and what it declares about that dict is the only thing standing between
the typed event class and the read model.

Today most of them declare nothing::

    def _apply_session_completed(existing: dict[str, Any], event_data: dict) -> None:
        existing["input_tokens"] = event_data.get("total_input_tokens", 0)

``SessionCompletedEvent`` declares ``total_input_tokens: int`` as a required
field three files away. The projection re-derives it by string key, and
``existing["input_tokens"] = event_data.get("status")`` would typecheck just
as cleanly. The contract is typed at the source and untyped at the consumer.

**This gate measures that population; it does not migrate it.** Every site
present when the gate landed is grandfathered in
``ci/fitness/fitness_exceptions.toml``. A new one fails.

Why that is worth landing on its own: these sites were not budgeted debt, they
were *unmeasured* debt. ``check_untyped_dicts.py`` scores a bare ``dict``
annotation as zero by design (pinned at ``test_check_untyped_dicts.py``), so
70-odd untyped handlers sat inside ``syn-domain``'s budget without ever
consuming a single point of it. Counting them against the package ratchet
would have moved every budget in the file at once; a narrow rule that must be
zero is enforceable in a way a global budget of 440 never is.

What counts as a violation:
- A function named ``on_*``, ``_apply_*`` or ``_accumulate_*``
- in a projection module (see ``is_projection_module``),
- with a parameter annotated as dict-shaped structured state.

``bare_mapping=True`` is the load-bearing argument. ``dict[str, Any]`` erases
its values; a bare ``dict`` declares nothing at all. The package ratchet counts
only the first, which is precisely how this population stayed invisible.

Every annotated parameter is checked, not just the payload. Picking out "the
payload" would need a heuristic over parameter names - ``event_data``,
``event``, ``data``, ``payload`` are all in use - and guessing structure from a
string is the defect this gate exists to stop. ``existing: dict[str, Any]``,
the read-model row, is the same untyped boundary reached from the other side.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
Issue:    #1268
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from check_untyped_dicts import module_shapes

_EXCEPTION_SECTION = "typed_projection_handlers"

#: Dispatched handlers and the helpers they hand the payload straight to. The
#: ``on_`` prefix is not a convention here, it IS the dispatch contract:
#: ``AutoDispatchProjection`` looks up ``on_<event_name>`` by name. ``_apply_``
#: and ``_accumulate_`` are where those handlers put the body, so the untyped
#: payload crosses into them unchanged.
_HANDLER_PREFIXES = ("on_", "_apply_", "_accumulate_")


def is_projection_module(path: Path) -> bool:
    """Whether ``path`` is a projection module.

    Deliberately not ``contexts/*/slices/*/projection.py``, which is where the
    issue's reproduction lives. Nine sites sit one directory outside that glob
    - ``organization/_shared/organization_projection.py`` and the adapters'
    ``projections/`` package - and they are the same handlers with the same
    untyped payload. A scope that names a slice path excuses them for where
    they are filed, and lets the next one be excused by being moved.
    """
    return (
        path.name == "projection.py"
        or path.name.endswith("_projection.py")
        or "projections" in path.parts
    )


class Violation(NamedTuple):
    """One handler parameter that declares dict-shaped state."""

    qualname: str
    parameter: str
    line: int
    annotation: str

    def key(self, file_path: str) -> str:
        """The ``fitness_exceptions.toml`` key grandfathering this site."""
        return f"{file_path}:{self.qualname}.param:{self.parameter}"


class _HandlerVisitor(ast.NodeVisitor):
    """Collect untyped parameters of projection handlers in one module."""

    def __init__(self, tree: ast.Module) -> None:
        self._shapes = module_shapes(tree)
        self._scope: list[str] = []
        self.violations: list[Violation] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name.startswith(_HANDLER_PREFIXES):
            self._check_parameters(node)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def _check_parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        qualname = ".".join([*self._scope, node.name])
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            annotation = arg.annotation
            if arg.arg in ("self", "cls") or annotation is None:
                continue
            if self._shapes.contains_dict_shaped_state(annotation, bare_mapping=True):
                self.violations.append(
                    Violation(
                        qualname=qualname,
                        parameter=arg.arg,
                        line=arg.lineno,
                        annotation=ast.unparse(annotation),
                    )
                )


def find_untyped_handler_parameters(source: str) -> list[Violation]:
    """Projection handler parameters in ``source`` that declare no structure.

    Raises ``SyntaxError`` if ``source`` does not parse, and callers must not
    swallow it: a module that cannot be measured has an unknown number of
    violations, not zero of them.
    """
    tree = ast.parse(source)
    visitor = _HandlerVisitor(tree)
    visitor.visit(tree)
    return visitor.violations


def _scan() -> tuple[list[tuple[str, Violation]], frozenset[str]]:
    """Return every live violation, and the keys currently grandfathered."""
    root = repo_root()
    found: list[tuple[str, Violation]] = []
    for py_file in production_files(root):
        if not is_projection_module(py_file):
            continue
        path = rel_path(py_file, root)
        for violation in find_untyped_handler_parameters(py_file.read_text()):
            found.append((path, violation))
    return found, frozenset(load_exceptions(root).get(_EXCEPTION_SECTION, {}))


_VIOLATIONS, _GRANDFATHERED = _scan()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,violation",
    _VIOLATIONS,
    ids=[f"{path}:{v.qualname}.{v.parameter}" for path, v in _VIOLATIONS],
)
def test_projection_handler_declares_a_typed_payload(file_path: str, violation: Violation) -> None:
    """A projection handler parameter must declare its structure.

    The event class already does. Give the parameter a ``@dataclass`` or a
    Pydantic ``BaseModel`` - not a ``TypedDict``, which validates nothing at
    runtime and is read by string key, so it reproduces both halves of the
    defect under a name that looks typed (AGENTS.md; PR #1246, #1248).
    """
    assert violation.key(file_path) in _GRANDFATHERED, (
        f"{file_path}:{violation.line} - {violation.qualname} takes "
        f"`{violation.parameter}: {violation.annotation}`, which declares no structure. "
        f"The event class this handler is dispatched for already types every field; "
        f"take a typed payload rather than re-deriving it by string key (#1268)."
    )


@pytest.mark.architecture
def test_no_stale_grandfathered_handlers() -> None:
    """A fixed site must lose its exception, so the list can only shrink.

    Without this the table is a ratchet in one direction only on paper: typing
    a handler leaves its key behind, and that key is then standing permission
    to untype it again. Three waivers in ``fitness-exceptions.toml`` had gone
    stale exactly this way before anything reported it.
    """
    live = {violation.key(path) for path, violation in _VIOLATIONS}
    stale = sorted(_GRANDFATHERED - live)
    assert not stale, (
        f"{len(stale)} grandfathered handler(s) no longer violate. Delete them "
        f"from [{_EXCEPTION_SECTION}] in ci/fitness/fitness_exceptions.toml:\n  "
        + "\n  ".join(stale)
    )
