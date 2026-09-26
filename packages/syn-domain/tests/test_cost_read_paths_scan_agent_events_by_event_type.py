"""Every ``agent_events`` scan that filters on ``event_type``, and what bounds it.

``event_type`` is in neither the hypertable's ``compress_segmentby``
(``session_id``) nor its ``compress_orderby`` (``time``), so inside a compressed
chunk it cannot be answered from any index - the segment is decompressed and
filtered row by row. #1338 shipped the two composite indexes that serve the
UNCOMPRESSED chunks (see ``002_agent_events.sql``); they change nothing for
compressed data. So what decides whether a scan is survivable is not the index,
it is whether the predicate pins ``session_id`` - the segmentby column - to
values the planner has in hand:

  * pinned (``session_id = $1``, ``session_id = ANY($1)``): a compressed chunk
    discards the segments of every other session without decompressing them.
    NARROWER, not bounded - nothing here limits the events WITHIN a session that
    IS selected, and the number of sessions per round-trip is bounded only where
    a caller caps it (``MAX_SESSIONS_PER_QUERY``).
  * not pinned (``execution_id``, or ``event_type`` alone, or a join): nothing
    narrows the chunk, so every segment in range is decompressed. Only a read
    model removes this.

THE GATE FINDS ITS OWN SUBJECTS. It parses production source, resolves the SQL
(including f-strings composed from constants in other modules), and reports
every statement that reads ``agent_events`` with ``event_type`` in a
row-selecting predicate. Each one must be declared in ``_DECLARED`` below, by
IDENTITY - the file it lives in plus the symbol that holds it.

That is the whole point, and it is what the first version of this file got
wrong (#1345 review): it named two queries by hand and drove them through a
recording fake. A new module scanning ``agent_events`` by ``event_type`` was
invisible to it, and ``repo_cost/timescale_query.py`` - modified in that very
PR - was already missing. It also compared a ``set``, so a second statement of
the same shape was absorbed by the first. Identities are compared with their
multiplicity here: two statements are two entries even when the SQL is
identical, because two statements are two scans.

WHAT THE READER SHOULD KNOW ABOUT THE PARSING. It is a SQL-aware text pass, not
a SQL parser - no parser is a dependency of this repository. Four consequences
are worth stating, because each one decides whether a real query is seen:

  * ``event_type`` inside ``COUNT(*) FILTER (WHERE ...)``, a ``CASE``, or a
    select list is NOT a row-selecting predicate and does not make a scan a
    subject. Only ``WHERE``/``ON`` at the statement's own paren depth counts.
  * SQL assembled by ``str.format`` at call time is not resolved; the
    ``{placeholder}`` is opaque text. A predicate that arrives that way is read
    as absent, which under-reports what restricts the scan - the safe
    direction for a gate, the wrong direction for a reader.
  * A constant holding a statement, and the constant that composes it into a
    larger statement, are two identities and both must be declared. That counts
    one round-trip twice - deliberately, because the alternative is guessing
    which of two symbols a reviewer meant.
  * A declaration is prose plus a claim the parser can check
    (``restricted_by``). The prose is not checked by anything; it is the part a
    human has to mean.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

pytestmark = pytest.mark.unit

# The repo root is three parents up from packages/syn-domain/tests/<file>.
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Production source. Tests are deliberately excluded: a fixture query in a test
#: is not a read path, and a gate that policed them would be arguing with its
#: own fixtures.
_SEARCH_ROOTS = (
    _REPO_ROOT / "packages" / "syn-domain" / "src",
    _REPO_ROOT / "packages" / "syn-adapters" / "src",
    _REPO_ROOT / "packages" / "syn-shared" / "src",
    _REPO_ROOT / "packages" / "syn-collector" / "src",
    _REPO_ROOT / "apps" / "syn-api" / "src",
)

_TABLE = "agent_events"
#: The id columns whose presence in a predicate decides what the storage layer
#: can skip. ``session_id`` is compress_segmentby; ``execution_id`` is neither
#: segmentby nor orderby, so it narrows nothing once a chunk is compressed.
_SEGMENT_KEY = "session_id"
_ID_COLUMNS = (_SEGMENT_KEY, "execution_id")

_TABLE_REF = re.compile(rf"\b(?:from|join)\s+{_TABLE}\b", re.I)
_PREDICATE_START = re.compile(r"\b(?<!distinct )(where|on)\b", re.I)
#: What ends a predicate. ``where`` and ``join`` are here so that a JOIN-ON
#: clause stops where the next clause starts instead of swallowing it: every
#: clause is then reported once, in its own words.
_PREDICATE_END = re.compile(
    r"\b(where|join|group\s+by|order\s+by|limit|offset"
    r"|having|window|union|intersect|except|returning)\b",
    re.I,
)
_SUBSELECT = re.compile(r"\(\s*(?:select|with)\b", re.I)
_EVENT_TYPE = re.compile(r"\bevent_type\b", re.I)
#: ``col = $1``, ``col = ANY($1::text[])`` - an id pinned to a bound parameter.
#: A join (``w.session_id = a.session_id``) does not pin anything: the set of
#: sessions is whatever the other side yields, which is not a value the planner
#: can use to discard segments.
_PINNED = r"\b(?:\w+\.)?{col}\s*(?:=|<>|!=)\s*(?:any\s*\(\s*)?\$\d+"
#: What an unresolvable f-string placeholder renders as. Bare, so it reads as
#: one opaque SQL token wherever it lands - including inside quotes.
_OPAQUE = "_unresolved_"


@dataclass(frozen=True, order=True)
class ScanIdentity:
    """Where a scan lives: the file, and the symbol that holds its SQL.

    The symbol is a module-level constant name where there is one, and the
    qualified name of the function that issues the query where the SQL is
    written inline. Two statements under one symbol are one identity with a
    count of two - see ``DiscoveredScan.statements``.
    """

    module: str
    symbol: str

    def __str__(self) -> str:
        return f"{self.module}::{self.symbol}"


@dataclass(frozen=True)
class DiscoveredScan:
    """One statement reading ``agent_events`` with ``event_type`` in its predicate."""

    identity: ScanIdentity
    #: Id columns the predicate pins to bound parameters, sorted.
    restricted_by: tuple[str, ...]
    #: The row-selecting predicate, whitespace-normalised, for failure messages.
    predicate: str

    @property
    def discards_segments(self) -> bool:
        """Whether the storage layer can skip other sessions' segments."""
        return _SEGMENT_KEY in self.restricted_by


