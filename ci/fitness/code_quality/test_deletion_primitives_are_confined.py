"""Fitness function: host deletion stays in a known set of modules (#1983).

The disk janitor's slice 1 grants NO new deletion power. Every way this code
deletes from the host - ``shutil.rmtree``, ``os.remove``/``os.unlink``/
``os.rmdir``, ``docker rm`` and ``docker ... prune`` - is listed module by
module in ``[deletion_primitives]`` of ``fitness_exceptions.toml``. A new one
fails here until someone writes down why it is safe, and a listed module that
no longer deletes fails too, so the list only shrinks.

Second invariant: every ``os.walk`` under ``workspace_backends`` passes
``onerror``. Without it a directory this process cannot list is silently
skipped, which reads as "empty" - and the reclaimer deletes what it never saw.

Scope: ``apps/syn-api/src``, ``packages/syn-adapters/src``, ``infra/scripts``.
The detection is syntactic (AST), which is the point: an alias or a wrapper
that hides the call from this check hides it from a reviewer too.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import load_exceptions, rel_path, repo_root

if TYPE_CHECKING:
    from pathlib import Path

_SECTION = "deletion_primitives"
_SCOPES = ("apps/syn-api/src", "packages/syn-adapters/src", "infra/scripts")
_WALK_SCOPE = "packages/syn-adapters/src/syn_adapters/workspace_backends"
_WALK_SECTION = "os_walk_without_onerror"

_FS_DELETERS = {
    ("shutil", "rmtree"),
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
}
_DOCKER_DELETE_VERBS = {"rm", "prune"}


def _files(root: Path, scope: str) -> list[Path]:
    base = root / scope
    return sorted(
        p
        for p in base.rglob("*.py")
        if "tests" not in p.relative_to(base).parts and not p.name.startswith("test_")
    )


def _constants(node: ast.Call) -> list[str]:
    """String constants among a call's positional args, one list literal deep."""
    found: list[str] = []
    for arg in node.args:
        elements = arg.elts if isinstance(arg, ast.List | ast.Tuple) else [arg]
        found.extend(
            e.value for e in elements if isinstance(e, ast.Constant) and isinstance(e.value, str)
        )
    return found


