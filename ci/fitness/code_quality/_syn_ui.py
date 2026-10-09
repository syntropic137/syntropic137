"""Shared model for the syn-ui data-layer fitness functions (ADR-074).

The sources are parsed, not scanned: ``packages/syn-ui/scripts/boundary-facts.mjs``
runs the TypeScript compiler API over every ``.ts``/``.js``/``.mjs`` file and
``svelte/compiler`` over every ``.svelte`` file (its ``<script>`` blocks and
markup expressions are then parsed with TypeScript too), and writes one JSON
file of facts: imports, re-exports, exports, top-level declarations, calls with
their callee chain and folded string arguments, references to imported
bindings and to ``fetch``, and every folded string expression. A file that does
not parse carries ``parse_error`` and every check reports it.

This module loads those facts and resolves names the way the module system
does: an imported binding is followed through aliases (``import { a as b }``)
and re-export chains (``export { x as y } from``, ``export *``,
``import { x }; export { x }``) to the declaration that defines it, so a check
asks "is this the data package's ``request``?", never "is this spelled
``request``?".

Checks run over a *base*: ``""`` for the repository, or a planted tree under
``ci/fitness/code_quality/fixtures/syn_ui/<tree>/`` laid out like the repo.
"""

from __future__ import annotations

import posixpath
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[3]
SYN_UI_APP = ROOT / "apps" / "syn-ui"
FACTS_SCRIPT = ROOT / "packages" / "syn-ui" / "scripts" / "boundary-facts.mjs"
PLANTED = "ci/fitness/code_quality/fixtures/syn_ui"
#: Directories the facts cover (repo-relative): the Skyline UI and the planted trees.
SCANNED = ("apps/syn-ui", "packages/syn-ui", PLANTED)

PACKAGE = "@syn137/syn-ui-data"
DATA = "packages/syn-ui/data/"
CLIENT_INDEX = "packages/syn-ui/data/src/client/index.ts"


class _Fact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Folded(_Fact):
    """A folded expression: ``literal`` text, a ``pattern`` (``\\x00`` per substitution), or ``dynamic`` source."""

    kind: Literal["literal", "pattern", "dynamic"]
    value: str


class Import(_Fact):
    spec: str | None
    resolved: str | None
    line: int
    #: The local binding; None for a side-effect import or an ``import('x')`` type.
    local: str | None
    #: ``default``, ``*`` (namespace), a name, or None (side-effect import).
    imported: str | None
    type_only: bool


class DynamicImport(_Fact):
    #: None when the argument does not fold to a literal: it cannot be checked.
    spec: str | None
    resolved: str | None
    line: int
    require: bool


class ReExport(_Fact):
    spec: str
    resolved: str | None
    line: int
    #: The name in the source module, or ``*``.
    local: str
    #: The name exported here; None for ``export * from``.
    exported: str | None
    type_only: bool


class Export(_Fact):
    #: The local binding exported; None for ``export default <expression>``.
    local: str | None
    exported: str
    kind: str
    type_only: bool
    line: int


class Decl(_Fact):
    """One top-level declaration and the top-level names (declarations, imports) it references."""

    names: tuple[str, ...]
    kind: str
    line: int
    refs: tuple[str, ...]
    #: ``const x = y`` / ``const x = ns.y``: the chain x is another name for.
    alias: tuple[str, ...] | None


class Call(_Fact):
    callee: tuple[str, ...] | None
    line: int
    #: The top-level declaration the call sits in, if any.
    decl: str | None
    #: The first three arguments, folded.
    args: tuple[Folded, ...]
    #: ``method`` in an object-literal second argument, when it is a literal.
    method: str | None
    method_known: bool


class Ref(_Fact):
    name: str
    line: int


class StringFact(_Fact):
    value: str
    line: int


class FileFacts(_Fact):
    path: str
    kind: Literal["ts", "svelte"]
    parse_error: str | None
    imports: tuple[Import, ...]
    dynamic_imports: tuple[DynamicImport, ...]
    reexports: tuple[ReExport, ...]
    exports: tuple[Export, ...]
    decls: tuple[Decl, ...]
    calls: tuple[Call, ...]
    refs: tuple[Ref, ...]
    member_fetch: tuple[int, ...]
    strings: tuple[StringFact, ...]


