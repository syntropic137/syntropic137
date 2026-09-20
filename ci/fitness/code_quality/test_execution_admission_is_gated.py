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

**The granularity is the call site, not the module.** That distinction is the
whole value of this check and it was missing until now: the first version
asked whether the module containing an admission mentioned the gate anywhere,
which meant every module that already had a gated path was a free pass for
every path added to it afterwards. Verification demonstrated it - a second,
entirely ungated admission function appended to ``routes/executions/commands.py``
and all seven tests stayed green. The module a new admission is most likely to
be written in is precisely a module that already admits something.

So each site is asked about on its own: the function it is written in - or a
function lexically enclosing that one, since a closure can be handed a ticket -
must name the gate. "Name the gate" is matched against the AST, never the
text, so a comment about maintenance mode buys nothing.

The failure mode a discovery check has of its own is going vacuous: an anchor
that matches nothing passes everywhere. So each anchor must find at least one
site, the composition root must be seen passing the port, and
``TestTheCheckerItself`` drives the checker over synthetic modules - including
the exact false negative above - so this file cannot quietly stop checking.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest
from ci.fitness.conftest import production_files, rel_path, repo_root

#: Constructing this command IS admitting an execution.
_COMMAND = "ExecuteWorkflowCommand"

#: Calling this hands work to the background dispatcher.
_DISPATCH_METHOD = "run_workflow"

_ANCHORS = (_COMMAND, _DISPATCH_METHOD)

#: The single composition root for the handler, which must be given the port.
_HANDLER = "ExecuteWorkflowHandler"

#: Where the gate is declared. Named here so a rename breaks this test loudly
#: rather than leaving it matching a token nothing uses any more.
_GATE_MODULE = Path("packages/syn-domain/src/syn_domain/contexts/_shared/maintenance.py")
_GATE_FUNCTION = "refuse_if_paused"

#: Any of these identifiers, written in the function that admits, means that
#: function has the gate in hand. Three ways a function can legitimately have
#: it, and all three must count or the check would force a shape on code rather
#: than a property:
#:
#:   * it consults the gate itself (`refuse_if_paused`, `admitting`, ...)
#:   * it receives the decision (`admitted`, `ticket`) - which is how an
#:     admission that was granted upstream, under the transition lock, avoids
#:     being re-decided inside a fire-and-forget task where a refusal could
#:     only lose the work
#:   * it handles the refusal (`MaintenancePausedError`) to answer in its own
#:     protocol - a 409, a `paused` trigger record
_GATE_NAMES = frozenset(
    {
        _GATE_FUNCTION,
        "AdmissionGate",
        "AdmissionTicket",
        "MaintenancePausedError",
        "MaintenancePort",
        "admitted",
        "admitting",
        "get_admission_gate",
        "get_maintenance_port",
        "maintenance",
        "_maintenance",
        "refuse_early",
        "_refuse_while_paused",
        "_admit_or_409",
        "ticket",
    }
)


#: What an ungated site is reported as. A location, because the reader has to
#: go and look at exactly one place.
@dataclass(frozen=True)
class _Site:
    anchor: str
    line: int
    scope: str


def _names_written_directly_in(node: ast.AST) -> set[str]:
    """Identifiers written in this scope, NOT counting nested scopes.

    Excluding nested functions and classes is what keeps the check per-site: a
    gated helper defined beside an ungated one must not vouch for it.
    """
    found: set[str] = set()

    def visit(current: ast.AST, *, top: bool) -> None:
        if not top and isinstance(
            current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda
        ):
            return
        if isinstance(current, ast.Name):
            found.add(current.id)
        elif isinstance(current, ast.Attribute):
            found.add(current.attr)
        elif isinstance(current, ast.keyword) and current.arg is not None:
            found.add(current.arg)
        elif isinstance(current, ast.alias):
            found.add(current.asname or current.name.rsplit(".", 1)[-1])
        elif isinstance(current, ast.arg):
            found.add(current.arg)
        for child in ast.iter_child_nodes(current):
            visit(child, top=False)

    visit(node, top=True)
    return found


def _anchor_of(call: ast.Call) -> str | None:
    """The admission anchor this call is, if it is one."""
    name = (
        call.func.id
        if isinstance(call.func, ast.Name)
        else call.func.attr
        if isinstance(call.func, ast.Attribute)
        else None
    )
    return name if name in _ANCHORS else None


