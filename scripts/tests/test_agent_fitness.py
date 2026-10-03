"""`agent-fitness.sh` either runs fitness or says loudly that it did not (#1498).

Runs the real script against fake `cargo`, `rustup` and `just` on an otherwise
empty PATH, so every branch is driven by what the workspace actually has. The
last tests swap the fake `just` for the real one and the repo's real justfile,
so the dependency chain of `fitness-check` is the one CI runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[1] / "agent-fitness.sh"
BASH = shutil.which("bash") or "/bin/bash"
JUST = shutil.which("just")
JUSTFILE = SCRIPT.parents[1] / "justfile"
NOT_RUN = "FITNESS NOT RUN:"

# `cargo` behaves like the rustup proxy: it fails until a toolchain exists.
_FAKE_CARGO = '#!{bash}\n[[ -e "$STATE/toolchain" ]]\n'
_FAKE_RUSTUP = (
    '#!{bash}\necho "$*" >> "$STATE/rustup.log"\n'
    '[[ "${{RUSTUP_EXIT:-0}}" == 0 ]] || exit "$RUSTUP_EXIT"\n'
    ': > "$STATE/toolchain"\n'
)
_FAKE_JUST = (
    '#!{bash}\necho "$*" >> "$STATE/just.log"\n'
    'case "$1" in\n'
    '  aps-build) exit "${{APS_BUILD_EXIT:-0}}" ;;\n'
    # Like the real recipe: the marker is touched only once every prerequisite
    # passed, so PREREQ_EXIT fails it before the thresholds are reached.
    "  fitness-check)\n"
    '    [[ "${{PREREQ_EXIT:-0}}" == 0 ]] || exit "$PREREQ_EXIT"\n'
    '    : > "$SYN_FITNESS_STARTED_FILE"\n'
    '    exit "${{FITNESS_EXIT:-0}}" ;;\n'
    "esac\n"
)


@dataclass(frozen=True)
class Run:
    code: int
    output: str
    rustup_calls: list[str]
    just_calls: list[str]


def _link_real(bin_dir: Path, *names: str) -> None:
    for name in names:
        real = shutil.which(name)
        assert real, f"{name} is not on PATH"
        (bin_dir / name).symlink_to(real)


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def run(
    tmp_path: Path,
    *,
    toolchain: bool = True,
    rustup: bool = True,
    env: dict[str, str] | None = None,
) -> Run:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {"cargo": _FAKE_CARGO, "just": _FAKE_JUST}
    if rustup:
        fakes["rustup"] = _FAKE_RUSTUP
    for name, body in fakes.items():
        tool = bin_dir / name
        tool.write_text(body.format(bash=BASH))
        tool.chmod(0o755)
    _link_real(bin_dir, "mktemp", "rm")
    if toolchain:
        (tmp_path / "toolchain").touch()
    result = subprocess.run(
        [BASH, str(SCRIPT)],
        cwd=tmp_path,
        env={
            "PATH": str(bin_dir),
            "STATE": str(tmp_path),
            "TMPDIR": str(tmp_path),
            **(env or {}),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return Run(
        code=result.returncode,
        output=result.stdout + result.stderr,
        rustup_calls=_lines(tmp_path / "rustup.log"),
        just_calls=_lines(tmp_path / "just.log"),
    )


def test_with_a_toolchain_it_runs_the_real_fitness_check(tmp_path: Path) -> None:
    run_ = run(tmp_path)
    assert run_.code == 0, run_.output
    assert run_.just_calls == ["aps-build", "fitness-check"]
    assert run_.rustup_calls == []
    assert NOT_RUN not in run_.output


def test_without_a_toolchain_it_installs_stable_then_runs_fitness(tmp_path: Path) -> None:
    run_ = run(tmp_path, toolchain=False)
    assert run_.code == 0, run_.output
    # --no-self-update: without it rustup fails on the image's read-only
    # /usr/local/bin even after a good install.
    assert run_.rustup_calls == ["toolchain install stable --profile minimal --no-self-update"]
    assert run_.just_calls == ["aps-build", "fitness-check"]


@pytest.mark.parametrize("allow", [None, "1"])
def test_a_fitness_violation_is_a_failure_not_a_skip(tmp_path: Path, allow: str | None) -> None:
    """The opt-out covers 'could not run', never 'ran and failed'."""
    env = {"FITNESS_EXIT": "1"} | ({"SYN_ALLOW_FITNESS_NOT_RUN": allow} if allow else {})
    run_ = run(tmp_path, env=env)
    assert run_.code == 1
    assert NOT_RUN not in run_.output


def test_no_cargo_and_no_rustup_fails_loudly(tmp_path: Path) -> None:
    run_ = run(tmp_path, toolchain=False, rustup=False)
    assert run_.code == 69
    assert f"{NOT_RUN} no working cargo and no rustup" in run_.output
    assert run_.just_calls == []


def test_the_opt_out_passes_but_still_prints_the_line(tmp_path: Path) -> None:
    run_ = run(tmp_path, toolchain=False, rustup=False, env={"SYN_ALLOW_FITNESS_NOT_RUN": "1"})
    assert run_.code == 0
    assert NOT_RUN in run_.output
    assert run_.just_calls == []


def test_a_failed_toolchain_install_fails_loudly(tmp_path: Path) -> None:
    run_ = run(tmp_path, toolchain=False, env={"RUSTUP_EXIT": "1"})
    assert run_.code == 69
    assert f"{NOT_RUN} rustup could not install" in run_.output
    assert run_.just_calls == []


def test_a_failed_aps_build_fails_loudly_and_skips_nothing_silently(tmp_path: Path) -> None:
    run_ = run(tmp_path, env={"APS_BUILD_EXIT": "101"})
    assert run_.code == 69
    assert f"{NOT_RUN} aps-build failed" in run_.output
    assert run_.just_calls == ["aps-build"]


@pytest.mark.parametrize("allow", [None, "1"])
def test_a_failed_prerequisite_is_not_run_and_never_waived(
    tmp_path: Path, allow: str | None
) -> None:
    """A ratchet in front of the thresholds failed: fitness did not run (#1498).

    It may be a real untyped-dicts or test-marker violation, so the opt-out must
    not turn it green; the loud line is what tells it apart from a verdict.
    """
    env = {"PREREQ_EXIT": "72"} | ({"SYN_ALLOW_FITNESS_NOT_RUN": allow} if allow else {})
    run_ = run(tmp_path, env=env)
    assert run_.code == 72, run_.output
    assert f"{NOT_RUN} a fitness-check prerequisite failed (exit 72)" in run_.output
    assert run_.just_calls == ["aps-build", "fitness-check"]


# --- the real justfile ------------------------------------------------------

_APS = "lib/agent-paradise-standards-system/target/release/apss-dev"
_STUB = '#!{bash}\nexit "${{{var}:-0}}"\n'
# Only `architecture-fitness validate` is the threshold check; topology is a
# prerequisite and always succeeds here.
_FAKE_APS = (
    '#!{bash}\n[[ "$2" == architecture-fitness ]] || exit 0\nexit "${{APS_VALIDATE_EXIT:-0}}"\n'
)


def run_real_just(tmp_path: Path, env: dict[str, str]) -> Run:
    """The script, the real `just` and a copy of the real justfile.

    Every external tool a recipe in fitness-check's chain calls is a stub, so
    each one can be made to fail on its own: `bash` (aps-build), `python3`
    (check-untyped-dicts), `uv` (check-test-markers, stale exceptions) and the
    aps binary at the path the justfile names.
    """
    assert JUST
    shutil.copy(JUSTFILE, tmp_path / "justfile")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "cargo": _STUB.format(bash=BASH, var="CARGO_EXIT"),
        "bash": _STUB.format(bash=BASH, var="APS_BUILD_EXIT"),
        "python3": _STUB.format(bash=BASH, var="PYTHON_EXIT"),
        "uv": _STUB.format(bash=BASH, var="UV_EXIT"),
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    aps = tmp_path / _APS
    aps.parent.mkdir(parents=True)
    aps.write_text(_FAKE_APS.format(bash=BASH))
    aps.chmod(0o755)
    # Stubs shadow the real PATH: the justfile's own backticks (`uname`, ...)
    # are evaluated before any recipe runs and need the real tools.
    result = subprocess.run(
        [BASH, str(SCRIPT)],
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "TMPDIR": str(tmp_path), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    return Run(result.returncode, result.stdout + result.stderr, [], [])


needs_just = pytest.mark.skipif(JUST is None, reason="`just` is not installed")


@needs_just
@pytest.mark.parametrize("allow", [None, "1"])
def test_real_chain_a_failed_prerequisite_prints_not_run(tmp_path: Path, allow: str | None) -> None:
    env = {"PYTHON_EXIT": "72"} | ({"SYN_ALLOW_FITNESS_NOT_RUN": allow} if allow else {})
    run_ = run_real_just(tmp_path, env)
    assert "recipe `check-untyped-dicts` failed" in run_.output, run_.output
    assert run_.code == 72, run_.output
    assert f"{NOT_RUN} a fitness-check prerequisite failed (exit 72)" in run_.output


@needs_just
def test_real_chain_a_threshold_failure_is_a_verdict(tmp_path: Path) -> None:
    run_ = run_real_just(tmp_path, {"APS_VALIDATE_EXIT": "1"})
    assert "Checking architecture fitness thresholds" in run_.output, run_.output
    assert run_.code == 1, run_.output
    assert NOT_RUN not in run_.output


@needs_just
def test_real_chain_green_runs_every_step(tmp_path: Path) -> None:
    run_ = run_real_just(tmp_path, {})
    assert run_.code == 0, run_.output
    assert "Fitness threshold checks passed" in run_.output
    assert NOT_RUN not in run_.output


def test_the_marker_sits_directly_above_the_threshold_check() -> None:
    """Runs where `just` does not: CI's unit job installs none.

    Anything between the marker and `validate` would be reported as a verdict
    when it failed, and anything after `validate` as not run.
    """
    body = JUSTFILE.read_text().split("\nfitness-check:", 1)[1].split("\n\n", 1)[0]
    commands = [line.strip() for line in body.splitlines()[1:] if not line.strip().startswith("#")]
    validate = next(i for i, c in enumerate(commands) if "architecture-fitness validate" in c)
    assert "SYN_FITNESS_STARTED_FILE" in commands[validate - 1], commands
    assert sum("SYN_FITNESS_STARTED_FILE" in c for c in commands) == 1, commands
