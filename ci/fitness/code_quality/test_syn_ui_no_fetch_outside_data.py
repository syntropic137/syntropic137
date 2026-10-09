"""Fitness function: only the data package talks HTTP (ADR-074 rule 1).

ADR-074 rule 1: routes and components never call ``fetch``, never build URLs,
never parse responses. They call a named resource in
``packages/syn-ui/data/src/resources`` through the binding.

Guarded here, over

* ``apps/syn-ui/src/**`` (the Vite proxy config lives outside ``src``),
* ``packages/syn-ui/skyline-svelte-v5/src/**``,
* ``packages/syn-ui/skyline-core/src/**``:

1. no ``fetch`` at all: not called, not referenced (``const f = fetch``,
   ``globalThis.fetch``), not named in a string (``globalThis["fetch"]``);
2. no ``/api/`` in a string, including a string built by ``+`` from literals
   (``"/api/" + "v1"``) or a template's static text;
3. outside the binding (``apps/syn-ui/src/lib``), no transport: no import of
   the data package's request layer (``request``, ``fetchJSON``,
   ``Coalescer``, URL builders, ``configureClient``, the cache), no namespace
   import of the package (``import * as data``, which reaches all of them),
   and no ``request(`` / ``fetchJSON(`` call however it got its name.

Sources are tokenized (``_syn_ui.tokens``), so strings cannot hide code from
the comment stripper and comments do not count. Zero tolerance, no exceptions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from ci.fitness.code_quality._syn_ui import (
    ROOT,
    SYN_UI_APP,
    code_only,
    is_svelte,
    line_of,
    module_refs,
    rel,
    source_files,
    tokens,
)

SCANNED_ROOTS = (
    ROOT / "apps" / "syn-ui" / "src",
    ROOT / "packages" / "syn-ui" / "skyline-svelte-v5" / "src",
    ROOT / "packages" / "syn-ui" / "skyline-core" / "src",
)
BINDING = SYN_UI_APP / "src" / "lib"
PACKAGE = "@syn137/syn-ui-data"

#: The data package's request layer: only resources (inside the package) and the binding use it.
TRANSPORT = frozenset(
    {
        "request",
        "fetchJSON",
        "Coalescer",
        "toSearchParams",
        "withQuery",
        "seg",
        "listQueryParams",
        "configureClient",
        "clientConfig",
        "API_BASE",
        "queryCache",
        "QueryCache",
        "cached",
    }
)

#: `fetch` as a word: `prefetch` and `refetch` are other words.
FETCH = re.compile(r"(?<![\w$])fetch(?![\w$])")
TRANSPORT_CALL = re.compile(r"(?<![\w$])(request|fetchJSON)\s*(?:<[^()]*?>)?\s*\(")
API_PATH = re.compile(r"/api(?:/|$)")
_CONCAT = re.compile(r"\s*\+\s*")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


@dataclass
class _Chain:
    start: int
    end: int
    value: str


def _string_chains(text: str, *, svelte: bool) -> list[_Chain]:
    """Each string literal, or run of literals joined by `+`, with its static text."""
    chains: list[_Chain] = []
    for t in tokens(text, svelte=svelte):
        if t.kind not in ("str", "tmpl"):
            continue
        if chains and _CONCAT.fullmatch(text, chains[-1].end, t.start):
            chains[-1].end, chains[-1].value = t.end, chains[-1].value + t.value
        else:
            chains.append(_Chain(t.start, t.end, t.value))
    return chains


def violations_in(text: str, path: str, *, transport_allowed: bool = False) -> list[Violation]:
    svelte = is_svelte(path)
    code = code_only(text, svelte=svelte)
    found = [Violation(path, line_of(code, m.start()), "uses fetch") for m in FETCH.finditer(code)]
    for chain in _string_chains(text, svelte=svelte):
        if chain.value == "fetch":
            found.append(Violation(path, line_of(text, chain.start), "names fetch in a string"))
        if API_PATH.search(chain.value):
            found.append(Violation(path, line_of(text, chain.start), "names an /api/ URL"))
    if transport_allowed:
        return found
    found += [
        Violation(path, line_of(code, m.start()), f"calls {m.group(1)}() (use a named resource)")
        for m in TRANSPORT_CALL.finditer(code)
    ]
    for ref in module_refs(text, svelte=svelte):
        if not (ref.spec or "").startswith(PACKAGE):
            continue
        if ref.namespace:
            found.append(Violation(path, ref.line, f"namespace-imports {ref.spec}"))
        found += [
            Violation(path, ref.line, f"imports transport {n} from {ref.spec}")
            for n in ref.names
            if n in TRANSPORT
        ]
    return found


def _file_violations() -> list[Violation]:
    files = [f for root in SCANNED_ROOTS for f in source_files(root)]
    assert len(files) > 50, f"scanned only {len(files)} files; the roots moved?"
    return [
        v
        for f in files
        for v in violations_in(
            f.read_text(encoding="utf-8"), rel(f), transport_allowed=f.is_relative_to(BINDING)
        )
    ]


@pytest.mark.architecture
def test_ui_layers_never_fetch_or_name_the_api() -> None:
    found = _file_violations()
    assert not found, (
        "ADR-074 rule 1: UI code calls a named resource from @syn137/syn-ui-data through the "
        "binding (apps/syn-ui/src/lib/load.svelte.ts), never fetch(), the request layer or an "
        "/api/ URL:\n" + "\n".join(v.render() for v in found)
    )


PLANTED = {
    "bare fetch": "const r = await fetch('/x')",
    "window fetch": "window.fetch (url)",
    "fetch alias": "const f = fetch; f('/x')",
    "computed member fetch": 'globalThis["fetch"]("/x")',
    "computed member template": "self[`fetch`]('/x')",
    "api path": "const url = `/api/v1/executions/${id}`",
    "api path concatenated": 'const u = "/api/" + "v1/executions"',
    "api path concat multiline": "const u = '/ap' +\n  'i/v1'",
    "api base alone": "const base = '/api'",
    "request from data": "import { request } from '@syn137/syn-ui-data'\nrequest('/executions')",
    "request renamed": "import { request as r } from '@syn137/syn-ui-data'",
    "namespace import": "import * as data from '@syn137/syn-ui-data'\ndata.listExecutions()",
    "request via dynamic import": "const { request } = await import('@syn137/syn-ui-data')\nrequest('/x')",
    "fetchJSON": "fetchJSON('/x')",
    "string hides code from block comment": (
        '<script>const s=" /* "; fetch("/x"); const e=" */ ";</script>'
    ),
    "string hides code from line comment": "<script>const s = ' // '; fetch('/x')</script>",
    "markup expression": "<button onclick={() => fetch('/x')}>go</button>",
}
CLEAN = {
    "comment": "// never fetch( here, and no /api/v1 either",
    "block comment": "/* fetch(x) */ const a = 1",
    "html comment": "<!-- fetch(x) -->",
    "other words": "prefetch(route); refetch()",
    "resource import": "import { listExecutions, type ExecutionSummary } from '@syn137/syn-ui-data'",
    "url in string is not a comment": "const u = 'https://example.com/a'; const b = 1",
    "regex with quote": 'const re = /"/g; const ok = 1',
}


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(PLANTED))
def test_planted_violation_is_caught(name: str) -> None:
    path = "planted.svelte" if "<" in PLANTED[name] else "planted.ts"
    assert violations_in(PLANTED[name], path), name


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(CLEAN))
def test_clean_text_passes(name: str) -> None:
    path = "clean.svelte" if "<!--" in CLEAN[name] else "clean.ts"
    assert not violations_in(CLEAN[name], path), name


@pytest.mark.architecture
def test_binding_may_use_transport_but_never_fetch() -> None:
    allowed = "import { configureClient, queryCache } from '@syn137/syn-ui-data'"
    assert not violations_in(allowed, "lib.ts", transport_allowed=True)
    assert violations_in("globalThis['fetch']('/x')", "lib.ts", transport_allowed=True)
