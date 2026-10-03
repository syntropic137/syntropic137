"""`agent-fitness.sh` either runs fitness or says loudly that it did not (#1498).

Runs the real script against fake `cargo`, `rustup` and `just` on an otherwise
empty PATH, so every branch is driven by what the workspace actually has.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[1] / "agent-fitness.sh"
BASH = shutil.which("bash") or "/bin/bash"
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
    '  fitness-check) exit "${{FITNESS_EXIT:-0}}" ;;\n'
    "esac\n"
)


@dataclass(frozen=True)
class Run:
    code: int
    output: str
    rustup_calls: list[str]
    just_calls: list[str]


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
    if toolchain:
        (tmp_path / "toolchain").touch()
    result = subprocess.run(
        [BASH, str(SCRIPT)],
        cwd=tmp_path,
        env={"PATH": str(bin_dir), "STATE": str(tmp_path), **(env or {})},
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