class Bound(Enum):
    """What limits the rows a scan has to look at. Neither value means "cheap"."""

    #: The predicate pins session_id, so segments of other sessions are skipped.
    #: Says nothing about the events within the sessions it does select.
    SEGMENT_DISCARD = "discards other sessions' segments"
    #: Nothing pins session_id, so every segment of every chunk in range is
    #: decompressed. Outstanding debt: an index cannot close it.
    FULL_SEGMENT_SCAN = "decompresses every segment in range"


@dataclass(frozen=True)
class Declaration:
    """The reviewed claim about one scan identity.

    ``bound`` and ``restricted_by`` are checked against the SQL. ``why`` is the
    part a person has to mean: what makes this acceptable, or what it is
    waiting on.
    """

    bound: Bound
    restricted_by: tuple[str, ...]
    why: str
    #: How many event_type-filtered ``agent_events`` statements this symbol
    #: holds. Stated so that a second one cannot arrive unnoticed.
    statements: int = 1


# --- Reading the SQL out of the source --------------------------------------


@dataclass
class _Module:
    """One parsed production file and its module-level string constants."""

    path: Path
    dotted: str
    tree: ast.Module
    constants: dict[str, ast.expr] = field(default_factory=dict)
    #: Name -> the dotted module it was imported from, absolute.
    imported_from: dict[str, str] = field(default_factory=dict)


