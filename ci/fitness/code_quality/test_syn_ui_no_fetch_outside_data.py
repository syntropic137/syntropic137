"""Fitness function: only the data package talks HTTP (ADR-074 rule 1).

ADR-074 rule 1: routes and components never call ``fetch``, never build URLs,
never parse responses. They call a named resource in
``packages/syn-ui/data/src/resources`` through the binding.

Guarded here: no ``fetch(`` call and no ``/api/v1`` string in

* ``apps/syn-ui/src/**`` (the Vite proxy config lives outside ``src``),
* ``packages/syn-ui/skyline-svelte-v5/src/**``,
* ``packages/syn-ui/skyline-core/src/**``.

Zero tolerance, no exceptions. Comments do not count; strings do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from ci.fitness.code_quality._syn_ui import ROOT, line_of, rel, source_files, strip_comments

SCANNED_ROOTS = (
    ROOT / "apps" / "syn-ui" / "src",
    ROOT / "packages" / "syn-ui" / "skyline-svelte-v5" / "src",
    ROOT / "packages" / "syn-ui" / "skyline-core" / "src",
)

#: `fetch(` as a call: `prefetch(` and `refetch(` are other words.
FETCH_CALL = re.compile(r"(?<![\w$])fetch\s*\(")
API_PATH = re.compile(r"/api/v1\b")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


def violations_in(text: str, path: str) -> list[Violation]:
    code = strip_comments(text)
    found = [
        Violation(path, line_of(code, m.start()), "calls fetch(") for m in FETCH_CALL.finditer(code)
    ]
    found += [
        Violation(path, line_of(code, m.start()), "names /api/v1") for m in API_PATH.finditer(code)
    ]
    return found


@pytest.mark.architecture
def test_ui_layers_never_fetch_or_name_the_api() -> None:
    files = [f for root in SCANNED_ROOTS for f in source_files(root)]
    assert len(files) > 50, f"scanned only {len(files)} files; the roots moved?"
    found = [v for f in files for v in violations_in(f.read_text(encoding="utf-8"), rel(f))]
    assert not found, (
        "ADR-074 rule 1: UI code calls a resource from @syn137/syn-ui-data through the binding "
        "(apps/syn-ui/src/lib/load.svelte.ts), never fetch() or an /api/v1 URL:\n"
        + "\n".join(v.render() for v in found)
    )


PLANTED = {
    "bare fetch": "const r = await fetch('/x')",
    "window fetch": "window.fetch (url)",
    "api path": "const url = `/api/v1/executions/${id}`",
}
CLEAN = {
    "comment": "// never fetch( here, and no /api/v1 either",
    "block comment": "/* fetch(x) */ const a = 1",
    "html comment": "<!-- fetch(x) -->",
    "other words": "prefetch(route); refetch()",
}


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(PLANTED))
def test_planted_violation_is_caught(name: str) -> None:
    assert violations_in(PLANTED[name], "planted.ts"), name


@pytest.mark.architecture
@pytest.mark.parametrize("name", sorted(CLEAN))
def test_clean_text_passes(name: str) -> None:
    assert not violations_in(CLEAN[name], "clean.ts"), name
