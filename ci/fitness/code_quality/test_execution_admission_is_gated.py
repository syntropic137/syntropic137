"""Fitness function: every execution admission path consults the gate (#1387).

A gate with one unguarded entrance is not a gate. The HTTP route is the
entrance everybody remembers; the ones that get forgotten are the trigger
paths - webhooks, the Events API poller, the Checks API poller - because no
operator is standing at them when a deploy starts.

So this does not carry a list of the paths. A list is a third declaration of
something already declared twice, and it drifts silently the moment someone
adds a fourth entrance. Instead the admission paths are DISCOVERED from the
AST, by the two things an admission does and cannot avoid doing:

    * constructing an ``ExecuteWorkflowCommand`` - admitting work directly
    * calling ``run_workflow(...)`` - admitting work through the dispatcher

Every production module that does either must also name the gate. A new
admission path fails this test on the day it is written, which is the only
day fixing it is cheap.

The failure mode a discovery check has of its own is going vacuous: an anchor
that matches nothing passes everywhere. So each anchor must find at least one
site, and the composition root must be seen passing the port.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from ci.fitness.conftest import production_files, rel_path, repo_root

#: Constructing this command IS admitting an execution.
_COMMAND = "ExecuteWorkflowCommand"

#: Calling this hands work to the background dispatcher.
_DISPATCH_METHOD = "run_workflow"

#: The single composition root for the handler, which must be given the port.
_HANDLER = "ExecuteWorkflowHandler"

#: Where the gate is declared. Named here so a rename breaks this test loudly
#: rather than leaving it matching a token nothing uses any more.
_GATE_MODULE = Path("packages/syn-domain/src/syn_domain/contexts/_shared/maintenance.py")
_GATE_FUNCTION = "refuse_if_paused"

#: Any of these identifiers means the module has the gate in hand. A comment
#: mentioning maintenance does not count - these are matched against the AST.
_GATE_NAMES = frozenset(
    {
        _GATE_FUNCTION,
        "MaintenancePausedError",
        "MaintenancePort",
        "get_maintenance_port",
        "maintenance",
        "_maintenance",
        "_refuse_while_paused",
    }
)


def _identifiers(tree: ast.AST) -> set[str]:
    """Every name, attribute and keyword argument written in the module."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            found.add(node.arg)
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name.rsplit(".", 1)[-1])
    return found


def _called_names(tree: ast.AST) -> set[str]:
    """The names actually CALLED, so a class definition is not a construction."""
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    return called


def _discover() -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Return (admission sites, per-anchor counts) across production code."""
    root = repo_root()
    sites: list[tuple[str, str]] = []
    counts = {_COMMAND: 0, _DISPATCH_METHOD: 0}

    for py_file in production_files(root):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        called = _called_names(tree)
        for anchor in (_COMMAND, _DISPATCH_METHOD):
            if anchor in called:
                counts[anchor] += 1
                sites.append((rel_path(py_file, root), anchor))

    return sites, counts


_SITES, _COUNTS = _discover()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path,anchor",
    _SITES,
    ids=[f"{p.split('/')[-1]}::{a}" for p, a in _SITES] if _SITES else [],
)
def test_every_admission_path_names_the_gate(file_path: str, anchor: str) -> None:
    tree = ast.parse((repo_root() / file_path).read_text(encoding="utf-8"))
    assert _GATE_NAMES & _identifiers(tree), (
        f"{file_path} admits executions (it calls {anchor}) but never consults "
        f"the maintenance gate. Every admission path must refuse while "
        f"maintenance mode is set (#1387) - see {_GATE_MODULE}. "
        f"A new entrance is a new hole in the deploy drain."
    )


@pytest.mark.architecture
@pytest.mark.parametrize("anchor", [_COMMAND, _DISPATCH_METHOD])
def test_the_anchor_still_matches_something(anchor: str) -> None:
    """A discovery check that discovers nothing passes over everything."""
    assert _COUNTS[anchor] > 0, (
        f"No production module calls {anchor!r}. Either admission moved to a "
        f"new shape - in which case this fitness function is now blind and the "
        f"anchor must be updated - or the call was renamed."
    )


@pytest.mark.architecture
def test_the_gate_is_where_this_test_says_it_is() -> None:
    """Pins _GATE_NAMES to reality, so it cannot decay into dead tokens."""
    path = repo_root() / _GATE_MODULE
    assert path.exists(), f"{_GATE_MODULE} is gone; _GATE_NAMES no longer names the gate."
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    assert _GATE_FUNCTION in defined, (
        f"{_GATE_MODULE} no longer defines {_GATE_FUNCTION!r}. Update _GATE_NAMES "
        f"to the new name, or every check above is matching a token that no "
        f"longer gates anything."
    )


@pytest.mark.architecture
def test_the_handler_is_constructed_with_the_port() -> None:
    """The handler's backstop is optional so fixtures stay cheap, which means
    production passing it is exactly the thing nobody would notice losing."""
    root = repo_root()
    constructions: list[tuple[str, bool]] = []

    for py_file in production_files(root):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == _HANDLER
            ):
                passed = any(kw.arg == "maintenance" for kw in node.keywords)
                constructions.append((rel_path(py_file, root), passed))

    assert constructions, (
        f"No production module constructs {_HANDLER}. The composition root "
        f"moved or was renamed; this check is now blind."
    )
    ungated = [path for path, passed in constructions if not passed]
    assert not ungated, (
        f"{_HANDLER} is constructed without maintenance= in: {', '.join(ungated)}. "
        f"The handler's gate is the backstop for admission paths that forget "
        f"their own refusal (#1387); unwired, it refuses nothing."
    )
