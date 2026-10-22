"""``DockerDeadHostReaper.scope()`` is the ``docker info`` engine ID (ADR-072 D13 Reap Scope).

Derived, never configured: an empty ID refuses rather than returning a scope
that would never equal another, or worse, one that equals every other.
"""

from __future__ import annotations

import subprocess

import pytest

from syn_api.services import dead_host_reaper
from syn_api.services.dead_host_reaper import DockerDeadHostReaper, ReapScopeUnknown

pytestmark = pytest.mark.unit


def _docker_info(stdout: str, returncode: int = 0) -> object:
    def run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ["docker", "info", "--format", "{{.ID}}"]
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="boom")

    return run


def test_scope_is_the_engine_id_and_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = _docker_info("ABCD:EFGH:1234\n")

    def counted(args: list[str], **kwargs: object) -> object:
        calls.append(args[1])
        return real(args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(dead_host_reaper.subprocess, "run", counted)
    reaper = DockerDeadHostReaper()
    assert reaper.scope() == "ABCD:EFGH:1234"
    assert reaper.scope() == "ABCD:EFGH:1234"
    assert calls == ["info"]


@pytest.mark.parametrize(("stdout", "returncode"), [("\n", 0), ("", 1), ("ID-but-failed", 1)])
def test_an_empty_or_failed_engine_id_raises(
    monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int
) -> None:
    monkeypatch.setattr(dead_host_reaper.subprocess, "run", _docker_info(stdout, returncode))
    with pytest.raises(ReapScopeUnknown):
        DockerDeadHostReaper().scope()


def test_an_unreachable_docker_cli_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(dead_host_reaper.subprocess, "run", missing)
    with pytest.raises(ReapScopeUnknown):
        DockerDeadHostReaper().scope()


def test_provider_and_isolation_are_what_docker_runs() -> None:
    reaper = DockerDeadHostReaper()
    assert (reaper.provider(), int(reaper.isolation())) == ("docker", 10)
