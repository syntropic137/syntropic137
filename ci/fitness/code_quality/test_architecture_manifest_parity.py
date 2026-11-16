"""Parity: scripts/architecture_manifest.py equals `vsa manifest` for every
field the architecture docs generator reads (#1782).

The Python reader exists so that a machine without `vsa` (the agent
workspace) can regenerate the architecture docs. That only works while it
discovers what `vsa` discovers. Here both run on the same trees: the repo
itself, and the unit-test fixture, which exercises rules the repo does not
(a versioned event, a context with no domain/, a skipped __pycache__). The
generator then runs on both manifests and must write the same docs.

Runs in CI's Architectural Fitness job (setup-vsa, then `just preflight`), and
in `just preflight` on a dev machine. In an agent workspace it is NOT RUN.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests"))

from architecture_manifest import ArchitectureManifest, read_manifest  # noqa: E402
from test_architecture_manifest import DIVERGENCE_TREES, make_repo  # noqa: E402

pytestmark = [pytest.mark.architecture, pytest.mark.host_tool("vsa")]

GENERATED = (
    "README.md",
    "docs/architecture/projection-subscriptions.md",
    "docs/architecture/event-flows/README.md",
    "apps/syn-docs/content/docs/guide/architecture.mdx",
    "apps/syn-docs/content/docs/architecture/index.mdx",
)
SEEDED = (GENERATED[0], *GENERATED[3:])


def _vsa_manifest(repo: Path, output: Path) -> ArchitectureManifest:
    subprocess.run(
        ["vsa", "manifest", "--config", "vsa.yaml", "--output", str(output), "--include-domain"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return ArchitectureManifest.model_validate_json(output.read_text())


def _generate(manifest: Path, out_root: Path) -> dict[str, str]:
    for page in SEEDED:
        (out_root / page).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / page, out_root / page)
    subprocess.run(
        [sys.executable, str(SCRIPTS / "generate-architecture-docs.py"),
         "--manifest", str(manifest), "--out-root", str(out_root)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )  # fmt: skip
    return {name: (out_root / name).read_text() for name in GENERATED}


def test_reader_matches_vsa_on_the_repo(tmp_path: Path) -> None:
    vsa = _vsa_manifest(REPO_ROOT, tmp_path / "vsa.json")
    ours = read_manifest(REPO_ROOT, Path("vsa.yaml"))
    assert ours == vsa.canonical()


def test_generator_writes_the_same_docs_from_either_manifest(tmp_path: Path) -> None:
    _vsa_manifest(REPO_ROOT, tmp_path / "vsa.json")
    (tmp_path / "ours.json").write_text(
        read_manifest(REPO_ROOT, Path("vsa.yaml")).model_dump_json(indent=2)
    )
    assert _generate(tmp_path / "ours.json", tmp_path / "ours") == _generate(
        tmp_path / "vsa.json", tmp_path / "vsa"
    )


def test_reader_matches_vsa_on_the_unit_fixture(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    vsa = _vsa_manifest(repo, tmp_path / "vsa.json")
    assert read_manifest(repo, Path("vsa.yaml")) == vsa.canonical()


@pytest.mark.parametrize("tree", sorted(DIVERGENCE_TREES))
def test_reader_matches_vsa_where_review_found_divergences(tmp_path: Path, tree: str) -> None:
    """Layouts the repo does not use today, each one a divergence independent
    review reproduced (#2292): disabled versioning, a nested domain path, a
    symlinked context directory. vsa itself is the oracle here."""
    repo = DIVERGENCE_TREES[tree](tmp_path / "repo")
    vsa = _vsa_manifest(repo, tmp_path / "vsa.json")
    assert read_manifest(repo, Path("vsa.yaml")) == vsa.canonical()
