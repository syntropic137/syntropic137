"""generate-architecture-docs.py: the output the drift check compares must not
depend on the order `vsa manifest` happened to walk the filesystem in."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[1] / "generate-architecture-docs.py"

README = """The system is organized into 9 bounded contexts following VSA:

| Context | Aggregates | Purpose |
|---------|------------|---------|
| **`orchestration`** | Workspace | Workflow execution |
| **`artifacts`** | Artifact | Artifact storage |
"""


def _manifest(reverse: bool) -> dict[str, object]:
    aggregates = [
        {"name": "WorkspaceAggregate", "context": "orchestration"},
        {"name": "EvalAggregate", "context": "orchestration"},
        {"name": "ArtifactAggregate", "context": "artifacts"},
    ]
    # Equal projection counts, so only a tie-break makes the order stable.
    event_to_projections = {
        "WorkspaceCreated": ["B", "A"],
        "EvalRecorded": ["A", "B"],
    }
    if reverse:
        aggregates.reverse()
        event_to_projections = dict(reversed(list(event_to_projections.items())))
        event_to_projections = {k: list(reversed(v)) for k, v in event_to_projections.items()}
    return {
        "generated_at": "2026-10-07T00:00:00Z",
        "bounded_contexts": [{"name": "orchestration"}, {"name": "artifacts"}],
        "domain": {
            "aggregates": aggregates,
            "commands": [],
            "events": [],
            "projections": [],
            "relationships": {"event_to_projections": event_to_projections},
        },
    }


def _run(root: Path, readme: str, manifest: dict[str, object]) -> subprocess.CompletedProcess[str]:
    root.mkdir()
    (root / "README.md").write_text(readme)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", "manifest.json", "--out-root", "."],
        capture_output=True,
        text=True,
        cwd=root,
    )


def _generate(tmp_path: Path, reverse: bool) -> dict[str, str]:
    root = tmp_path / ("reversed" if reverse else "forward")
    _run(root, README, _manifest(reverse)).check_returncode()
    return {
        name: (root / name).read_text()
        for name in (
            "README.md",
            "docs/architecture/projection-subscriptions.md",
            "docs/architecture/event-flows/README.md",
            "manifest.json",
        )
    }


def test_output_is_independent_of_manifest_order(tmp_path: Path) -> None:
    assert _generate(tmp_path, reverse=False) == _generate(tmp_path, reverse=True)


def test_readme_aggregate_column_lists_every_aggregate_in_its_context(tmp_path: Path) -> None:
    readme = _generate(tmp_path, reverse=True)["README.md"]
    assert "| **`orchestration`** | Eval, Workspace | Workflow execution |" in readme
    assert "| **`artifacts`** | Artifact | Artifact storage |" in readme


def test_canonicalize_sorts_maps_and_arrays_recursively() -> None:
    spec = importlib.util.spec_from_file_location("gen_arch_docs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    canonical = module.canonicalize({"b": [3, 1, 2], "a": [{"n": "y"}, {"n": "x"}]})
    assert json.dumps(canonical) == '{"a": [{"n": "x"}, {"n": "y"}], "b": [1, 2, 3]}'


def test_readme_context_count_follows_the_manifest(tmp_path: Path) -> None:
    readme = _generate(tmp_path, reverse=False)["README.md"]
    assert "organized into 2 bounded contexts" in readme


def test_readme_missing_a_context_row_fails(tmp_path: Path) -> None:
    readme = README.replace("| **`orchestration`** | Workspace | Workflow execution |\n", "")
    result = _run(tmp_path / "missing", readme, _manifest(reverse=False))
    assert result.returncode != 0
    assert "missing rows for orchestration" in result.stderr


def test_readme_row_for_an_unknown_context_fails(tmp_path: Path) -> None:
    readme = README.replace("`artifacts`", "`retired_context`")
    result = _run(tmp_path / "unknown", readme, _manifest(reverse=False))
    assert result.returncode != 0
    assert "missing rows for artifacts" in result.stderr
    assert "unknown contexts retired_context" in result.stderr


def test_docs_site_counts_and_aggregate_table_are_generated(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    page = root / "apps/syn-docs/content/docs/architecture/index.mdx"
    page.parent.mkdir(parents=True)
    page.write_text(
        "**Commands (42):** ...\n\n| Context | Aggregates | Key |\n|---|---|---|\n"
        "| `orchestration` | Workspace | Workflows |\n| `artifacts` | Artifact | Storage |\n"
    )
    manifest = _manifest(reverse=False)
    manifest["domain"]["commands"] = [{"name": "A"}, {"name": "B"}]  # type: ignore[index]
    (root / "README.md").write_text(README)
    (root / "manifest.json").write_text(json.dumps(manifest))
    subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", "manifest.json", "--out-root", "."],
        check=True,
        capture_output=True,
        cwd=root,
    )
    content = page.read_text()
    assert "**Commands (2):**" in content
    assert "| `orchestration` | Eval, Workspace | Workflows |" in content
