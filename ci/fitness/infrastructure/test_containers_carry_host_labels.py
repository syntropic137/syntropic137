"""Fitness function: every container the API creates names its host (#1310, 0.4).

The next API generation finds its predecessor's containers by ``syn.host_id``.
A creation path that forgets the labels makes containers no generation can
claim, and nothing fails until a hot upgrade strands them. So every place
production code creates a container must take its labels from ``host_labels()``.

A creation site is any of:

* a ``docker run`` / ``docker create`` argv - a literal list, or the positional
  arguments of a call, whose strings contain ``"docker", "run"`` adjacent, or
  start with ``"run"``/``"create"`` as the argument of a ``*docker*`` helper;
* a Docker SDK ``<x>.containers.create(...)`` or ``<x>.containers.run(...)``;
* an agentic_isolation ``WorkspaceConfig(...)``, which the provider turns into
  a ``docker run``.

Each site must itself receive the labels from ``host_labels()``: in the argv,
in the ``labels=`` keyword, or through a local name built from them. The
scanner is pinned to the paths known today, so a scanner that silently stops
finding them fails too.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest
from ci.fitness.conftest import production_files, rel_path

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.architecture

#: Today's creation paths: workspace, sidecar, capture recovery helper.
KNOWN_CREATION_MODULES = {
    "packages/syn-adapters/src/syn_adapters/workspace_backends/agentic/adapter.py",
    "packages/syn-adapters/src/syn_adapters/workspace_backends/docker/docker_sidecar_helpers.py",
    "packages/syn-adapters/src/syn_adapters/session_inventory/docker_recovery.py",
}


def _strings(nodes: list[ast.expr]) -> list[str | None]:
    return [
        n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None for n in nodes
    ]


def _is_docker_argv(values: list[str | None], *, docker_helper: bool) -> bool:
    for before, current in zip([None, *values], values, strict=False):
        if before == "docker" and current in {"run", "create"}:
            return True
    return docker_helper and bool(values) and values[0] in {"run", "create"}


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _creation_sites(func: ast.AST) -> list[ast.expr]:
    """Each creation site in ``func``, as the node that must carry the labels.

    For an argv that is the list itself; for ``WorkspaceConfig`` or the SDK it
    is the ``labels=`` keyword value (``None`` stands in when it is missing).
    """
    sites: dict[int, ast.expr] = {}

    def add(node: ast.expr) -> None:
        sites.setdefault(id(node), node)

    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            docker_helper = "docker" in name.lower()
            if _is_docker_argv(_strings(node.args), docker_helper=docker_helper):
                add(node)
            for arg in node.args:
                if isinstance(arg, ast.List | ast.Tuple) and _is_docker_argv(
                    _strings(arg.elts), docker_helper=docker_helper
                ):
                    add(arg)
            if name == "WorkspaceConfig" or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"create", "run"}
                and _call_name(node.func.value) == "containers"
            ):
                labels = next((k.value for k in node.keywords if k.arg == "labels"), None)
                add(labels or ast.Constant(value=None, lineno=node.lineno, col_offset=0))
        elif isinstance(node, ast.List) and _is_docker_argv(
            _strings(node.elts), docker_helper=False
        ):
            add(node)
    return list(sites.values())


def _is_host_source(node: ast.AST, carriers: set[str]) -> bool:
    if isinstance(node, ast.Call) and _call_name(node.func) == "host_labels":
        return True
    return isinstance(node, ast.Name) and node.id in carriers


def _mentions(node: ast.AST, carriers: set[str]) -> bool:
    return any(_is_host_source(n, carriers) for n in ast.walk(node))


def _label_carriers(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names in ``func`` that hold the host labels, to a fixpoint.

    Sources are a ``host_labels()`` call and a parameter named ``host`` (the
    labels a caller took from ``host_labels()``). A name carries them once it
    is assigned from a carrier, or a carrier is appended/extended into it.
    """
    carriers = {a.arg for a in [*func.args.args, *func.args.kwonlyargs] if a.arg == "host"}
    while True:
        before = len(carriers)
        for node in ast.walk(func):
            if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign) and node.value:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if _mentions(node.value, carriers):
                    carriers.update(t.id for t in targets if isinstance(t, ast.Name))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"append", "extend", "insert", "update"}
                and isinstance(node.func.value, ast.Name)
                and any(_mentions(a, carriers) for a in node.args)
            ):
                carriers.add(node.func.value.id)
        if len(carriers) == before:
            return carriers


def _assigned_name(func: ast.AST, site: ast.expr) -> str | None:
    for node in ast.walk(func):
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is site:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            return names[0] if names else None
    return None


def _scan(path: Path) -> tuple[list[int], list[int]]:
    """(lines of creation sites, lines of those without host labels).

    Each site is judged on its own: the labels must reach that argv or that
    ``labels=`` value, directly or through a name built from them. Another
    site in the same function taking them proves nothing about this one.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[int] = set()
    unlabelled: set[int] = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        carriers = _label_carriers(func)
        for site in _creation_sites(func):
            found.add(site.lineno)
            name = _assigned_name(func, site)
            if not (_mentions(site, carriers) or (name is not None and name in carriers)):
                unlabelled.add(site.lineno)
    return sorted(found), sorted(unlabelled)


def test_every_container_creation_path_carries_host_labels() -> None:
    creation_modules: set[str] = set()
    violations: list[str] = []
    for path in production_files():
        found, unlabelled = _scan(path)
        if found:
            creation_modules.add(rel_path(path))
        violations.extend(f"{rel_path(path)}:{line}" for line in unlabelled)

    missing = KNOWN_CREATION_MODULES - creation_modules
    assert not missing, f"Scanner no longer finds known container creation paths: {missing}"
    assert not violations, (
        "Container creation without host labels; take them from "
        "syn_adapters.workspace_backends.host_labels.host_labels():\n  " + "\n  ".join(violations)
    )


def _scan_source(tmp_path: Path, source: str) -> tuple[list[int], list[int]]:
    path = tmp_path / "creator.py"
    path.write_text(source, encoding="utf-8")
    return _scan(path)


def test_second_unlabelled_site_in_a_labelled_function_fails(tmp_path: Path) -> None:
    found, unlabelled = _scan_source(
        tmp_path,
        "async def f():\n"
        "    host = await host_labels()\n"
        "    await _docker(['run', *[f'--label={k}={v}' for k, v in host.items()], 'one'])\n"
        "    await _docker(['run', 'image-two'])\n",
    )
    assert found == [3, 4]
    assert unlabelled == [4]


def test_argv_labelled_by_extending_it_passes(tmp_path: Path) -> None:
    _, unlabelled = _scan_source(
        tmp_path,
        "def f(host):\n"
        "    cmd = ['docker', 'run', '-d']\n"
        "    labels = {'a': 'b', **host}\n"
        "    cmd.extend(f'--label={k}={v}' for k, v in labels.items())\n"
        "    return cmd\n",
    )
    assert unlabelled == []


def test_workspace_config_needs_host_labels_in_its_labels_keyword(tmp_path: Path) -> None:
    _, unlabelled = _scan_source(
        tmp_path,
        "async def f():\n"
        "    host = await host_labels()\n"
        "    WorkspaceConfig(image='i', labels={**host})\n"
        "    WorkspaceConfig(image='i', labels={'a': 'b'}, environment=host)\n"
        "    WorkspaceConfig(image='i')\n",
    )
    assert unlabelled == [4, 5]
