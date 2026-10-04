"""`run-gate-steps.sh` runs every step it is given, in order, and stops at the first failure (#1585).

`test_ci_and_preflight_agree.py` pins WHICH steps the gate hands the runner,
read from `just --dry-run`. That says nothing about whether the runner then
executes them, so these drive the real script against a fake `just` that
records each recipe it was asked to run.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[1] / "run-gate-steps.sh"
BASH = shutil.which("bash") or "/bin/bash"

# Exits with $FAIL_<recipe> if set. The prewarm sleeps, then logs, so a
# consumer that did not wait for it is logged BEFORE it.
_FAKE_JUST = (
    "#!{bash}\n"
    'if [[ "$1" == prewarm ]]; then sleep 0.3; fi\n'
    'echo "$1" >> "$STATE/just.log"\n'
    'var="FAIL_${{1//-/_}}"\n'
    'exit "${{!var:-0}}"\n'
)


@dataclass(frozen=True)
class Run:
    code: int
    output: str
    calls: list[str]


def run(tmp_path: Path, *args: str, env: dict[str, str] | None = None) -> Run:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "just"
    fake.write_text(_FAKE_JUST.format(bash=BASH))
    fake.chmod(0o755)
    for name in ("awk", "date", "mktemp", "rm", "cat", "sleep"):
        real = shutil.which(name)
        assert real, f"{name} is not on PATH"
        (bin_dir / name).symlink_to(real)
    result = subprocess.run(
        [BASH, str(SCRIPT), *args],
        env={"PATH": str(bin_dir), "STATE": str(tmp_path), **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )
    log = tmp_path / "just.log"
    calls = log.read_text().splitlines() if log.exists() else []
    return Run(result.returncode, result.stdout + result.stderr, calls)


def test_every_step_runs_in_order(tmp_path: Path) -> None:
    result = run(tmp_path, "gate", "one", "two", "three")
    assert result.code == 0, result.output
    assert result.calls == ["one", "two", "three"]
    for step in ("one", "two", "three"):
        assert f"[gate] {step} ok " in result.output
    assert "[gate] all 3 steps ok; total " in result.output


def test_the_first_failure_stops_the_gate_with_its_exit_code(tmp_path: Path) -> None:
    result = run(tmp_path, "gate", "one", "two", "three", env={"FAIL_two": "7"})
    assert result.code == 7
    assert result.calls == ["one", "two"], "a step after the failure ran"
    assert "[gate] two FAILED (exit 7)" in result.output
    assert "three" not in result.output


def test_the_prewarm_finishes_before_its_consumer_starts(tmp_path: Path) -> None:
    result = run(tmp_path, "--prewarm", "prewarm:three", "gate", "one", "two", "three")
    assert result.code == 0, result.output
    assert result.calls.index("prewarm") < result.calls.index("three")
    assert [c for c in result.calls if c != "prewarm"] == ["one", "two", "three"]
    assert "[gate] prewarm (background) ok " in result.output
    assert "[gate] all 3 steps ok" in result.output


def test_a_failed_prewarm_does_not_stop_the_gate(tmp_path: Path) -> None:
    """Its consumer redoes the work in the foreground and reports the real error."""
    result = run(
        tmp_path, "--prewarm", "prewarm:two", "gate", "one", "two", env={"FAIL_prewarm": "69"}
    )
    assert result.code == 0, result.output
    assert result.calls[-1] == "two"
    assert "[gate] prewarm (background) FAILED (exit 69)" in result.output


def test_an_early_failure_kills_the_prewarm(tmp_path: Path) -> None:
    result = run(tmp_path, "--prewarm", "prewarm:two", "gate", "one", "two", env={"FAIL_one": "3"})
    assert result.code == 3
    # The killed prewarm never reaches its log line.
    assert result.calls == ["one"]
