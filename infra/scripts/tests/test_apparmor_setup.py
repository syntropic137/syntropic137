"""The AppArmor host step loads and persists the Codex sandbox profile (#1398).

Runs the real script with stand-ins for docker, sudo and apparmor_parser on
PATH and temporary directories for /etc/apparmor.d and securityfs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "infra" / "scripts" / "apparmor-setup.sh"
_SHIPPED = (
    _REPO
    / "lib/agentic-workspace/lib/python/agentic_isolation/agentic_isolation/apparmor"
    / "agentic-codex-sandbox"
)
_NAME = "agentic-codex-sandbox"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


def _host(tmp_path: Path, security_options: str, *, docker_ok: bool = True) -> dict[str, str]:
    bin_dir, etc, policy, log = (
        tmp_path / "bin",
        tmp_path / "etc",
        tmp_path / "policy",
        tmp_path / "calls.log",
    )
    for directory in (bin_dir, etc, policy):
        directory.mkdir()
    _stub(
        bin_dir,
        "docker",
        f'echo docker "$@" >> {log}; ' + (f"echo '{security_options}'" if docker_ok else "exit 1"),
    )
    # apparmor_parser -r FILE: "load" it by publishing its name in securityfs.
    _stub(
        bin_dir,
        "apparmor_parser",
        f'echo apparmor_parser "$@" >> {log}; mkdir -p {policy}/p1; echo {_NAME} > {policy}/p1/name',
    )
    _stub(bin_dir, "fakesudo", f'echo sudo "$@" >> {log}; "$@"')
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SYN_APPARMOR_OS": "Linux",
        "SYN_APPARMOR_ETC_DIR": str(etc),
        "SYN_APPARMOR_POLICY_DIR": str(policy),
        "SYN_APPARMOR_SUDO": str(bin_dir / "fakesudo"),
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def _calls(tmp_path: Path) -> str:
    log = tmp_path / "calls.log"
    return log.read_text() if log.exists() else ""


APPARMOR = '["name=apparmor","name=seccomp,profile=builtin","name=cgroupns"]'
NO_APPARMOR = '["name=seccomp,profile=builtin","name=cgroupns"]'


def test_shipped_profile_exists_in_the_pinned_submodule() -> None:
    assert _SHIPPED.is_file()
    assert f"profile {_NAME}" in _SHIPPED.read_text()


def test_apparmor_host_installs_persists_and_loads(tmp_path: Path) -> None:
    env = _host(tmp_path, APPARMOR)
    assert _run(env, "--check").returncode == 1
    result = _run(env)
    assert result.returncode == 0, result.stderr
    persisted = tmp_path / "etc" / _NAME
    assert persisted.read_bytes() == _SHIPPED.read_bytes()
    assert f"apparmor_parser -r {persisted}" in _calls(tmp_path)
    assert _run(env, "--check").returncode == 0
    # Idempotent: a second run loads nothing.
    before = _calls(tmp_path).count("apparmor_parser")
    assert _run(env).returncode == 0
    assert _calls(tmp_path).count("apparmor_parser") == before


def test_changed_profile_is_reinstalled(tmp_path: Path) -> None:
    env = _host(tmp_path, APPARMOR)
    assert _run(env).returncode == 0
    (tmp_path / "etc" / _NAME).write_text("stale profile from an older AW\n")
    assert _run(env, "--check").returncode == 1
    assert _run(env).returncode == 0
    assert (tmp_path / "etc" / _NAME).read_bytes() == _SHIPPED.read_bytes()


def test_host_without_apparmor_is_skipped(tmp_path: Path) -> None:
    env = _host(tmp_path, NO_APPARMOR)
    for args in ((), ("--check",)):
        result = _run(env, *args)
        assert result.returncode == 0, result.stderr
    assert "apparmor_parser" not in _calls(tmp_path)
    assert not (tmp_path / "etc" / _NAME).exists()


def test_non_linux_host_is_skipped_without_asking_docker(tmp_path: Path) -> None:
    env = {**_host(tmp_path, APPARMOR), "SYN_APPARMOR_OS": "Darwin"}
    assert _run(env).returncode == 0
    assert _calls(tmp_path) == ""


def test_failing_docker_info_is_an_error_not_no_apparmor(tmp_path: Path) -> None:
    env = _host(tmp_path, APPARMOR, docker_ok=False)
    result = _run(env)
    assert result.returncode == 1
    assert "docker info failed" in result.stderr
    assert "apparmor_parser" not in _calls(tmp_path)
