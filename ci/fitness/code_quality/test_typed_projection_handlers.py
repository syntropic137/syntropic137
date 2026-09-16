"""Fitness function: projection event handlers accept a typed payload (#1268).

A projection's event handlers are dispatched off an event envelope, and every
dispatch path flattens the event with ``model_dump()`` first (``checkpoint.py``,
``projection_adapters.py``). So the handler receives a dict, and what it
declares about that dict is the only thing standing between the typed event
class and the read model.

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

WHAT IS A HANDLER: THE PAYLOAD'S REACH, NOT A LIST OF PREFIXES.

The first version of this gate named three prefixes - ``on_``, ``_apply_``,
``_accumulate_`` - and review found the hole immediately: ``_on_`` was not
among them, and ``TriggerQueryProjection`` routes five live event types to
``_on_trigger_registered`` and friends off a ``model_dump()`` payload. The gate
saw none of them. Adding ``_on_`` would have closed that one spelling and left
the defect: the population was being decided by what handlers are *called*,
so any other valid convention evades it silently, and nothing at the point of
use tells a reader which conventions are the magic ones.

So the population is derived from the dispatch mechanisms themselves, and a
function is a handler when the event reaches it:

1. ``handle_event`` - the ``Projection`` protocol method the subscription
   machinery calls. Every projection has one; it is where the envelope enters.
2. ``on_*`` - not a convention but the dispatch contract:
   ``AutoDispatchProjection._discover_handlers`` walks the MRO for exactly this
   prefix and calls what it finds (``checkpoint.py``).
3. A function named by a **string literal** in a module that reaches for an
   attribute by variable name - ``getattr(self, handler_name)``. That is an
   explicit dispatch table, whatever shape it is written in: a dict, a match
   statement, a chain of ifs.
4. Anything a handler hands a piece of its own payload to. This is the transitive
   step, and it is what ``_apply_*`` and ``_accumulate_*`` used to approximate:
   the untyped payload crosses into them unchanged, so they are the same
   boundary one call deeper. ``_on_trigger_fired``, reached only by a direct
   call, arrives here too.

(1)-(3) are seeds; (4) closes over them. The result is wider than the prefix
list - ``handle_event``, ``_dispatch_event``, and the ``_on_*`` five all join -
and it drops ``_apply_post_filters``, a query-side filter the prefix caught by
accident and no event ever reaches.

WHAT IS AN ACCEPTABLE PARAMETER: STATED POSITIVELY.

The first version listed the spellings it rejected, and review found that hole
too. The list said ``dict`` and ``dict[str, Any]``; it did not say ``object``,
``dict[str, str]``, an absent annotation, or a ``TypedDict`` - so the very fix
the failure message forbids ("not a ``TypedDict``") made the gate green, and
three ``TypedDict`` handler payloads were already live in the codebase.

A list of rejected spellings can only ever be as complete as the last person to
extend it. So the accepted boundary is named instead, and everything else
fails:

    A handler parameter must declare a payload that is READ BY ATTRIBUTE and
    DECLARES ITS FIELDS - a ``@dataclass`` or a Pydantic ``BaseModel``, which
    is what the failure message has always said, or a ``NamedTuple`` or an
    ``Enum``.

The three ways to fail that are categorical rather than enumerated:

- ``UNDECLARED`` - no annotation at all, or one naming ``Any``/``object``.
- ``STRING_KEYED`` - a mapping, at any nesting, whatever its key and value
  types. There is no value-type list left to be incomplete, which is the whole
  point: ``dict[str, str]`` and ``dict[str, JsonValue]`` are read by string key
  exactly as ``dict[str, Any]`` is.
- ``DECLARES_NO_FIELDS`` - a type declared in THIS module that is none of the
  four accepted kinds. A ``TypedDict`` lands here, class-based or functional,
  and that is the branch that makes the failure message true.

The one place the rule is not closed is an imported type: the gate parses one
module at a time and cannot open ``from elsewhere import Row`` to see what kind
of thing ``Row`` is, so it is accepted on trust. Closing that needs whole-repo
type resolution, which is a much larger machine than this gate should be; the
local branch already covers where the evasion actually lives, because a payload
type invented to satisfy this gate is invented next to the handler.

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
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import pytest
from ci.fitness.conftest import load_exceptions, production_files, rel_path, repo_root

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from check_untyped_dicts import (
    MAPPING_NAMES,
    NAMESPACE_NAME,
    TYPED_DICT_NAME,
    UNCONSTRAINED_VALUES,
    ModuleShapes,
    module_shapes,
)

_EXCEPTION_SECTION = "typed_projection_handlers"

#: The ``Projection`` protocol method the subscription machinery calls. Not a
#: naming convention - it is the one method every projection must define for
#: an event to reach it at all, so it is where the envelope enters the module.
_PROTOCOL_ENTRY_POINT = "handle_event"

#: ``AutoDispatchProjection._discover_handlers`` walks the MRO for attributes
#: starting with exactly this, derives the event type from the rest of the name
#: and calls what it finds. A handler named this way IS the dispatch table.
_AUTO_DISPATCH_PREFIX = "on_"

#: Declarations that name their fields and are read by attribute. ``TypedDict``
#: is deliberately absent: it names its fields and is still read by string key,
#: so it reproduces half the defect under a name that looks typed (AGENTS.md;
#: PR #1246, #1248). ``SimpleNamespace`` is absent for the mirror reason - read
#: by attribute, declares nothing.
_FIELD_DECLARING_BASES = frozenset({"BaseModel", "NamedTuple", "Enum", "StrEnum", "IntEnum"})
_FIELD_DECLARING_DECORATOR = "dataclass"

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


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


class Verdict(Enum):
    """Why a handler parameter does not declare an attribute-readable payload.

    An enum rather than a bool because the three failures need different
    remediations, and because naming them is what stops the rule drifting back
    into a list of spellings: a new evasion has to be argued into one of these
    categories or it is already covered by one.
    """

    UNDECLARED = "declares nothing"
    STRING_KEYED = "is read by string key"
    DECLARES_NO_FIELDS = "declares no fields"


class Violation(NamedTuple):
    """One handler parameter that does not declare a typed payload."""

    qualname: str
    parameter: str
    line: int
    annotation: str
    verdict: Verdict

    def key(self, file_path: str) -> str:
        """The ``fitness_exceptions.toml`` key grandfathering this site."""
        return f"{file_path}:{self.qualname}.param:{self.parameter}"


def _qualnames(tree: ast.Module) -> dict[_FunctionNode, str]:
    """Every function in ``tree``, mapped to its dotted name."""
    found: dict[_FunctionNode, str] = {}

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, (*scope, child.name))
            elif isinstance(child, _FunctionNode):
                found[child] = ".".join((*scope, child.name))
                walk(child, (*scope, child.name))
            else:
                walk(child, scope)

    walk(tree, ())
    return found


def _payload_parameters(node: _FunctionNode) -> list[ast.arg]:
    """Every parameter of ``node`` that could carry state, ``self`` aside.

    ``*args``/``**kwargs`` are included: a handler that accepts ``**event:
    Any`` has the same erased boundary as one that names the parameter.
    """
    args = node.args
    declared = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    return [arg for arg in declared if arg is not None and arg.arg not in ("self", "cls")]


def _names_dispatched_by_string(tree: ast.Module) -> frozenset[str]:
    """Names this module reaches for dynamically, if it reaches for any.

    ``getattr(self, handler_name)`` is a dispatch table whose entries are
    string literals somewhere in the module, and the table's shape - a dict, a
    match statement, a chain of ifs - is not something a gate should have to
    enumerate. So when a module resolves an attribute from a *variable*, every
    string literal in it is a candidate handler name; the caller intersects
    them with the functions that actually exist.

    Gated on the ``getattr`` because without it the rule reads every string in
    every projection, and a namespace constant that happens to share a name
    with a method (``"session_list"``) would enrol it.
    """
    reaches_dynamically = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) > 1
        and not isinstance(node.args[1], ast.Constant)
        for node in ast.walk(tree)
    )
    if not reaches_dynamically:
        return frozenset()
    return frozenset(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _binding(statement: ast.AST) -> tuple[ast.expr, list[ast.expr]] | None:
    """The value a statement binds, and the targets it binds it to.

    Assignment is not the only way a name comes to hold part of a payload.
    Each of these binds a fresh name to something carved out of the expression
    beside it, and a handler that hands that name to a helper has handed the
    payload on exactly as ``item = event_data[...]`` would::

        for item in event_data:                 # ast.For / ast.AsyncFor
        [... for item in event_data]            # ast.comprehension
        with self._open(event_data) as item:    # ast.withitem
        if (item := event_data.get("x")):       # ast.NamedExpr

    Reading only assignment drops the helper reached through any of them out
    of the measured population entirely - not failing it, never looking at it -
    which is the one failure mode a gate cannot have: it goes green over code
    it never read. Naming every binding form in one place is what stops the
    next form being a fifth silent hole.

    ``ast.comprehension`` and ``ast.withitem`` are reached directly by
    ``ast.walk``, since both are child nodes of the statements that hold them.
    """
    if isinstance(statement, ast.Assign):
        return statement.value, list(statement.targets)
    if isinstance(statement, ast.AnnAssign | ast.NamedExpr):
        return None if statement.value is None else (statement.value, [statement.target])
    if isinstance(statement, ast.For | ast.AsyncFor | ast.comprehension):
        return statement.iter, [statement.target]
    if isinstance(statement, ast.withitem):
        target = statement.optional_vars
        return None if target is None else (statement.context_expr, [target])
    return None


def _derived_from_parameters(node: _FunctionNode) -> frozenset[str]:
    """Local names holding something derived from ``node``'s own parameters.

    A payload does not stay in the variable it arrived in. ``event_data =
    envelope.event.model_dump()`` and ``data = event_data.get("data", {})`` are
    both the event, one transformation on, and a handler that passes either to
    a helper has passed the payload on. So taint spreads across every binding
    form ``_binding`` names, and is not narrowed by what the right-hand side
    does to the value: a gate cannot tell ``model_dump()`` from
    ``.get("started_at")`` without types, and guessing would drop exactly the
    sub-payload hops that matter.

    Over-approximating costs nothing here. A helper that receives a scalar
    carved out of the payload joins the population and then declares a scalar,
    which is not a violation. Under-approximating loses handlers silently.
    """
    tainted = {arg.arg for arg in _payload_parameters(node)}
    changed = True
    while changed:
        changed = False
        for statement in ast.walk(node):
            binding = _binding(statement)
            if binding is None:
                continue
            value, targets = binding
            if not any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(value)):
                continue
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and name.id not in tainted:
                        tainted.add(name.id)
                        changed = True
    return frozenset(tainted)


def _called_name(call: ast.Call) -> str | None:
    """The bare name a call invokes - ``self._apply_x(...)`` answers ``_apply_x``."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def dispatched_handlers(tree: ast.Module) -> dict[_FunctionNode, str]:
    """Every function in ``tree`` the event payload reaches, by qualname.

    The four mechanisms are in the module docstring. Functions are matched by
    bare name because that is all a call site or a dispatch table writes; a
    name defined twice in a module enrols both definitions, which is the safe
    direction.
    """
    qualnames = _qualnames(tree)
    by_name: dict[str, list[_FunctionNode]] = {}
    for node in qualnames:
        by_name.setdefault(node.name, []).append(node)

    dispatched_by_string = _names_dispatched_by_string(tree)
    reached: dict[_FunctionNode, str] = {
        node: qualname
        for node, qualname in qualnames.items()
        if node.name.startswith(_AUTO_DISPATCH_PREFIX)
        or node.name == _PROTOCOL_ENTRY_POINT
        or node.name in dispatched_by_string
    }

    frontier = list(reached)
    while frontier:
        handler = frontier.pop()
        carries_payload = _derived_from_parameters(handler)
        for call in ast.walk(handler):
            if not isinstance(call, ast.Call):
                continue
            callees = by_name.get(_called_name(call) or "", [])
            arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
            forwards = any(
                isinstance(name, ast.Name) and name.id in carries_payload
                for argument in arguments
                for name in ast.walk(argument)
            )
            if not forwards:
                continue
            for callee in callees:
                if callee not in reached:
                    reached[callee] = qualnames[callee]
                    frontier.append(callee)
    return reached