def _callee(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def deletions(tree: ast.AST) -> list[int]:
    """Lines that delete from the host or remove docker objects."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (node.value.id, node.attr) in _FS_DELETERS
        ):
            lines.append(node.lineno)
        if isinstance(node, ast.Call):
            constants = _constants(node)
            via_docker = "docker" in constants or "docker" in _callee(node).lower()
            if via_docker and _DOCKER_DELETE_VERBS & set(constants):
                lines.append(node.lineno)
    return lines


def walks_without_onerror(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and (node.func.value.id, node.func.attr) == ("os", "walk")
        and not any(k.arg == "onerror" for k in node.keywords)
    ]


def _deleting_modules(root: Path) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for scope in _SCOPES:
        for path in _files(root, scope):
            lines = deletions(ast.parse(path.read_text(), str(path)))
            if lines:
                found[rel_path(path, root)] = lines
    return found


@pytest.mark.architecture
class TestDeletionPrimitivesAreConfined:
    def test_no_module_outside_the_list_deletes(self) -> None:
        root = repo_root()
        allowed = load_exceptions(root).get(_SECTION, {})
        unlisted = {m: lines for m, lines in _deleting_modules(root).items() if m not in allowed}
        assert not unlisted, (
            "Host deletion outside the modules listed in "
            f"[{_SECTION}] of ci/fitness/fitness_exceptions.toml (#1983). Route it "
            "through an existing deleter, or list the module with the reason it "
            "is safe:\n" + "\n".join(f"  {m}: lines {lines}" for m, lines in unlisted.items())
        )

    def test_every_listed_module_still_deletes_and_says_why(self) -> None:
        root = repo_root()
        allowed = load_exceptions(root).get(_SECTION, {})
        stale = sorted(set(allowed) - set(_deleting_modules(root)))
        assert not stale, f"[{_SECTION}] lists modules that no longer delete: {stale}"
        unexplained = sorted(m for m, entry in allowed.items() if not entry.get("reason"))
        assert not unexplained, f"[{_SECTION}] entries without a reason: {unexplained}"

    def test_every_workspace_walk_fails_closed(self) -> None:
        root = repo_root()
        budgets = load_exceptions(root).get(_WALK_SECTION, {})
        bare = {
            rel_path(path, root): lines
            for path in _files(root, _WALK_SCOPE)
            if (lines := walks_without_onerror(ast.parse(path.read_text(), str(path))))
        }
        over = {
            m: lines for m, lines in bare.items() if len(lines) > budgets.get(m, {}).get("max", 0)
        }
        assert not over, (
            "os.walk without onerror under workspace_backends silently skips what it "
            "cannot list (#1983). Pass onerror that raises:\n"
            + "\n".join(f"  {m}: lines {lines}" for m, lines in over.items())
        )
        # A ratchet: a budget above what is there must come down with it.
        loose = sorted(m for m, b in budgets.items() if len(bare.get(m, [])) < b["max"])
        assert not loose, f"[{_WALK_SECTION}] budgets above the current count: {loose}"


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("source", "caught"),
    [
        ("import shutil\nshutil.rmtree(p)\n", True),
        ("import os\nos.remove(p)\n", True),
        ("await asyncio.create_subprocess_exec('docker', 'rm', '-f', c)\n", True),
        ("await _docker(['volume', 'rm', v])\n", True),
        ("await _docker('image', 'prune', '-f')\n", True),
        ("await workspace.execute(['rm', '-rf', '/workspace/x'])\n", False),
        ("shutil.copytree(a, b)\n", False),
    ],
)
def test_the_detector_sees_each_form(source: str, caught: bool) -> None:
    assert bool(deletions(ast.parse(source))) is caught


@pytest.mark.architecture
def test_the_walk_detector_sees_a_bare_walk() -> None:
    assert walks_without_onerror(ast.parse("os.walk(p)\n")) == [1]
    assert walks_without_onerror(ast.parse("os.walk(p, onerror=_raise)\n")) == []


# --- owner decision (#1983): the janitor deletes scratch, never run history ---

#: Every module of the workspace janitor.
_JANITOR_MODULES = (
    "apps/syn-api/src/syn_api/services/workspace_dir_reclaim.py",
    "apps/syn-api/src/syn_api/services/workspace_reclaim_status.py",
    "apps/syn-api/src/syn_api/services/disk_pressure.py",
    "packages/syn-adapters/src/syn_adapters/workspace_backends/stale_dirs.py",
    "packages/syn-adapters/src/syn_adapters/workspace_backends/remote_refs.py",
    "apps/syn-api/src/syn_api/vps_reclaim.py",
    "infra/scripts/vps_reclaim.py",
)

#: Where run history lives: the event store, Postgres, MinIO artifacts,
#: transcripts and telemetry. The janitor may not even import a writer of it.
_HISTORY_IMPORTS = (
    "event_sourcing",
    "syn_adapters.storage",
    "syn_adapters.event_store",
    "syn_adapters.observability",
    "asyncpg",
    "minio",
    "boto3",
)

#: Method names that write or delete stored history.
_HISTORY_WRITES = {
    "save",
    "upload",
    "delete",
    "delete_all",
    "delete_object",
    "remove_object",
    "append_events",
    "purge",
    "truncate",
    # The capture spool index is read (session_ids) and never advanced here.
    "project",
    "advance",
    "mark_drained",
    "settle",
    "settle_run",
    "execute",
}


def history_reach(tree: ast.AST) -> list[str]:
    """Imports of a run-history store, and calls of a history write, in one module."""
    found: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        found.extend(
            f"line {node.lineno}: imports {name}"
            for name in names
            if any(name == p or name.startswith(p + ".") for p in _HISTORY_IMPORTS)
        )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _HISTORY_WRITES
        ):
            found.append(f"line {node.lineno}: calls .{node.func.attr}()")
    return found


@pytest.mark.architecture
def test_the_janitor_never_reaches_run_history() -> None:
    root = repo_root()
    reach = {
        module: hits
        for module in _JANITOR_MODULES
        if (hits := history_reach(ast.parse((root / module).read_text(), module)))
    }
    assert not reach, (
        "All run history is kept for every run (owner decision, #1983): the workspace "
        "janitor deletes only scratch directories under the workspace base and must not "
        "import or write the event store, Postgres, MinIO, transcripts or telemetry:\n"
        + "\n".join(f"  {m}: {hits}" for m, hits in reach.items())
    )


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("source", "caught"),
    [
        ("from syn_adapters.storage.artifact_storage import x\n", True),
        ("import event_sourcing\n", True),
        ("await store.delete_all('p')\n", True),
        ("await storage.upload(k, b)\n", True),
        ("from syn_adapters.projection_stores import get_projection_store\n", False),
        ("items.append(x)\n", False),
    ],
)
def test_the_history_detector_sees_each_form(source: str, caught: bool) -> None:
    assert bool(history_reach(ast.parse(source))) is caught
