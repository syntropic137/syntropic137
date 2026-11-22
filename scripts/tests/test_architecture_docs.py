"""architecture-docs.sh: the markdown regenerates and checks without `vsa`,
and the svg, which still needs it, is reported NOT RUN rather than passed (#1782).

Each test runs the real script in a temp git repo holding only what it reads,
with a PATH built by hand so `vsa`, `pnpm` and `node` are present only when a
test puts them there. `uv run python` is shimmed to this interpreter, so no
test builds a venv.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SVG = "docs/architecture/vsa-overview.svg"
STALE_MARKDOWN = "docs/architecture/projection-subscriptions.md"
COPIED = [
    "scripts/architecture-docs.sh",
    "scripts/architecture_manifest.py",
    "scripts/generate-architecture-docs.py",
    "vsa.yaml",
    "packages/syn-domain/src/syn_domain/contexts",
    SVG,
    STALE_MARKDOWN,
    "docs/architecture/event-flows/README.md",
    "README.md",
    "apps/syn-docs/content/docs/guide/architecture.mdx",
    "apps/syn-docs/content/docs/architecture/index.mdx",
]
TOOLS = ["bash", "git", "mktemp", "rm", "mkdir", "dirname", "cp", "cmp", "diff", "head", "cat"]

# Out of canonical order on purpose: the svg must be drawn from the
# canonicalised manifest, as it was before #1782.
VSA_MANIFEST = '{"z": [2, 1], "a": 1}'
CANONICAL_SVG = json.dumps({"a": 1, "z": [1, 2]}, indent=2) + "\n"


def _executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in COPIED:
        src, dst = REPO / rel, root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    path = tmp_path / "bin"
    path.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        assert found, f"{tool} is needed to run architecture-docs.sh"
        (path / tool).symlink_to(found)
    # `uv run python ARGS` -> this interpreter with ARGS.
    _executable(path / "uv", f'shift 2\nexec "{sys.executable}" "$@"')
    return path


def _add_svg_toolchain(bin_dir: Path) -> None:
    """Stand-ins for vsa, pnpm and the node visualizer, as CI has the real ones."""
    _executable(
        bin_dir / "vsa",
        f'while [ "$1" != "--output" ]; do shift; done\nprintf \'%s\' \'{VSA_MANIFEST}\' > "$2"',
    )
    _executable(bin_dir / "pnpm", "exit 0")
    # node dist/index.js MANIFEST --format svg --type architecture --output DIR
    _executable(bin_dir / "node", 'cat "$2" > "$8/vsa-overview.svg"')


def _run(repo: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(bin_dir / "bash"), "scripts/architecture-docs.sh", *args],
        cwd=repo,
        env={"PATH": str(bin_dir), "HOME": str(repo)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_without_vsa_the_markdown_is_checked_and_the_svg_reported_not_run(
    repo: Path, bin_dir: Path
) -> None:
    result = _run(repo, bin_dir, "--check")

    assert result.returncode == 0, result.stderr
    assert f"NOT RUN: {SVG} (needs vsa + pnpm; CI checks it)" in result.stderr
    assert STALE_MARKDOWN in result.stdout
    assert SVG not in result.stdout


def test_without_vsa_a_stale_markdown_file_fails_the_check(repo: Path, bin_dir: Path) -> None:
    page = repo / STALE_MARKDOWN
    page.write_text(page.read_text() + "drift\n")

    result = _run(repo, bin_dir, "--check")

    assert result.returncode == 1
    assert f"Architecture docs are stale: {STALE_MARKDOWN}" in result.stderr
    assert f"NOT RUN: {SVG}" in result.stderr


def test_without_vsa_write_mode_regenerates_the_markdown_and_leaves_the_svg(
    repo: Path, bin_dir: Path
) -> None:
    page = repo / STALE_MARKDOWN
    fresh = page.read_text()
    page.write_text("stale\n")
    svg_before = (repo / SVG).read_bytes()

    result = _run(repo, bin_dir)

    assert result.returncode == 0, result.stderr
    assert page.read_text() == fresh
    assert (repo / SVG).read_bytes() == svg_before
    assert f"NOT RUN: {SVG}" in result.stderr


def test_with_vsa_and_pnpm_the_svg_is_drawn_from_vsa_and_checked(repo: Path, bin_dir: Path) -> None:
    _add_svg_toolchain(bin_dir)
    (repo / "lib/event-sourcing-platform").mkdir(parents=True)

    stale = _run(repo, bin_dir, "--check")
    assert stale.returncode == 1
    assert f"Architecture docs are stale: {SVG}" in stale.stderr

    (repo / SVG).write_text(CANONICAL_SVG)
    fresh = _run(repo, bin_dir, "--check")
    assert fresh.returncode == 0, fresh.stderr
    assert SVG in fresh.stdout
    assert "NOT RUN" not in fresh.stderr
