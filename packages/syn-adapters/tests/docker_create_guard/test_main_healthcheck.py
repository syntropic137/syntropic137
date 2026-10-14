"""``python -m syn_adapters.docker_create_guard --healthcheck`` is the compose healthcheck."""

from __future__ import annotations

import socket
import subprocess
import sys

import pytest

from syn_adapters.docker_create_guard.__main__ import healthcheck, main

pytestmark = pytest.mark.unit


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_healthy_when_the_port_accepts_connections() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = int(listener.getsockname()[1])
        assert healthcheck(port)


def test_unhealthy_when_nothing_listens() -> None:
    assert not healthcheck(_free_port(), timeout=0.5)


def test_the_flag_exits_without_serving(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_DOCKER_CREATE_GUARD_PORT", str(_free_port()))
    with pytest.raises(SystemExit) as exited:
        main(["--healthcheck"])
    assert exited.value.code == 1


def _run_module(port: int) -> subprocess.CompletedProcess[bytes]:
    """The exact argv compose runs, so a renamed flag or module fails here, not in a deploy."""
    return subprocess.run(
        [sys.executable, "-m", "syn_adapters.docker_create_guard", "--healthcheck"],
        env={"SYN_DOCKER_CREATE_GUARD_PORT": str(port), "PATH": ""},
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_compose_spelling_exits_0_when_the_guard_listens() -> None:
    """Exit 0 proves the module imported and ran; a crash could only ever give 1."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = _run_module(int(listener.getsockname()[1]))
    assert result.returncode == 0, result.stderr


def test_compose_spelling_exits_1_when_nothing_listens() -> None:
    result = _run_module(_free_port())
    assert result.returncode == 1, result.stderr
    assert b"Traceback" not in result.stderr
