"""The guard's compose healthcheck: ``healthcheck.py``, run by path (stdlib only)."""

from __future__ import annotations

import ast
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from syn_adapters.docker_create_guard import healthcheck as healthcheck_module
from syn_adapters.docker_create_guard.__main__ import main
from syn_adapters.docker_create_guard.healthcheck import healthcheck

pytestmark = pytest.mark.unit

_SCRIPT = Path(healthcheck_module.__file__)
_REPO = Path(__file__).resolve().parents[4]
# The syn-api image copies packages/syn-adapters/ to /app/packages/syn-adapters/.
_IMAGE_ROOT = "/app"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_script(port: int) -> subprocess.CompletedProcess[bytes]:
    """The way compose runs it: by path, isolated, nothing on the path but stdlib."""
    return subprocess.run(
        [sys.executable, "-I", str(_SCRIPT)],
        env={"SYN_DOCKER_CREATE_GUARD_PORT": str(port)},
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_healthy_when_the_port_accepts_connections() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert healthcheck(int(listener.getsockname()[1]))


def test_unhealthy_when_nothing_listens() -> None:
    assert not healthcheck(_free_port(), timeout=0.5)


def test_script_exits_0_when_the_guard_listens() -> None:
    """Exit 0 proves the script ran; a crash could only ever give 1."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = _run_script(int(listener.getsockname()[1]))
    assert result.returncode == 0, result.stderr


def test_script_exits_1_when_nothing_listens() -> None:
    result = _run_script(_free_port())
    assert result.returncode == 1, result.stderr
    assert b"Traceback" not in result.stderr


def test_script_imports_the_standard_library_only() -> None:
    """Importing syn_adapters per probe took >20 s under the guard's CPU limit."""
    tree = ast.parse(_SCRIPT.read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


def test_compose_probes_the_script_at_its_image_path() -> None:
    guard = yaml.safe_load((_REPO / "docker" / "docker-compose.yaml").read_text())["services"][
        "docker-create-guard"
    ]
    probe = guard["healthcheck"]["test"]
    assert probe[:3] == ["CMD", "python", "-I"]
    relative = _SCRIPT.relative_to(_REPO)
    assert probe[3] == f"{_IMAGE_ROOT}/{relative.as_posix()}"
    dockerfile = (_REPO / "infra/docker/images/syn-api/Dockerfile").read_text()
    assert f"WORKDIR {_IMAGE_ROOT}\n" in dockerfile
    assert "COPY packages/syn-adapters/ ./packages/syn-adapters/" in dockerfile


def test_the_module_flag_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_DOCKER_CREATE_GUARD_PORT", str(_free_port()))
    with pytest.raises(SystemExit) as exited:
        main(["--healthcheck"])
    assert exited.value.code == 1
