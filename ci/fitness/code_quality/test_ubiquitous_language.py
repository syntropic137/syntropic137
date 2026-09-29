"""Every bounded context owns a ubiquitous language file.

Standard DDD practice, and inherited from the event-sourcing platform this
system is built on: a bounded context is DEFINED by the language spoken inside
it, so that language is an artifact and not folklore.

The absence had already cost a domain word. One operation was called both
`resume` and `resume` until 2026-09-27, when the meanings were separated and
`resume` had to be reclaimed for the capability it should have named.

Naming standard: `<bounded-context>-ubiquitous-language.md`, context name first,
so a search returns files whose names say which context they speak for instead
of five identically-named ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_CONTEXTS = Path("packages/syn-domain/src/syn_domain/contexts")
_DOCS = Path("docs/architecture")

#: Not a bounded context: shared value objects with no domain of their own.
_NOT_A_CONTEXT = {"_shared"}


def _bounded_contexts() -> list[str]:
    return sorted(
        d.name
        for d in _CONTEXTS.iterdir()
        if d.is_dir() and not d.name.startswith("__") and d.name not in _NOT_A_CONTEXT
    )


def test_there_are_contexts_to_check() -> None:
    """A discovery bug that finds nothing would make every test below vacuous."""
    found = _bounded_contexts()
    assert len(found) >= 5, found


@pytest.mark.parametrize("context", _bounded_contexts())
def test_every_context_has_a_vocabulary(context: str) -> None:
    doc = _DOCS / f"{context}-ubiquitous-language.md"
    assert doc.is_file(), (
        f"bounded context {context!r} has no ubiquitous language file. "
        f"Expected {doc}. See AGENTS.md, 'Ubiquitous Language'."
    )


@pytest.mark.parametrize("context", _bounded_contexts())
def test_every_vocabulary_names_its_context(context: str) -> None:
    """A file that does not say which context it speaks for invites drift."""
    doc = _DOCS / f"{context}-ubiquitous-language.md"
    if not doc.is_file():
        pytest.skip("covered by test_every_context_has_a_vocabulary")
    head = doc.read_text()[:400]
    assert context in head, f"{doc} must name {context!r} near the top"


def test_no_vocabulary_is_orphaned() -> None:
    """A vocabulary for a context that no longer exists is stale documentation."""
    contexts = set(_bounded_contexts())
    orphans = [
        f.name
        for f in _DOCS.glob("*-ubiquitous-language.md")
        if f.name.removesuffix("-ubiquitous-language.md") not in contexts
    ]
    assert not orphans, f"vocabularies with no bounded context: {orphans}"


def test_agents_md_explains_the_convention() -> None:
    """A convention nobody is told about is not a convention.

    AGENTS.md is the primary context every agent and contributor reads, so the
    vocabularies are worthless if nothing points at them from there.
    """
    agents = Path("AGENTS.md").read_text()
    assert "Ubiquitous Language" in agents, "AGENTS.md must explain the convention"
    assert "-ubiquitous-language.md" in agents, "AGENTS.md must state the naming standard"
