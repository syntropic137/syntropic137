"""Fitness: every port is paired with the thing that implements it (#1305).

``syn_adapters.port_conformance`` is where a port meets its implementation
under an annotation, which is the only place pyright performs the structural
match. A port missing from it is a port nothing checks -- and a Protocol
nothing checks is documentation that can lie: ``WorkflowExecutionRepositoryPort``
disagreed with ``RepositoryAdapter`` over a parameter name through a green
pyright run, because no site anywhere named the port.

pyright enforces that each pairing HOLDS. This enforces that the list is
COMPLETE, which pyright cannot: a port simply left out produces no error.

A port with no implementation in this repository goes in ``_UNIMPLEMENTED``
with its reason. That table is the ratchet -- adding a port is free, adding
one that nothing implements costs an explicit entry.

Standard: ADR-062 (architectural fitness function standard).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPO_ROOT / "packages/syn-adapters/src/syn_adapters/port_conformance.py"
_SEARCH_ROOTS = ("packages", "apps")

#: Ports with no implementation in this repository, and why. The reason is the
#: point: each says what would have to exist before a pairing could be written,
#: so the entry stops being true the moment that thing lands.
_UNIMPLEMENTED: dict[str, str] = {
    "DelegateIdentityPort": (
        "By design, the implementation is a harness concern and lands in "
        "agentic-primitives (#895). Contract-tested against a local double in "
        "packages/syn-domain/tests/contexts/agent_sessions/"
        "test_delegate_identity_port.py."
    ),
    "GitConfigurationPort": (
        "Declared and never implemented or consumed -- no adapter provides it "
        "and no call site asks for it. Kept here rather than deleted because "
        "removing a published port is a separate decision from #1305."
    ),
    "TokenInjectionPort": (
        "DirectTokenInjectionAdapter and MemoryTokenInjectionAdapter are "
        "paired in the manifest. SidecarTokenInjectionAdapter is not: its "
        "inject() takes a required sidecar_handle the port has no slot for, "
        "so it is genuinely a different operation rather than a drifted "
        "spelling of this one. Widening the port to fit it would oblige every "
        "other implementation to accept a sidecar handle it has no use for."
    ),
}


def _is_protocol(node: ast.ClassDef) -> bool:
    return any("Protocol" in ast.unparse(base) for base in node.bases)


def _is_production_source(path: Path) -> bool:
    parts = path.parts
    return (
        "src" in parts
        and "tests" not in parts
        and not path.name.startswith("test_")
        and "node_modules" not in parts
    )


def _declared_ports() -> dict[str, Path]:
    """Every ``Protocol`` named ``*Port`` in production source, by name."""
    ports: dict[str, Path] = {}
    for root in _SEARCH_ROOTS:
        for file in sorted((_REPO_ROOT / root).rglob("*.py")):
            if not _is_production_source(file):
                continue
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ClassDef)
                    and node.name.endswith("Port")
                    and _is_protocol(node)
                ):
                    ports[node.name] = file.relative_to(_REPO_ROOT)
    return ports


def _manifest_names() -> set[str]:
    """Names the manifest annotates something with.

    Read as the ANNOTATIONS it writes, not as the identifiers it mentions, so
    importing a port and never pairing it does not count as pairing it. Both
    sides of ``import X as Y`` count: the manifest renames two ports that are
    declared twice under one name.
    """
    tree = ast.parse(_MANIFEST.read_text(encoding="utf-8"))
    annotated: set[str] = set()
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            annotated.add(ast.unparse(node.annotation))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
    return {aliases.get(name, name) for name in annotated}


@pytest.mark.architecture
class TestEveryPortIsPaired:
    def test_manifest_is_readable(self) -> None:
        """Guards the checks below: an unreadable manifest would make every
        port look unpaired, or - worse, if the discovery were the thing that
        broke - make every port look paired.
        """
        assert _MANIFEST.is_file(), f"conformance manifest missing at {_MANIFEST}"
        assert _manifest_names(), "manifest annotates nothing"

    def test_discovery_finds_the_port_that_started_this(self) -> None:
        """Pins the discovery itself. Silent under-collection is the failure
        mode that would make this whole test pass over nothing.
        """
        ports = _declared_ports()
        assert "WorkflowExecutionRepositoryPort" in ports
        assert len(ports) > 20, f"suspiciously few ports discovered: {len(ports)}"

    def test_every_port_is_paired_or_declared_unimplemented(self) -> None:
        unpaired = sorted(
            f"{name} ({path})"
            for name, path in _declared_ports().items()
            if name not in _manifest_names() and name not in _UNIMPLEMENTED
        )
        assert not unpaired, (
            "These ports are checked by nothing. Pair each with its "
            f"implementation in {_MANIFEST.relative_to(_REPO_ROOT)}, or add it "
            "to _UNIMPLEMENTED with the reason no implementation exists:\n  "
            + "\n  ".join(unpaired)
        )

    def test_no_stale_unimplemented_entries(self) -> None:
        """An entry that names a port nobody declares any more is permission
        standing open for a name that could come back meaning something else.
        """
        declared = _declared_ports()
        stale = sorted(name for name in _UNIMPLEMENTED if name not in declared)
        assert not stale, (
            "_UNIMPLEMENTED names ports that no longer exist; delete them: " + ", ".join(stale)
        )