class _SourceTree:
    """Every production module, with names resolvable across files.

    SQL in this repository is composed: a query is an f-string over predicate
    and CTE fragments that live in other modules (``CANONICAL_USAGE_EVENT_FILTER``
    is one). A scanner that read only literal text would see the placeholder and
    not the predicate, which is a blind spot shaped exactly like the one this
    gate exists to close.
    """

    def __init__(self, roots: Sequence[Path]) -> None:
        self._by_path: dict[Path, _Module] = {}
        self._by_dotted: dict[str, Path] = {}
        for root in roots:
            for path in sorted(root.rglob("*.py")):
                module = _parse(path, dotted=_dotted_name(path, root))
                if module is None:
                    continue
                self._by_path[path] = module
                self._by_dotted[module.dotted] = path

    def modules(self) -> Iterator[_Module]:
        yield from self._by_path.values()

    def resolve(
        self, module: _Module, name: str, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> tuple[_Module, ast.expr] | None:
        """Where ``name`` is defined, following re-exports to the module that owns it.

        A fragment is usually imported from a package rather than from the file
        that writes it (``from syn_domain.contexts.agent_sessions import
        CANONICAL_USAGE_EVENT_FILTER``), so stopping at the first hop would find
        an ``__init__`` that only passes the name along.
        """
        if (module.dotted, name) in seen:
            return None
        local = module.constants.get(name)
        if local is not None:
            return module, local
        dotted = module.imported_from.get(name)
        if dotted is None:
            return None
        path = self._by_dotted.get(dotted)
        if path is None:
            return None
        return self.resolve(self._by_path[path], name, seen | {(module.dotted, name)})

    def render(
        self, module: _Module, node: ast.expr, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> str:
        """The SQL text of an expression, with what cannot be resolved made opaque."""
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, str) else _OPAQUE
        if isinstance(node, ast.JoinedStr):
            return "".join(self.render(module, part, seen) for part in node.values)
        if isinstance(node, ast.FormattedValue):
            return self.render(module, node.value, seen)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.render(module, node.left, seen) + self.render(module, node.right, seen)
        if isinstance(node, ast.Name):
            found = self.resolve(module, node.id, seen)
            if found is not None:
                owner, expression = found
                return self.render(owner, expression, seen | {(module.dotted, node.id)})
        return _OPAQUE


def _parse(path: Path, *, dotted: str) -> _Module | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    package = dotted if path.name == "__init__.py" else dotted.rpartition(".")[0]
    module = _Module(path=path, dotted=dotted, tree=tree)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                module.constants[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                module.constants[node.target.id] = node.value
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                module.imported_from[alias.asname or alias.name] = _absolute_module(node, package)
    return module


def _absolute_module(node: ast.ImportFrom, package: str) -> str:
    """The dotted module a from-import names, with relative levels applied.

    ``package`` is the module's own package - itself for an ``__init__``, its
    parent otherwise - which is what a relative import counts levels from.
    """
    if node.level == 0:
        return node.module or ""
    parts = package.split(".") if package else []
    base = parts[: len(parts) - node.level + 1]
    return ".".join([*base, *([node.module] if node.module else [])])


def _dotted_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _sql_expressions(tree: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    """(symbol, expression) for every string-valued expression in a module.

    A module-level constant is named by its own symbol; SQL written inline
    inside a function is named by that function, because that is the name a
    reader greps for and a local variable is not.

    Docstrings are excluded. Prose is not code, and this file's own subject is a
    table whose name appears in prose all over this repository - ``"counts from
    agent_events"`` is a sentence, not a scan.
    """
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }

    def walk(node: ast.AST, symbol: str, *, in_function: bool) -> Iterator[tuple[str, ast.expr]]:
        for child in ast.iter_child_nodes(node):
            name, nested = symbol, in_function
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name, nested = _join(symbol, child.name), True
            elif isinstance(child, ast.ClassDef):
                name = _join(symbol, child.name)
            elif not in_function and isinstance(child, ast.Assign) and len(child.targets) == 1:
                target = child.targets[0]
                if isinstance(target, ast.Name):
                    name = _join(symbol, target.id)
            elif (
                not in_function
                and isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
            ):
                name = _join(symbol, child.target.id)
            if id(child) in docstrings:
                continue
            if isinstance(child, ast.JoinedStr) or (
                isinstance(child, ast.Constant) and isinstance(child.value, str)
            ):
                # Yielded whole: the parts of an f-string are one SQL string,
                # and descending into them would cut a predicate in half.
                yield name, child
                continue
            yield from walk(child, name, in_function=nested)

    yield from walk(tree, "", in_function=False)


def _join(symbol: str, name: str) -> str:
    return f"{symbol}.{name}" if symbol else name


# --- Reading the predicate out of the SQL -----------------------------------


def _blank(text: str, start: int, end: int) -> str:
    """Erase a span, keeping every other character at the same offset."""
    return text[:start] + " " * (end - start) + text[end:]


def _strip_noise(sql: str) -> str:
    """Remove comments and string literals, which can hold anything."""
    stripped = sql
    for pattern in (
        re.compile(r"--[^\n]*"),
        re.compile(r"/\*.*?\*/", re.S),
        re.compile(r"'[^']*'"),
    ):
        while (match := pattern.search(stripped)) is not None:
            stripped = _blank(stripped, match.start(), match.end())
    return stripped


def _depths(text: str) -> list[int]:
    """The paren depth of every character; an opening paren sits at its own depth."""
    depth = 0
    out: list[int] = []
    for char in text:
        if char == "(":
            out.append(depth)
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
            out.append(depth)
        else:
            out.append(depth)
    return out


def _closing(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _statement_of(text: str, depths: Sequence[int], position: int) -> str:
    """The text of the SELECT that owns the table reference at ``position``.

    A CTE body, a subquery and a top-level statement are all just the span
    between the parens that enclose them, so one rule covers all three.
    """
    depth = depths[position]
    start = 0
    for index in range(position, -1, -1):
        if text[index] == "(" and depths[index] == depth - 1:
            start = index + 1
            break
    end = len(text)
    for index in range(position, len(text)):
        if text[index] == ")" and depths[index] == depth - 1:
            end = index
            break
    return text[start:end]


def _row_selecting_predicate(statement: str) -> str:
    """The WHERE and JOIN-ON text of a statement, and nothing else.

    Subqueries are erased first: their predicates belong to them, and each is
    found separately if it reads ``agent_events`` itself. What is left is read
    at the statement's own paren depth, which is what keeps ``FILTER (WHERE
    event_type = ...)`` and ``CASE WHEN event_type = ...`` out - they narrow an
    aggregate over rows already chosen, not the rows.
    """
    body = statement
    while (match := _SUBSELECT.search(body)) is not None:
        body = _blank(body, match.start(), min(_closing(body, match.start()) + 1, len(body)))
    depths = _depths(body)
    clauses: list[str] = []
    covered = 0
    for start in _PREDICATE_START.finditer(body):
        if depths[start.start()] != 0 or start.start() < covered:
            continue
        end = len(body)
        for terminator in _PREDICATE_END.finditer(body, start.end()):
            if depths[terminator.start()] == 0:
                end = terminator.start()
                break
        clauses.append(body[start.end() : end])
        covered = end
    return " ".join(" ".join(clause.split()) for clause in clauses)


def _restricted_by(predicate: str) -> tuple[str, ...]:
    return tuple(
        column
        for column in _ID_COLUMNS
        if re.search(_PINNED.format(col=column), predicate, re.I) is not None
    )


def discover_event_type_scans(roots: Sequence[Path], *, relative_to: Path) -> list[DiscoveredScan]:
    """Every ``agent_events`` statement under ``roots`` that filters on event_type.

    One entry per statement. Identical SQL under two symbols is two entries, and
    so is the same SQL twice under one symbol: the storage layer is charged per
    statement, so the gate counts per statement.
    """
    tree = _SourceTree(roots)
    found: list[DiscoveredScan] = []
    for module in tree.modules():
        if _TABLE not in module.path.read_text(encoding="utf-8"):
            continue
        relative = str(module.path.relative_to(relative_to))
        for symbol, node in _sql_expressions(module.tree):
            sql = _strip_noise(tree.render(module, node))
            if not _TABLE_REF.search(sql):
                continue
            depths = _depths(sql)
            for reference in _TABLE_REF.finditer(sql):
                predicate = _row_selecting_predicate(_statement_of(sql, depths, reference.start()))
                if not _EVENT_TYPE.search(predicate):
                    continue
                found.append(
                    DiscoveredScan(
                        identity=ScanIdentity(relative, symbol or "<module>"),
                        restricted_by=_restricted_by(predicate),
                        predicate=predicate,
                    )
                )
    return found


# --- The reviewed inventory -------------------------------------------------

_DOMAIN = "packages/syn-domain/src/syn_domain/contexts"
_ADAPTERS = "packages/syn-adapters/src/syn_adapters"
_API = "apps/syn-api/src/syn_api"

_SESSION_COST = f"{_DOMAIN}/agent_sessions/slices/session_cost"
_EXECUTION_COST = f"{_DOMAIN}/orchestration/slices/execution_cost"


def _declared(module: str, entries: Mapping[str, Declaration]) -> dict[ScanIdentity, Declaration]:
    """The declarations for one file, keyed by identity."""
    return {ScanIdentity(module, symbol): entry for symbol, entry in entries.items()}


def _segment_discard(why: str, *, statements: int = 1) -> Declaration:
    return Declaration(
        bound=Bound.SEGMENT_DISCARD,
        restricted_by=(_SEGMENT_KEY,),
        why=why,
        statements=statements,
    )


def _full_scan(why: str, *, by: tuple[str, ...] = (), statements: int = 1) -> Declaration:
    return Declaration(
        bound=Bound.FULL_SEGMENT_SCAN,
        restricted_by=by,
        why=why,
        statements=statements,
    )


_BY_EXECUTION = ("execution_id",)

#: Every identity the discovery above finds, and the reviewed claim about it.
#: Adding a row here is a review decision, not a formality: the bound is checked
#: against the SQL, the prose is not checked by anything.
_DECLARED: Mapping[ScanIdentity, Declaration] = {
    # The read path #1338 is about. Pins the segmentby column AND caps the ids
    # per round-trip; neither fact limits the events inside a session.
    **_declared(
        f"{_SESSION_COST}/timescale_query.py",
        {
            "_SESSION_SUMMARY_BATCH_QUERY": _segment_discard(
                "Authoritative per-session cost for one page of sessions: the latest "
                "session_summary per id. A compressed chunk discards every other session's "
                "segment, and calculate_many binds at most MAX_SESSIONS_PER_QUERY ids. "
                "Nothing bounds the events within a session that IS selected - that is what "
                "the read model in #1338 is for."
            ),
            "_TOKEN_USAGE_FALLBACK_BATCH_QUERY": _segment_discard(
                "The same page for sessions with no summary yet, summed per (session, model). "
                "Same pin, same cap, same unbounded interior."
            ),
            "_MIN_TIME_BATCH_QUERY": _segment_discard(
                "started_at for the same page. `time` is compress_orderby, so the MIN is "
                "cheap per segment - but it still visits every segment the pinned sessions "
                "own."
            ),
        },
    ),
    # Execution-keyed reads. execution_id is neither compress_segmentby nor
    # compress_orderby, so pinning it discards nothing: every segment of every
    # chunk in range is decompressed and filtered row by row. The composite
    # index from #1338 serves the uncompressed head only. All outstanding debt.
    **_declared(
        f"{_EXECUTION_COST}/timescale_query.py",
        {
            "_SESSION_SUMMARY_QUERY": _full_scan(
                "One execution's authoritative cost. Pinning execution_id skips no segment; "
                "the fix is a read model keyed by execution, not another index (#1338).",
                by=_BY_EXECUTION,
            ),
            "_TOKEN_USAGE_FALLBACK_QUERY": _full_scan(
                "The same execution's tokens when no summary exists yet. Same shape, same debt.",
                by=_BY_EXECUTION,
            ),
            "_TURN_COUNT_QUERY": _full_scan(
                "Turn count for one execution, same shape as the tool count.",
                by=_BY_EXECUTION,
            ),
            "_COST_BY_PHASE_QUERY": _full_scan(
                "Per-phase breakdown of one execution's cost, grouped so unpriced rows "
                "cannot hide in a priced group (#812). Unbounded in the same way.",
                by=_BY_EXECUTION,
            ),
        },
    ),
    **_declared(
        f"{_EXECUTION_COST}/query_service.py",
        {
            "_BY_IDS_FROM_SUMMARY_QUERY": _full_scan(
                "One page of executions by id (#1077), from session_summary. The page bounds "
                "the ids bound, not the rows read.",
                by=_BY_EXECUTION,
            ),
            "_BY_IDS_FROM_TOKEN_USAGE_QUERY": _full_scan(
                "The token_usage fallback for that same page of ids.",
                by=_BY_EXECUTION,
            ),
            "_COST_BY_PHASE_QUERY": _full_scan(
                "Phase breakdown for a page of ids.",
                by=_BY_EXECUTION,
            ),
            "_LIST_ALL_FROM_SUMMARY_QUERY": _full_scan(
                "The executions list. Two statements: a CTE that picks the LIMIT'd "
                "most-recent executions, then the select that reads agent_events again for "
                "their rows. The LIMIT counts executions; the scan under it is every "
                "session_summary event in range, with nothing pinned at all.",
                statements=2,
            ),
            "_LIST_ALL_FROM_TOKEN_USAGE_QUERY": _full_scan(
                "The same list for executions with no summary. No LIMIT anywhere: it groups "
                "every token_usage event ever recorded, on every page view."
            ),
        },
    ),
    **_declared(
        f"{_SESSION_COST}/query_service.py",
        {
            "_LIST_ALL_FROM_SUMMARY_QUERY": _full_scan(
                "The sessions list. LIMIT $2 caps the rows returned, not the rows read: the "
                "GROUP BY runs over every session_summary event first."
            ),
            "_LIST_ALL_FROM_TOKEN_USAGE_QUERY": _full_scan(
                "The same list for in-progress sessions, grouped per (session, model) so "
                "mixed pricing cannot merge (#788). No LIMIT at all - the widest read in "
                "this file."
            ),
            "_STARTED_AT_BY_SESSION_QUERY": _full_scan(
                "MIN(time) per session over the whole table. Unlimited."
            ),
        },
    ),
    **_declared(
        "packages/syn-domain/src/syn_domain/tool_call_counts.py",
        {
            "BACKFILL_SQL": _full_scan(
                "The deliberate full recount used to rebuild the maintained tally. It runs "
                "during repair or projection rebuild, never on an API read path."
            ),
            "_HISTORY_HAS_TOOL_CALLS_SQL": _full_scan(
                "Startup asks whether canonical history contains any tool call before "
                "accepting an empty tally. EXISTS may stop early, but has no storage bound."
            ),
        },
    ),
    **_declared(
        f"{_DOMAIN}/agent_sessions/slices/canonical_totals/query_service.py",
        {
            "_SCOPED_EVENTS": _full_scan(
                "The CTE behind the dashboard's all-time totals card. All-time by intent, so "
                "no session pin is possible; narrowed by #1253 to the two event types that "
                "carry tokens, which is what stopped it materialising the whole table's JSONB "
                "into a work table. Its execution filter arrives through str.format, so this "
                "gate reads the predicate without it."
            ),
            "_TOTALS_QUERY": _full_scan(
                "The statement _SCOPED_EVENTS is composed into. The same text under a second "
                "symbol, and therefore a second identity: the gate compares identities, so a "
                "constant and the query built from it are both declared. One round-trip, not "
                "two."
            ),
        },
    ),
    **_declared(
        f"{_DOMAIN}/organization/slices/contribution_heatmap/TimescaleHeatmapQuery.py",
        {
            "_USAGE_QUERY": _full_scan(
                "The contribution heatmap's usage read. session_id appears only as a join "
                "key (w.session_id = a.session_id), which pins nothing the planner can use, "
                "so this is discovered and declared like any other unpinned scan. This file "
                "is #1253's subject and its cost is being addressed there; #1338 makes no "
                "claim about it either way."
            ),
        },
    ),
    **_declared(
        f"{_DOMAIN}/organization/slices/repo_cost/timescale_query.py",
        {
            "_EXECUTION_COSTS_QUERY": _full_scan(
                "Per-repo cost: session_summary rows for the repo's executions. The id list "
                "is as long as the repo's history, and execution_id discards no segments.",
                by=_BY_EXECUTION,
            ),
            "_EXECUTION_COSTS_FALLBACK_QUERY": _full_scan(
                "The token_usage fallback for the same id list.",
                by=_BY_EXECUTION,
            ),
        },
    ),
    # SQL written inline inside a function is identified by the function that
    # issues it: there is no constant to name, and the function is what a reader
    # would go and read.
    **_declared(
        f"{_ADAPTERS}/events/queries.py",
        {
            "query_session_events": _segment_discard(
                "The session event feed, LIMIT/OFFSET paged. Pins the segmentby column and "
                "orders by the orderby column, which is the cheapest shape this table has. "
                "The page bounds what is returned; the session bounds which segments are "
                "read; the events within the session are still unbounded."
            ),
            "query_execution_events": _full_scan(
                "The execution event feed. LIMIT'd, but execution_id discards no segments, so "
                "the page is cheap only in what it hands back.",
                by=_BY_EXECUTION,
            ),
            "query_recent": _full_scan(
                "The live feed's recent-events-of-one-type read: event_type, ORDER BY time "
                "DESC, LIMIT. The newest chunk is normally still uncompressed, which is why "
                "this is usually fast - not why it is bounded. It is not."
            ),
            "query_recent_by_types": _full_scan(
                "The same feed for a set of types, and the same reasoning."
            ),
        },
    ),
    **_declared(
        f"{_ADAPTERS}/projections/session_tools_helpers.py",
        {
            "get_session_tools": _segment_discard(
                "The session timeline. Two statements: a CTE collecting tool names for the "
                "session, then the timeline select that joins it. Both pin session_id. The "
                "second filters with `event_type != ALL($4)` - a negation, so it reads nearly "
                "every type in the segments it does open.",
                statements=2,
            ),
        },
    ),
}


# --- The gate ----------------------------------------------------------------


def gate_findings(
    scans: Sequence[DiscoveredScan], declarations: Mapping[ScanIdentity, Declaration]
) -> list[str]:
    """Everything wrong with the relationship between what was found and what was declared.

    A finding is a sentence a reader can act on. Four kinds: discovered and not
    declared, declared and no longer discovered, a different number of
    statements than declared, and a declared bound the SQL does not support.
    """
    findings: list[str] = []
    by_identity: dict[ScanIdentity, list[DiscoveredScan]] = {}
    for scan in scans:
        by_identity.setdefault(scan.identity, []).append(scan)

    for identity in sorted(by_identity):
        found = by_identity[identity]
        declaration = declarations.get(identity)
        if declaration is None:
            findings.append(
                f"{identity} reads {_TABLE} filtered on event_type "
                f"({len(found)} statement(s)) and is not declared. Predicate: "
                f"{found[0].predicate!r}. Add it to _DECLARED with the bound you have "
                f"checked, or give this read path a read model."
            )
            continue
        if declaration.statements != len(found):
            findings.append(
                f"{identity} declares {declaration.statements} statement(s) but "
                f"{len(found)} were found. If a statement was added, say so and say what "
                f"bounds it; if one was removed, lower the number."
            )
        pinned = {scan.restricted_by for scan in found}
        if pinned != {declaration.restricted_by}:
            findings.append(
                f"{identity} declares restricted_by={declaration.restricted_by} but the SQL "
                f"pins {sorted(pinned)}. Predicates: {[scan.predicate for scan in found]}"
            )
        actual = {
            Bound.SEGMENT_DISCARD if scan.discards_segments else Bound.FULL_SEGMENT_SCAN
            for scan in found
        }
        if actual != {declaration.bound}:
            findings.append(
                f"{identity} declares {declaration.bound.name} but its predicate implies "
                f"{sorted(bound.name for bound in actual)}: {_SEGMENT_KEY} is "
                f"{'not ' if declaration.bound is Bound.SEGMENT_DISCARD else ''}pinned."
            )

    for identity in sorted(set(declarations) - set(by_identity)):
        findings.append(
            f"{identity} is declared but no longer reads {_TABLE} by event_type. Delete the "
            f"declaration - a stale inventory is how the last one stopped being true."
        )
    return findings


def _production_scans() -> list[DiscoveredScan]:
    return discover_event_type_scans(_SEARCH_ROOTS, relative_to=_REPO_ROOT)


# --- What the gate asserts about production ----------------------------------


def test_every_event_type_scan_of_agent_events_is_declared_with_a_checked_bound() -> None:
    """No read path scans this table by event_type without a reviewed declaration.

    This is the whole gate. It fails when a query appears, when one disappears,
    when a symbol grows a second statement, and when a declaration claims a bound
    the predicate does not support - none of which require anyone to remember
    that this file exists.
    """
    findings = gate_findings(_production_scans(), _DECLARED)
    assert not findings, "\n" + "\n".join(findings)


def test_the_number_of_unpinned_statements_is_the_number_we_have_accepted() -> None:
    """The outstanding debt, as a number, so that adding to it is a decision.

    Counted per statement as written in source, which is why a constant and the
    query composed from it count twice: the gate compares identities, and there
    are two identities. The number may go DOWN when a read path gets a read
    model. It may not go up without changing this line, and changing this line is
    the conversation.
    """
    unpinned = [scan for scan in _production_scans() if not scan.discards_segments]
    assert len(unpinned) == 23, "\n" + "\n".join(
        f"{scan.identity}: {scan.predicate}" for scan in unpinned
    )


def test_the_session_cost_read_path_still_pins_the_segmentby_column() -> None:
    """The specific claim #1338's change rests on, named where a reader will look.

    Three batch statements, all pinning session_id. If one loses the pin it
    becomes a full segment scan and the test above catches that too - this one
    says which file to open.
    """
    module = f"{_SESSION_COST}/timescale_query.py"
    scans = [scan for scan in _production_scans() if scan.identity.module == module]
    assert len(scans) == 3
    assert all(scan.discards_segments for scan in scans), [
        (str(scan.identity), scan.predicate) for scan in scans
    ]


# --- What the gate asserts about itself --------------------------------------
#
# The gate's own claim is that it finds its subjects. These two fixtures are how
# that claim is falsifiable: a query nobody declared, and two queries a set would
# have merged.


def _fixture(tmp_path: Path, name: str, sql_by_symbol: Mapping[str, str]) -> None:
    body = "\n".join(f'{symbol} = """\n{sql}\n"""\n' for symbol, sql in sql_by_symbol.items())
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")


_NEW_SCAN = "SELECT session_id, COUNT(*)\nFROM agent_events\nWHERE event_type = $1\nGROUP BY 1"


def test_a_new_event_type_query_fails_the_gate_with_no_edit_to_any_inventory(
    tmp_path: Path,
) -> None:
    """The defect the review found: a new read path was invisible to the old list.

    Nothing about this fixture is registered anywhere. Discovery has to notice it
    by parsing, and the gate has to refuse it for not being declared.
    """
    _fixture(tmp_path, "brand_new_read_path", {"_TOTALS_BY_SESSION": _NEW_SCAN})
    assert all("brand_new_read_path" not in identity.module for identity in _DECLARED)

    scans = discover_event_type_scans([tmp_path], relative_to=tmp_path)
    assert [str(scan.identity) for scan in scans] == ["brand_new_read_path.py::_TOTALS_BY_SESSION"]

    findings = gate_findings(scans, _DECLARED)
    refusals = [
        finding
        for finding in findings
        if "brand_new_read_path.py::_TOTALS_BY_SESSION" in finding and "not declared" in finding
    ]
    assert len(refusals) == 1, "\n" + "\n".join(findings)


def test_two_identical_statements_under_different_symbols_are_reported_separately(
    tmp_path: Path,
) -> None:
    """Two scans are two scans, even when the SQL is character-for-character equal.

    The old gate compared a ``set`` of shapes, so the second of these vanished
    into the first and its file never had to be looked at. Identity is (file,
    symbol) and the comparison keeps multiplicity, so both are reported and both
    have to be declared.
    """
    _fixture(tmp_path, "twins", {"_FIRST_QUERY": _NEW_SCAN, "_SECOND_QUERY": _NEW_SCAN})

    scans = discover_event_type_scans([tmp_path], relative_to=tmp_path)
    assert sorted(str(scan.identity) for scan in scans) == [
        "twins.py::_FIRST_QUERY",
        "twins.py::_SECOND_QUERY",
    ]

    findings = gate_findings(scans, {})
    assert sum("twins.py::_FIRST_QUERY" in finding for finding in findings) == 1
    assert sum("twins.py::_SECOND_QUERY" in finding for finding in findings) == 1


def test_a_second_statement_under_one_symbol_raises_that_symbol_s_count(
    tmp_path: Path,
) -> None:
    """The same shape twice under ONE symbol is two statements, not one.

    This is the production shape of ``_LIST_ALL_FROM_SUMMARY_QUERY``: a CTE that
    reads the table, and an outer select that reads it again. A declaration that
    says one is refused.
    """
    both = (
        "WITH recent AS (\n"
        "    SELECT session_id FROM agent_events WHERE event_type = $1 LIMIT 10\n"
        ")\n"
        "SELECT r.session_id\n"
        "FROM agent_events a\n"
        "JOIN recent r ON r.session_id = a.session_id\n"
        "WHERE a.event_type = $1"
    )
    _fixture(tmp_path, "twice_over", {"_PAGED_QUERY": both})

    scans = discover_event_type_scans([tmp_path], relative_to=tmp_path)
    identity = ScanIdentity("twice_over.py", "_PAGED_QUERY")
    assert [scan.identity for scan in scans] == [identity, identity]

    understated = {identity: _full_scan("Understated on purpose.", statements=1)}
    findings = gate_findings(scans, understated)
    assert [finding for finding in findings if "declares 1 statement(s) but 2" in finding], (
        "\n" + "\n".join(findings)
    )
    assert not gate_findings(scans, {identity: _full_scan("Correct.", statements=2)})