def _types_declaring_no_fields(tree: ast.Module, shapes: ModuleShapes) -> frozenset[str]:
    """Types declared in ``tree`` that are not read by attribute with fields.

    Both ``TypedDict`` spellings land here - ``class X(TypedDict)`` and
    ``X = TypedDict("X", ...)`` - alongside any other locally declared type
    that is none of the four accepted kinds. Only local declarations: see the
    module docstring on the imported case.
    """
    declaring_no_fields: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            declares = any(
                shapes.names_any_of(base, _FIELD_DECLARING_BASES) for base in node.bases
            ) or any(
                shapes.names_any_of(
                    decorator.func if isinstance(decorator, ast.Call) else decorator,
                    {_FIELD_DECLARING_DECORATOR},
                )
                for decorator in node.decorator_list
            )
            if not declares:
                declaring_no_fields.add(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            if not shapes.names_any_of(value.func, {TYPED_DICT_NAME, NAMESPACE_NAME}):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            declaring_no_fields.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
    return frozenset(declaring_no_fields)


def verdict_for(
    annotation: ast.expr | None, shapes: ModuleShapes, declaring_no_fields: frozenset[str]
) -> Verdict | None:
    """Why ``annotation`` is not an attribute-readable payload, or ``None``.

    ``None`` is the accepted boundary: an annotation is present, names no
    mapping and no erasure, and - where this module can see the declaration -
    names something that declares its fields.
    """
    if annotation is None:
        return Verdict.UNDECLARED
    if shapes.names_any_of(annotation, MAPPING_NAMES):
        return Verdict.STRING_KEYED
    if shapes.names_any_of(annotation, UNCONSTRAINED_VALUES):
        return Verdict.UNDECLARED
    if shapes.names_any_of(annotation, {TYPED_DICT_NAME}):
        return Verdict.STRING_KEYED
    if shapes.names_any_of(annotation, declaring_no_fields | {NAMESPACE_NAME}):
        return Verdict.DECLARES_NO_FIELDS
    return None


def find_untyped_handler_parameters(source: str) -> list[Violation]:
    """Handler parameters in ``source`` that do not declare a typed payload.

    Raises ``SyntaxError`` if ``source`` does not parse, and callers must not
    swallow it: a module that cannot be measured has an unknown number of
    violations, not zero of them.
    """
    tree = ast.parse(source)
    shapes = module_shapes(tree)
    declaring_no_fields = _types_declaring_no_fields(tree, shapes)
    violations: list[Violation] = []
    for node, qualname in dispatched_handlers(tree).items():
        for arg in _payload_parameters(node):
            verdict = verdict_for(arg.annotation, shapes, declaring_no_fields)
            if verdict is None:
                continue
            violations.append(
                Violation(
                    qualname=qualname,
                    parameter=arg.arg,
                    line=arg.lineno,
                    annotation=ast.unparse(arg.annotation) if arg.annotation else "<none>",
                    verdict=verdict,
                )
            )
    return violations


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
        f"`{violation.parameter}: {violation.annotation}`, which "
        f"{violation.verdict.value}. The event class this handler is dispatched for "
        f"already types every field; take a payload that declares its own - a "
        f"@dataclass or a Pydantic BaseModel - rather than re-deriving it by "
        f"string key (#1268)."
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


# ---------------------------------------------------------------------------
# What the gate itself does, pinned.
#
# The scan above reports on the codebase; these report on the scanner. Both
# findings that sent PR #1281 back were the scanner being narrower than its own
# docstring while the scan was green, so a green scan is not evidence about any
# of this. Every case below is a shape the gate was measured to MISS before
# this change.
# ---------------------------------------------------------------------------


def _verdicts(source: str) -> dict[str, Verdict]:
    """``{"Class.handler.param": verdict}`` for one module's source."""
    return {
        f"{violation.qualname}.{violation.parameter}": violation.verdict
        for violation in find_untyped_handler_parameters(source)
    }


def _handler_names(source: str) -> set[str]:
    """The qualnames the gate considers handlers in one module's source."""
    return set(dispatched_handlers(ast.parse(source)).values())


_DISPATCH_TABLE_PROJECTION = '''
from typing import Any, ClassVar


class TriggerQueryProjection:
    """The shape TriggerQueryProjection dispatches with, reduced."""

    _EVENT_DISPATCH: ClassVar[dict[str, str]] = {
        "github.TriggerRegistered": "_on_trigger_registered",
    }

    async def _dispatch_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        if event_type == "github.TriggerFired":
            await self._on_trigger_fired(event_data)
            return
        handler_name = self._EVENT_DISPATCH.get(event_type)
        if handler_name is not None:
            handler = getattr(self, handler_name)
            await handler(event_data)

    async def handle_event(self, envelope: Envelope) -> None:
        event_data = envelope.event.model_dump()
        await self._dispatch_event(envelope.metadata.event_type, event_data)

    async def _on_trigger_registered(self, data: dict[str, Any]) -> None:
        self.store[data["trigger_id"]] = data

    async def _on_trigger_fired(self, data: dict[str, Any]) -> None:
        self.store[data["trigger_id"]] = data
'''


@pytest.mark.architecture
def test_handler_named_only_by_a_dispatch_table_is_a_handler() -> None:
    """`_on_trigger_registered` is reached by string, not by prefix.

    The whole of finding 1: `_HANDLER_PREFIXES` listed `on_` and not `_on_`, so
    five live handlers of `TriggerQueryProjection` were invisible while the
    gate reported green. A prefix list cannot see this one at all - the name is
    written once, as a value in `_EVENT_DISPATCH`, and reached with `getattr`.
    """
    assert (
        _verdicts(_DISPATCH_TABLE_PROJECTION)["TriggerQueryProjection._on_trigger_registered.data"]
        is Verdict.STRING_KEYED
    )


@pytest.mark.architecture
def test_handler_reached_only_by_a_direct_call_is_a_handler() -> None:
    """`_on_trigger_fired` is in no table; the dispatcher calls it by name.

    So it is reached by neither of the two mechanisms a reader would name
    first, and it takes the same `model_dump()` payload as its four siblings.
    It arrives through the payload's reach: `handle_event` forwards the
    envelope to `_dispatch_event`, which forwards the payload on.
    """
    assert (
        _verdicts(_DISPATCH_TABLE_PROJECTION)["TriggerQueryProjection._on_trigger_fired.data"]
        is Verdict.STRING_KEYED
    )


@pytest.mark.architecture
def test_the_dispatcher_between_them_is_a_handler_too() -> None:
    """`_dispatch_event` holds the payload in a `dict[str, Any]` on the way.

    Named because it is the hop the prefix list could never have reached under
    any prefix, and it is the one the payload spends longest in.
    """
    assert (
        _verdicts(_DISPATCH_TABLE_PROJECTION)["TriggerQueryProjection._dispatch_event.event_data"]
        is Verdict.STRING_KEYED
    )


@pytest.mark.architecture
def test_a_typed_dict_payload_fails() -> None:
    """The fix the failure message forbids must not be the fix that works.

    Finding 2, and it was not hypothetical: three `TypedDict` handler payloads
    were already live in the codebase and the gate scored all three as clean.
    """
    source = """
from typing import TypedDict


class _SkillRegisteredEventData(TypedDict, total=False):
    skill_id: str


class SkillProjection:
    async def on_skill_registered(self, event_data: _SkillRegisteredEventData) -> None:
        self.rows[event_data["skill_id"]] = event_data
"""
    assert _verdicts(source)["SkillProjection.on_skill_registered.event_data"] is (
        Verdict.DECLARES_NO_FIELDS
    )


@pytest.mark.architecture
def test_a_functional_typed_dict_payload_fails_too() -> None:
    """`X = TypedDict("X", ...)` is the same declaration in one line.

    Closing the class spelling alone would leave the number standing still for
    a rename, which is the #1188 defect one level up (AGENTS.md).
    """
    source = """
from typing import TypedDict

_EventData = TypedDict("_EventData", {"skill_id": str})


class SkillProjection:
    async def on_skill_registered(self, event_data: _EventData) -> None:
        self.rows[event_data["skill_id"]] = event_data
"""
    assert _verdicts(source)["SkillProjection.on_skill_registered.event_data"] is (
        Verdict.DECLARES_NO_FIELDS
    )


@pytest.mark.architecture
def test_an_unannotated_payload_fails() -> None:
    """Declaring nothing must not beat declaring something useless.

    The first version skipped a parameter with no annotation entirely, so
    deleting `: dict[str, Any]` was a one-character way to leave the gate.
    """
    source = """
class SessionProjection:
    async def on_session_started(self, event_data) -> None:
        self.rows[event_data["session_id"]] = event_data
"""
    assert _verdicts(source)["SessionProjection.on_session_started.event_data"] is (
        Verdict.UNDECLARED
    )


@pytest.mark.architecture
def test_an_object_payload_fails() -> None:
    """`object` erases exactly as much as `Any` and was not on the list."""
    source = """
class SessionProjection:
    async def on_session_started(self, event_data: object) -> None:
        self.rows["x"] = event_data
"""
    assert _verdicts(source)["SessionProjection.on_session_started.event_data"] is (
        Verdict.UNDECLARED
    )


@pytest.mark.architecture
def test_a_str_valued_mapping_payload_fails() -> None:
    """`dict[str, str]` is read by string key, which is the objection.

    The first version asked only whether the VALUE type was erased, so every
    mapping with a named value type passed - `dict[str, str]`,
    `dict[str, JsonValue]`, `dict[str, int]`. There is no value-type list here
    to be incomplete.
    """
    source = """
class SessionProjection:
    async def on_session_started(self, event_data: dict[str, str]) -> None:
        self.rows[event_data["session_id"]] = event_data
"""
    assert _verdicts(source)["SessionProjection.on_session_started.event_data"] is (
        Verdict.STRING_KEYED
    )


@pytest.mark.architecture
def test_a_quoted_mapping_payload_fails() -> None:
    """A forward reference is still a type, and the gate reads it as one."""
    source = """
class SessionProjection:
    async def on_session_started(self, event_data: "dict[str, str]") -> None:
        self.rows[event_data["session_id"]] = event_data
"""
    assert _verdicts(source)["SessionProjection.on_session_started.event_data"] is (
        Verdict.STRING_KEYED
    )


@pytest.mark.architecture
def test_a_dataclass_payload_is_accepted() -> None:
    """The remediation the message asks for has to be the one that works.

    Without this the gate could reject everything and every case above would
    still pass, which is the shape of an assertion that proves nothing.
    """
    source = """
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionStarted:
    session_id: str


class SessionProjection:
    async def on_session_started(self, event_data: SessionStarted) -> None:
        self.rows[event_data.session_id] = event_data
"""
    assert _verdicts(source) == {}


@pytest.mark.architecture
def test_a_pydantic_payload_is_accepted() -> None:
    """The other half of what the failure message names."""
    source = """
from pydantic import BaseModel


class SessionStarted(BaseModel):
    session_id: str


class SessionProjection:
    async def on_session_started(self, event_data: SessionStarted) -> None:
        self.rows[event_data.session_id] = event_data
"""
    assert _verdicts(source) == {}


@pytest.mark.architecture
def test_a_payload_handed_on_is_still_measured() -> None:
    """A helper the payload reaches is the same boundary one call deeper.

    This is what `_apply_`/`_accumulate_` approximated by name. Here the
    helper's name says nothing; it is a handler because the payload arrives.
    """
    source = """
from typing import Any


class SessionProjection:
    async def on_session_completed(self, event_data: dict[str, Any]) -> None:
        payload = event_data.get("data", {})
        self._merge(self.rows, payload)

    def _merge(self, existing: dict[str, Any], payload: dict[str, Any]) -> None:
        existing.update(payload)
"""
    verdicts = _verdicts(source)
    assert verdicts["SessionProjection._merge.payload"] is Verdict.STRING_KEYED
    assert verdicts["SessionProjection._merge.existing"] is Verdict.STRING_KEYED


@pytest.mark.architecture
def test_a_function_no_event_reaches_is_not_a_handler() -> None:
    """The population is the payload's reach, not the module's contents.

    `_apply_post_filters` is a real one: a query-side filter the prefix list
    enrolled for its name, which no event has ever reached. A gate that
    enrolled every function in a projection module would report on the read
    path and call it dispatch.
    """
    source = """
from typing import Any


class SessionProjection:
    async def on_session_started(self, event_data: dict[str, Any]) -> None:
        self.rows["x"] = event_data

    def _apply_post_filters(self, rows: dict[str, Any]) -> None:
        rows.pop("hidden", None)
"""
    assert _handler_names(source) == {"SessionProjection.on_session_started"}


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("label", "carve"),
    [
        ("for target", "for item in event_data:\n            self._store(item)"),
        ("async for target", "async for item in event_data:\n            self._store(item)"),
        (
            "comprehension target",
            "_ = [self._store(item) for item in event_data]",
        ),
        (
            "generator target",
            "_ = tuple(self._store(item) for item in event_data)",
        ),
        (
            "dict comprehension target",
            "_ = {k: self._store(item) for k, item in event_data.items()}",
        ),
        ("with target", "with self._open(event_data) as item:\n            self._store(item)"),
        ("walrus target", "if (item := event_data.get('x')):\n            self._store(item)"),
    ],
)
def test_a_payload_carved_out_by_any_binding_form_still_reaches_its_helper(
    label: str, carve: str
) -> None:
    """The population is every helper the payload reaches, however it got there.

    The taint walk read only `ast.Assign`/`ast.AnnAssign`, so a payload carved
    out by any of these seven forms handed `_store` nothing the gate could
    follow. `_store` did not FAIL the gate - it dropped out of the measured
    population entirely and was never read, which is the one failure mode a
    gate cannot have: green over code it never looked at.

    Two live helpers in `syn-domain` were exactly this, found when the walk was
    widened (see `fitness_exceptions.toml`, 171 -> 173).
    """
    source = f"""
from typing import Any


class SessionProjection:
    async def on_session_started(self, event_data: dict[str, Any]) -> None:
        {carve}

    def _store(self, item: dict[str, Any]) -> None:
        self.rows.update(item)
"""
    assert _verdicts(source)["SessionProjection._store.item"] is Verdict.STRING_KEYED, (
        f"a payload reached `_store` through a {label} and the gate never read it"
    )


@pytest.mark.architecture
def test_a_binding_form_that_never_touched_the_payload_reaches_nothing() -> None:
    """Widening the walk must not enrol every local name in the module.

    `for row in _DEFAULT_ROWS` binds a name the payload never reached, so the
    helper it calls is read-path code and not a handler. A walk that tainted
    every binding target rather than only those whose source mentions the
    payload would pass the seven cases above for the wrong reason, and report
    on the query side - the over-approximation the prefix list made.

    Deliberately NOT a case where the payload was assigned to `self` first:
    `self.seen = event_data[...]` taints `self` itself and has since before
    this walk was widened, and the module docstring accepts over-approximation
    by design. Pinning that here would pin a property the gate does not claim.
    """
    source = """
from typing import Any

_DEFAULT_ROWS: list[Any] = []


class SessionProjection:
    async def on_session_started(self, event_data: dict[str, Any]) -> None:
        for row in _DEFAULT_ROWS:
            self._render(row)

    def _render(self, row: dict[str, Any]) -> None:
        row.pop("hidden", None)
"""
    assert _handler_names(source) == {"SessionProjection.on_session_started"}