class Facts(_Fact):
    root: str
    files: tuple[FileFacts, ...]


def generate_facts(out: Path) -> Facts:
    """Run boundary-facts.mjs (with the workspace's own typescript and svelte) and load its output."""
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError(
            "pnpm is not on PATH: the syn-ui boundary checks need it to parse sources"
        )
    done = subprocess.run(
        [pnpm, "exec", "node", str(FACTS_SCRIPT), "--root", str(ROOT), "--out", str(out), *SCANNED],
        cwd=SYN_UI_APP,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"boundary-facts.mjs failed ({done.returncode}):\n{done.stderr}")
    return Facts.model_validate_json(out.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Symbol:
    """What a name resolves to: ``name`` declared in ``module`` (a repo path, or a bare spec when external)."""

    module: str
    name: str


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


def is_test_file(path: str) -> bool:
    return path.endswith((".test.ts", ".spec.ts", ".test.js", ".spec.js"))


def parse_violation(f: FileFacts) -> list[Violation]:
    """A file the parsers reject is a violation: it cannot be checked, so it never passes."""
    return [Violation(f.path, 1, f"does not parse: {f.parse_error}")] if f.parse_error else []


class Graph:
    """The module graph of the parsed files, with name resolution through aliases and re-exports."""

    def __init__(self, facts: Facts) -> None:
        self.files: dict[str, FileFacts] = {f.path: f for f in facts.files}
        self._exports_cache: dict[str, frozenset[Symbol]] = {}

    def under(self, base: str, prefix: str) -> list[FileFacts]:
        """Files under ``base + prefix``."""
        start = base + prefix
        return [f for path, f in sorted(self.files.items()) if path.startswith(start)]

    # -- resolution ---------------------------------------------------------

    def _from(
        self, spec: str | None, resolved: str | None, name: str, seen: frozenset[str]
    ) -> Symbol | None:
        if resolved is not None:
            return self.resolve_export(resolved, name, seen)
        return Symbol(spec or "<unresolvable>", name)

    def resolve_export(
        self, module: str, name: str, seen: frozenset[str] = frozenset()
    ) -> Symbol | None:
        """The declaration ``module`` exports as ``name``, followed through every re-export; None if absent."""
        key = f"{module}\x00{name}"
        if key in seen:
            return None
        seen = seen | {key}
        f = self.files.get(module)
        if f is None:
            return Symbol(module, name)
        for e in f.exports:
            if e.exported == name:
                return (
                    self.resolve_local(module, e.local, seen)
                    if e.local
                    else Symbol(module, "default")
                )
        for r in f.reexports:
            if r.exported == name:
                if r.local == "*":
                    return Symbol(r.resolved or r.spec, "*")
                return self._from(r.spec, r.resolved, r.local, seen)
        if name != "default":
            for r in f.reexports:
                if r.exported is None and r.resolved is not None:
                    hit = self.resolve_export(r.resolved, name, seen)
                    if hit is not None:
                        return hit
        return None

    def resolve_local(
        self, module: str, local: str, seen: frozenset[str] = frozenset()
    ) -> Symbol | None:
        """What a top-level name in ``module`` is: an import followed to its declaration, or a local one."""
        f = self.files.get(module)
        if f is not None:
            for i in f.imports:
                if i.local == local and i.imported is not None:
                    if i.imported == "*":
                        return Symbol(i.resolved or i.spec or "<unresolvable>", "*")
                    return self._from(i.spec, i.resolved, i.imported, seen)
            for d in f.decls:
                if local in d.names and d.alias and f"{module}\x00={local}" not in seen:
                    return self._alias(module, d.alias, seen | {f"{module}\x00={local}"}) or Symbol(
                        module, local
                    )
        return Symbol(module, local)

    def _alias(self, module: str, chain: tuple[str, ...], seen: frozenset[str]) -> Symbol | None:
        """``const x = y`` or ``const x = ns.y``, followed; None when the chain goes anywhere else."""
        head = self.resolve_local(module, chain[0], seen)
        if head is None or len(chain) == 1:
            return head
        if head.name == "*" and len(chain) == 2 and head.module in self.files:
            return self.resolve_export(head.module, chain[1], seen)
        return None

    def resolve_callee(self, f: FileFacts, callee: tuple[str, ...] | None) -> Symbol | None:
        """``x(...)`` or ``ns.x(...)`` (``ns`` a namespace import) resolved to its declaration."""
        if not callee:
            return None
        head = self.resolve_local(f.path, callee[0])
        if head is None:
            return None
        if head.name == "*" and len(callee) == 2:
            return (
                self.resolve_export(head.module, callee[1]) if head.module in self.files else None
            )
        if len(callee) == 1:
            if head == Symbol(f.path, callee[0]) and not any(callee[0] in d.names for d in f.decls):
                return Symbol("<global>", callee[0])
            return head
        return None

    def exported_symbols(
        self, module: str, seen: frozenset[str] = frozenset()
    ) -> frozenset[Symbol]:
        """Every declaration ``module`` exports (namespaces expanded), resolved."""
        if module in self._exports_cache:
            return self._exports_cache[module]
        if module in seen:
            return frozenset()
        seen = seen | {module}
        f = self.files.get(module)
        if f is None:
            return frozenset()
        out: set[Symbol] = set()
        names = {e.exported for e in f.exports} | {r.exported for r in f.reexports if r.exported}
        for name in names:
            sym = self.resolve_export(module, name)
            if sym is None:
                continue
            out.add(sym)
            if sym.name == "*":
                out |= self.exported_symbols(sym.module, seen)
        for r in f.reexports:
            if r.exported is None and r.resolved is not None:
                out |= self.exported_symbols(r.resolved, seen)
        result = frozenset(out)
        self._exports_cache[module] = result
        return result

    def value_export_names(self, module: str) -> set[str]:
        f = self.files[module]
        return {e.exported for e in f.exports if not e.type_only} | {
            r.exported for r in f.reexports if r.exported and not r.type_only
        }


def is_data(module: str, base: str) -> bool:
    """Is ``module`` inside the data package (the repo's, or a planted tree's own)?"""
    return module.startswith(DATA) or (bool(base) and module.startswith(base + DATA))


def client_index(graph: Graph, base: str) -> str:
    """The data package's ``client/index.ts`` for ``base`` (a planted tree may bring its own)."""
    own = base + CLIENT_INDEX
    return own if own in graph.files else CLIENT_INDEX


#: Exports of client/index.ts that are not transport: error types and plain helpers screens use.
NOT_TRANSPORT = frozenset({"ApiError", "isAbortError", "abortError", "MAX_PAGE_SIZE", "mapLimit"})


def transport(graph: Graph, base: str) -> frozenset[Symbol]:
    """The request layer: every value client/index.ts exports except NOT_TRANSPORT, plus ``cached``.

    Enumerated from the index, so a new export is transport until someone
    decides otherwise (fail closed).
    """
    index = client_index(graph, base)
    out = {
        sym
        for name in graph.value_export_names(index) - NOT_TRANSPORT
        if (sym := graph.resolve_export(index, name)) is not None
    }
    keys = index.replace("client/index.ts", "keys.ts")
    if keys in graph.files and (cached := graph.resolve_export(keys, "cached")) is not None:
        out.add(cached)
    return frozenset(out)


def relative_target(path: str, spec: str) -> str:
    """Where a relative specifier points (repo-relative), whether or not the file exists."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(path), spec.split("?", 1)[0]))


def tree_base(tree: str) -> str:
    """The base of one planted tree: ``ci/fitness/code_quality/fixtures/syn_ui/<tree>/``."""
    return f"{PLANTED}/{tree}/"


def planted_cases(tree: str) -> list[str]:
    """Planted files of ``tree`` that assert something (PROBE or CLEAN), repo-relative."""
    root = ROOT / tree_base(tree)
    files = sorted(
        p.relative_to(ROOT).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix in (".ts", ".svelte")
    )
    return [p for p in files if expectation(p) != "helper"]


def expectation(path: str) -> Literal["probe", "clean", "helper"]:
    """A planted file says what it is on its first line: PROBE (must be reported), CLEAN or HELPER."""
    first = (ROOT / path).read_text(encoding="utf-8").lstrip().splitlines()[0]
    if "PROBE" in first:
        return "probe"
    if "CLEAN" in first:
        return "clean"
    if "HELPER" in first:
        return "helper"
    raise AssertionError(f"{path}: first line must say PROBE, CLEAN or HELPER")
