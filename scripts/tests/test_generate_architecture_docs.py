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

README = """| Context | Aggregates | Purpose |
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
        "domain": {
            "aggregates": aggregates,
            "commands": [],
            "events": [],
            "projections": [],
            "relationships": {"event_to_projections": event_to_projections},
        },
    }


def _generate(tmp_path: Path, reverse: bool) -> dict[str, str]:
    root = tmp_path / ("reversed" if reverse else "forward")
    root.mkdir()
    (root / "README.md").write_text(README)
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(_manifest(reverse)))
    subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(manifest), "--out-root", str(root)],
        check=True,
        capture_output=True,
        cwd=root,
    )
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
