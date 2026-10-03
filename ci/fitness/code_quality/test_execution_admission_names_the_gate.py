"""Fitness function: every execution admission path NAMES the gate (#1387).

WHAT THIS PROVES, exactly: for every discovered admission site, some function
lexically enclosing it writes one of :data:`_GATE_NAMES` as an identifier. That
is co-occurrence in a scope, and nothing stronger. It is deliberately named for
what it measures, because the previous name - "admission is gated" - claimed a
property this file has never checked, and an over-claiming gate is worse than a
modest one: it is the reason nobody looks again.

WHAT IT CANNOT PROVE, and is not trying to:

    * that the gate is consulted BEFORE the admission, rather than after it;
    * that it is consulted on the path that actually runs - a `refuse_if_paused`
      in one branch of an `if` vouches for an admission in the other;
    * that the refusal is not caught and discarded two lines later;
    * that the port passed to it is the durable one.

Those are behaviours, and behaviour is proved by tests that RUN the code: see
`test_1387_maintenance_gates_admission.py`,
`test_1387_trigger_dispatch_is_paused_not_dropped.py` and
`test_1387_a_queued_execution_holds_its_lease.py`, which set the flag and
assert what each entrance then does. This check is the cheap, whole-codebase
half - it catches the entrance that was written without the gate anywhere in
sight, which is the mistake that actually happens - and `TestWhatThisCannotProve`
keeps its blind spot written down and executable rather than implied.

A control-flow dominance analysis would close some of that, and was considered.
It was not done here: dominance over `async with`, try/except/else/finally,
early returns and a ticket handed to a closure that is queued for later is a
dataflow problem, and a subtly wrong one would be a WORSE gate than an honest
lexical one - it would claim the strong property while still missing cases, and
the missing cases would be invisible. If it is built, it belongs in its own
file with the counterexample below as its first failing test.

HOW THE SITES ARE FOUND. Not from a list: a list is a third declaration of
something already declared twice, and it drifts silently the moment someone
adds a fourth entrance. The admission paths are DISCOVERED from the AST, by the
two things an admission does and cannot avoid doing:

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


#: What a site that never names the gate is reported as. A location, because
#: the reader has to go and look at exactly one place.
@dataclass(frozen=True)
class _Site:
    anchor: str
    line: int
    scope: str


def _names_written_directly_in(node: ast.AST) -> set[str]:
    """Identifiers written anywhere in this scope, NOT counting nested scopes.

    Excluding nested functions and classes is what keeps the check per-site: a
    gated helper defined beside an ungated one must not vouch for it.

    A SET, so order and reachability are discarded on purpose - this returns
    what the scope mentions, never what it does. Two consequences a reader
    should have in mind: a gate name written after the admission counts, and a
    gate name written in a branch that never runs counts. See the module
    docstring and :class:`TestWhatThisCannotProve`.
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


