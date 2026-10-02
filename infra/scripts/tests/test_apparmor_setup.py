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


def _loads(tmp_path: Path) -> int:
    """Real parser invocations (the sudo stand-in logs its own line too)."""
    return sum(line.startswith("apparmor_parser -r") for line in _calls(tmp_path).splitlines())


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
    check = _run(env, "--check")
    assert check.returncode == 0
    assert "cannot verify the LOADED rules" in check.stdout
    # A second run is harmless: nothing to install, but the profile is replaced
    # again, because loaded rules cannot be compared to the file.
    before = _loads(tmp_path)
    installs = _calls(tmp_path).count("sudo install")
    assert _run(env).returncode == 0
    assert _loads(tmp_path) == before + 1
    assert _calls(tmp_path).count("sudo install") == installs


def test_preloaded_name_with_current_file_is_still_reloaded(tmp_path: Path) -> None:
    """The name is loaded and the file matches, but the loaded rules may be an
    older profile (e.g. the file was replaced after the last load): reload."""
    env = _host(tmp_path, APPARMOR)
    (tmp_path / "policy" / "p0").mkdir()
    (tmp_path / "policy" / "p0" / "name").write_text(f"{_NAME}\n")
    persisted = tmp_path / "etc" / _NAME
    persisted.write_bytes(_SHIPPED.read_bytes())
    assert _run(env).returncode == 0
    assert f"apparmor_parser -r {persisted}" in _calls(tmp_path)
    assert "sudo install" not in _calls(tmp_path)


def test_preloaded_name_with_changed_file_is_reinstalled_and_reloaded(tmp_path: Path) -> None:
    env = _host(tmp_path, APPARMOR)
    (tmp_path / "policy" / "p0").mkdir()
    (tmp_path / "policy" / "p0" / "name").write_text(f"{_NAME}\n")
    persisted = tmp_path / "etc" / _NAME
    persisted.write_text("profile agentic-codex-sandbox { # locally edited\n}\n")
    assert _run(env, "--check").returncode == 1
    assert _run(env).returncode == 0
    assert persisted.read_bytes() == _SHIPPED.read_bytes()
    calls = _calls(tmp_path)
    assert calls.index("sudo install") < calls.index(f"apparmor_parser -r {persisted}")


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


# --- The upgrade path: `just selfhost-update` (#1398) ------------------------

_UPDATE = _REPO / "infra" / "scripts" / "selfhost-update-host.sh"


def _update(env: dict[str, str], env_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_UPDATE), str(env_file)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO,
    )


def _preload(tmp_path: Path) -> Path:
    """A host upgraded from an earlier release: name loaded, file persisted."""
    (tmp_path / "policy" / "p0").mkdir()
    (tmp_path / "policy" / "p0" / "name").write_text(f"{_NAME}\n")
    persisted = tmp_path / "etc" / _NAME
    persisted.write_bytes(_SHIPPED.read_bytes())
    return persisted


def test_update_reloads_a_preloaded_profile_and_migrates_the_old_default(tmp_path: Path) -> None:
    from syn_shared.settings.workspace_images import (
        DEFAULT_WORKSPACE_IMAGE,
        PREVIOUS_DEFAULT_WORKSPACE_IMAGES,
    )

    env = _host(tmp_path, APPARMOR)
    persisted = _preload(tmp_path)
    old = PREVIOUS_DEFAULT_WORKSPACE_IMAGES[-1]
    env_file = tmp_path / "selfhost.env"
    env_file.write_text(f"A=1\nSYN_WORKSPACE_DOCKER_IMAGE='{old}'\n")
    result = _update(env, env_file)
    assert result.returncode == 0, result.stderr
    assert _loads(tmp_path) == 1
    assert f"apparmor_parser -r {persisted}" in _calls(tmp_path)
    assert env_file.read_text() == f"A=1\nSYN_WORKSPACE_DOCKER_IMAGE='{DEFAULT_WORKSPACE_IMAGE}'\n"
    assert old in result.stdout and DEFAULT_WORKSPACE_IMAGE in result.stdout


def test_update_leaves_a_custom_image_alone(tmp_path: Path) -> None:
    env = _host(tmp_path, NO_APPARMOR)
    custom = "ghcr.io/example/my-omni@sha256:" + "cd" * 32
    env_file = tmp_path / "selfhost.env"
    env_file.write_text(f"SYN_WORKSPACE_DOCKER_IMAGE='{custom}'\n")
    result = _update(env, env_file)
    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == f"SYN_WORKSPACE_DOCKER_IMAGE='{custom}'\n"
    assert "custom image; left unchanged" in result.stdout
    assert "apparmor_parser" not in _calls(tmp_path)


def test_update_stops_before_restart_when_the_profile_cannot_load(tmp_path: Path) -> None:
    env = _host(tmp_path, APPARMOR)
    _stub(tmp_path / "bin", "fakesudo", "exit 1")  # sudo refused / no tty
    env_file = tmp_path / "selfhost.env"
    env_file.write_text("")
    result = _update(env, env_file)
    assert result.returncode == 1
    assert "needs root" in result.stderr
    assert "Update stopped before restarting services" in result.stderr


def test_selfhost_update_runs_host_steps_between_submodules_and_compose() -> None:
    justfile = (_REPO / "justfile").read_text()
    recipe = justfile[justfile.index("\nselfhost-update *args:") :]
    recipe = recipe[: recipe.index("\n\n# ")]
    submodules = recipe.index("git submodule update")
    host = recipe.index("infra/scripts/selfhost-update-host.sh")
    reexport = recipe.index("source infra/scripts/selfhost-env.sh", host)
    compose = recipe.index("$COMPOSE up")
    assert submodules < host < reexport < compose