def ungated_admission_sites(source: str) -> list[_Site]:
    """Every admission in ``source`` whose scope chain never names the gate.

    A pure function over text so the checker can be driven over cases that do
    not exist in the tree - including the ones it used to miss.
    """
    ungated: list[_Site] = []

    def walk(node: ast.AST, scope: tuple[str, ...], gated: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                walk(
                    child,
                    (*scope, child.name),
                    # Lexical, not just innermost: a nested function can be
                    # handed the ticket its enclosing function took out.
                    gated or bool(_GATE_NAMES & _names_written_directly_in(child)),
                )
                continue
            if isinstance(child, ast.ClassDef):
                walk(child, (*scope, child.name), gated)
                continue
            if isinstance(child, ast.Call) and (anchor := _anchor_of(child)) and not gated:
                ungated.append(
                    _Site(anchor=anchor, line=child.lineno, scope=".".join(scope) or "<module>")
                )
            walk(child, scope, gated)

    walk(ast.parse(source), (), gated=False)
    return ungated


def _count_anchors(source: str) -> dict[str, int]:
    counts = dict.fromkeys(_ANCHORS, 0)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and (anchor := _anchor_of(node)):
            counts[anchor] += 1
    return counts


def _discover() -> tuple[list[str], dict[str, int]]:
    """Return (production files that admit, per-anchor counts)."""
    root = repo_root()
    admitting: list[str] = []
    counts = dict.fromkeys(_ANCHORS, 0)

    for py_file in production_files(root):
        try:
            source = py_file.read_text(encoding="utf-8")
            found = _count_anchors(source)
        except SyntaxError:
            continue
        if any(found.values()):
            admitting.append(rel_path(py_file, root))
        for anchor, n in found.items():
            counts[anchor] += n

    return admitting, counts


_ADMITTING_FILES, _COUNTS = _discover()


@pytest.mark.architecture
@pytest.mark.parametrize(
    "file_path",
    _ADMITTING_FILES,
    ids=[p.split("/")[-1] for p in _ADMITTING_FILES] if _ADMITTING_FILES else [],
)
def test_every_admission_site_is_gated(file_path: str) -> None:
    source = (repo_root() / file_path).read_text(encoding="utf-8")
    ungated = ungated_admission_sites(source)
    assert not ungated, (
        f"{file_path} admits executions without consulting the maintenance "
        f"gate at: "
        + ", ".join(f"{s.scope}() line {s.line} ({s.anchor})" for s in ungated)
        + f". Every admission path must refuse while maintenance mode is set "
        f"(#1387) - see {_GATE_MODULE}. It is not enough that some OTHER "
        f"function in this module consults the gate: a new entrance is a new "
        f"hole in the deploy drain wherever it is written."
    )


@pytest.mark.architecture
@pytest.mark.parametrize("anchor", _ANCHORS)
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
    missing = {_GATE_FUNCTION, "AdmissionGate", "AdmissionTicket"} - defined
    assert not missing, (
        f"{_GATE_MODULE} no longer defines {sorted(missing)}. Update _GATE_NAMES "
        f"to the new names, or every check above is matching tokens that no "
        f"longer gate anything."
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


class TestTheCheckerItself:
    """The check above is only as good as what it can see, and what it could
    not see was found by mutation rather than by reading it. These are that
    mutation, kept."""

    @pytest.mark.architecture
    def test_an_ungated_admission_in_an_already_gated_module_is_caught(self) -> None:
        """The regression. This module gates one path and not the other; the
        module-wide version of this check passed it."""
        source = """
async def gated(workflow_id: str, gate) -> None:
    await refuse_if_paused(gate)
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))

async def a_new_path_someone_forgot(workflow_id: str) -> None:
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))
"""
        ungated = ungated_admission_sites(source)

        assert [s.scope for s in ungated] == ["a_new_path_someone_forgot"]

    @pytest.mark.architecture
    def test_a_gated_sibling_does_not_vouch_for_a_nested_one(self) -> None:
        """A helper defined beside an ungated function is a different scope,
        however close together they are written."""
        source = """
class Dispatcher:
    async def gated(self, wf, gate):
        async with gate.admitting() as ticket:
            await self.run_workflow(workflow_id=wf)

    async def ungated(self, wf):
        await self.run_workflow(workflow_id=wf)
"""
        ungated = ungated_admission_sites(source)

        assert [s.scope for s in ungated] == ["Dispatcher.ungated"]

    @pytest.mark.architecture
    def test_a_ticket_handed_to_a_closure_counts(self) -> None:
        """Lexical, so the real HTTP route's shape passes: the ticket is taken
        out in the endpoint and spent in the task it queues."""
        source = """
async def endpoint(wf, gate):
    async with gate.admitting() as ticket:
        async def _run():
            await handler.handle(ExecuteWorkflowCommand(aggregate_id=wf))
        queue(_run)
"""
        assert ungated_admission_sites(source) == []

    @pytest.mark.architecture
    def test_an_admission_at_module_level_is_caught(self) -> None:
        """Nowhere to put a gate check is not the same as not needing one."""
        source = "task = run_workflow(workflow_id='wf-x')\n"

        assert [s.scope for s in ungated_admission_sites(source)] == ["<module>"]

    @pytest.mark.architecture
    def test_a_module_that_does_not_admit_reports_nothing(self) -> None:
        """The negative control: a checker that flagged everything would pass
        every assertion above."""
        source = """
async def unrelated(x):
    return await something_else(x)
"""
        assert ungated_admission_sites(source) == []

    @pytest.mark.architecture
    def test_a_comment_naming_the_gate_does_not_count(self) -> None:
        """Matched against the AST, so prose cannot satisfy it."""
        source = '''
async def looks_gated(wf):
    # maintenance mode: refuse_if_paused, AdmissionTicket, admitting
    """See AdmissionGate - admitted, ticket, MaintenancePausedError."""
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=wf))
'''
        assert [s.scope for s in ungated_admission_sites(source)] == ["looks_gated"]