def admission_sites_not_naming_the_gate(source: str) -> list[_Site]:
    """Every admission in ``source`` whose scope chain never names the gate.

    Named for what it returns. "Ungated" would be a claim about behaviour; this
    is a claim about identifiers, and the difference is the whole of finding C
    on #1387 - a site whose enclosing scope mentions the gate is reported as
    fine here even when the mention cannot reach it.

    A pure function over text so the checker can be driven over cases that do
    not exist in the tree - including the ones it used to miss.
    """
    unnamed: list[_Site] = []

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
                unnamed.append(
                    _Site(anchor=anchor, line=child.lineno, scope=".".join(scope) or "<module>")
                )
            walk(child, scope, gated)

    walk(ast.parse(source), (), gated=False)
    return unnamed


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
def test_every_admission_site_names_the_gate(file_path: str) -> None:
    source = (repo_root() / file_path).read_text(encoding="utf-8")
    unnamed = admission_sites_not_naming_the_gate(source)
    assert not unnamed, (
        f"{file_path} admits executions in scopes that never name the "
        f"maintenance gate, at: "
        + ", ".join(f"{s.scope}() line {s.line} ({s.anchor})" for s in unnamed)
        + f". Every admission path must refuse while maintenance mode is set "
        f"(#1387) - see {_GATE_MODULE}. It is not enough that some OTHER "
        f"function in this module consults the gate: a new entrance is a new "
        f"hole in the deploy drain wherever it is written. "
        f"Naming the gate is the NECESSARY condition this check can measure, "
        f"not a sufficient one - satisfying it by writing the identifier "
        f"somewhere in the scope passes here and still loses executions; the "
        f"behaviour is what the #1387 tests assert."
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
    def test_an_admission_in_an_already_gated_module_is_still_asked(self) -> None:
        """The regression. This module gates one path and not the other; the
        module-wide version of this check passed it."""
        source = """
async def gated(workflow_id: str, gate) -> None:
    await refuse_if_paused(gate)
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))

async def a_new_path_someone_forgot(workflow_id: str) -> None:
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))
"""
        unnamed = admission_sites_not_naming_the_gate(source)

        assert [s.scope for s in unnamed] == ["a_new_path_someone_forgot"]

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
        unnamed = admission_sites_not_naming_the_gate(source)

        assert [s.scope for s in unnamed] == ["Dispatcher.ungated"]

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
        assert admission_sites_not_naming_the_gate(source) == []

    @pytest.mark.architecture
    def test_an_admission_at_module_level_is_caught(self) -> None:
        """Nowhere to put a gate check is not the same as not needing one."""
        source = "task = run_workflow(workflow_id='wf-x')\n"

        assert [s.scope for s in admission_sites_not_naming_the_gate(source)] == ["<module>"]

    @pytest.mark.architecture
    def test_a_module_that_does_not_admit_reports_nothing(self) -> None:
        """The negative control: a checker that flagged everything would pass
        every assertion above."""
        source = """
async def unrelated(x):
    return await something_else(x)
"""
        assert admission_sites_not_naming_the_gate(source) == []

    @pytest.mark.architecture
    def test_a_comment_naming_the_gate_does_not_count(self) -> None:
        """Matched against the AST, so prose cannot satisfy it."""
        source = '''
async def looks_gated(wf):
    # maintenance mode: refuse_if_paused, AdmissionTicket, admitting
    """See AdmissionGate - admitted, ticket, MaintenancePausedError."""
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=wf))
'''
        assert [s.scope for s in admission_sites_not_naming_the_gate(source)] == ["looks_gated"]


class TestWhatThisCannotProve:
    """The counterexample, kept executable.

    Each of these is ACCEPTED by the check above, and each is a case where the
    gate is named but does not guard the admission. They are here so the
    limitation cannot be forgotten, and so anyone who does build the dominance
    analysis has its first failing tests already written: flip these to the
    opposite assertion and make them pass.

    They are not marked xfail. Nothing is broken - the check is doing what it
    says it does, which is why it now says something narrower.
    """

    @pytest.mark.architecture
    def test_a_gate_in_one_branch_vouches_for_an_admission_in_the_other(self) -> None:
        """The counterexample from #1387's triage, exactly.

        `refuse_if_paused` is called only when `dry_run` is true, and the
        admission happens only when it is false - so on the path that admits,
        the gate is never consulted. A set of identifiers cannot see that, and
        the site is reported as fine.
        """
        source = """
async def admits_in_one_branch(workflow_id: str, gate, dry_run: bool) -> None:
    if dry_run:
        await refuse_if_paused(gate)
        return
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))
"""
        assert admission_sites_not_naming_the_gate(source) == [], (
            "the check has become branch-aware; this file's docstring and the "
            "name of test_every_admission_site_names_the_gate now understate "
            "what it proves, and should be widened deliberately"
        )

    @pytest.mark.architecture
    def test_a_gate_consulted_after_the_admission_counts(self) -> None:
        """Order is discarded with the rest of the control flow. The work is
        already admitted by the time anything refuses."""
        source = """
async def admits_then_asks(workflow_id: str, gate) -> None:
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))
    await refuse_if_paused(gate)
"""
        assert admission_sites_not_naming_the_gate(source) == []

    @pytest.mark.architecture
    def test_a_swallowed_refusal_counts(self) -> None:
        """Naming `MaintenancePausedError` is how an entrance says it TRANSLATES
        a refusal into its own protocol. Catching it and carrying on is the same
        identifier and the opposite behaviour."""
        source = """
async def swallows(workflow_id: str, gate) -> None:
    try:
        await refuse_if_paused(gate)
    except MaintenancePausedError:
        pass
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=workflow_id))
"""
        assert admission_sites_not_naming_the_gate(source) == []
