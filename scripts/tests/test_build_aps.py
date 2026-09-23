"""Exercise cache acceptance against real gitlinks and a fake compiler."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[1] / "build-aps.sh"
SUBMODULE = Path("lib/agent-paradise-standards-system")


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(path),
            *args,
        ],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sub = tmp_path / SUBMODULE
    sub.mkdir(parents=True)
    git(sub, "init", "-q")
    (sub / ".gitignore").write_text("/target/\n")
    (sub / "source.rs").write_text("// original\n")
    git(sub, "add", ".")
    git(sub, "commit", "-qm", "original")
    git(tmp_path, "init", "-q")
    git(
        tmp_path,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{git(sub, 'rev-parse', 'HEAD')},{SUBMODULE}",
    )
    git(tmp_path, "commit", "-qm", "pin")
    binary = sub / "target/release/apss-dev"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\necho apss-dev-test\n")
    binary.chmod(0o755)
    tools = tmp_path / "fake-tools"
    tools.mkdir()
    cargo = tools / "cargo"
    cargo.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CARGO_LOG"\nexit "${CARGO_EXIT:-0}"\n')
    cargo.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
    monkeypatch.setenv("CARGO_LOG", str(tmp_path / "cargo.log"))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SYN_APS_CACHE_HIT", "true")
    return tmp_path


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT)], cwd=root, capture_output=True, text=True)


def test_exact_hit_reuses_binary(checkout: Path) -> None:
    result = run(checkout)
    assert result.returncode == 0, result.stderr
    assert "Reusing APS CLI" in result.stdout
    assert not (checkout / "cargo.log").exists()


@pytest.mark.parametrize(
    "case", ["local", "miss", "wrong-pin", "dirty", "untracked", "missing", "nonexecutable"]
)
def test_unproven_binary_builds(
    checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    sub = checkout / SUBMODULE
    binary = sub / "target/release/apss-dev"
    if case == "local":
        monkeypatch.delenv("GITHUB_ACTIONS")
    elif case == "miss":
        monkeypatch.setenv("SYN_APS_CACHE_HIT", "false")
    elif case in {"wrong-pin", "dirty"}:
        (sub / "source.rs").write_text("// changed without a version bump\n")
        if case == "wrong-pin":
            git(sub, "commit", "-qam", "changed")
    elif case == "untracked":
        (sub / "new.rs").write_text("// new source\n")
    elif case == "missing":
        binary.unlink()
    else:
        binary.chmod(0o644)
    result = run(checkout)
    assert result.returncode == 0, result.stderr
    args = (checkout / "cargo.log").read_text().splitlines()
    assert args == [
        "build",
        "--locked",
        "--release",
        "--manifest-path",
        f"{SUBMODULE}/Cargo.toml",
        "-p",
        "aps-cli",
    ]


def test_corrupt_cache_fails_closed(checkout: Path) -> None:
    (checkout / SUBMODULE / "target/release/apss-dev").write_text("#!/bin/sh\nexit 37\n")
    assert run(checkout).returncode == 37


def test_failed_build_propagates(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_APS_CACHE_HIT", "false")
    monkeypatch.setenv("CARGO_EXIT", "42")
    assert run(checkout).returncode == 42
