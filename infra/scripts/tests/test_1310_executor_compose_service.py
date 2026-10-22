"""Both selfhost composes define an executor from the api image (#1310 1.6, ADR-072 D1),
behind the `run-queue` compose profile so a default install starts none.

The handwritten overlay is the input and the published file is generated from
it, so each is read: a selfhost stack and a downloaded one must agree, and a
stale regeneration fails here too.

The executor's environment mirrors api's by hand (a claimed run needs exactly
what an in-process one does), so the mirror is what is asserted: every key api
receives, the executor receives with the same value, except the role.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from syn_shared.settings.execution import ProcessRole

pytestmark = pytest.mark.unit

_DOCKER = Path(__file__).resolve().parents[3] / "docker"
_SELFHOST = _DOCKER / "docker-compose.selfhost.yaml"
_PUBLISHED = _DOCKER / "docker-compose.syntropic137.yaml"
_ROLE = "SYN_EXECUTION_PROCESS_ROLE"
_COMPOSES = pytest.mark.parametrize("compose", [_SELFHOST, _PUBLISHED], ids=lambda p: p.name)


def _services(compose: Path) -> dict[str, dict[str, object]]:
    return yaml.safe_load(compose.read_text())["services"]


def _env(service: dict[str, object]) -> dict[str, str | None]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): None if v is None else str(v) for k, v in env.items()}
    assert isinstance(env, list)
    pairs = (str(item).partition("=") for item in env)
    return {k: v if sep else None for k, sep, v in pairs}


@_COMPOSES
def test_the_roles_are_pinned_per_service(compose: Path) -> None:
    services = _services(compose)
    assert _env(services["api"])[_ROLE] == ProcessRole.API
    assert _env(services["executor"])[_ROLE] == ProcessRole.EXECUTOR


@_COMPOSES
def test_the_executor_receives_everything_api_does(compose: Path) -> None:
    services = _services(compose)
    api = {k: v for k, v in _env(services["api"]).items() if k != _ROLE}
    executor = _env(services["executor"])
    missing = {k: v for k, v in api.items() if executor.get(k, "<absent>") != v}
    assert not missing, f"executor environment drifted from api's: {sorted(missing)}"


@_COMPOSES
def test_the_executor_can_run_workspaces(compose: Path) -> None:
    """While the flag is off api keeps these too: executions still run there.

    api's DOCKER_HOST comes from docker-compose.yaml, so only the merged
    (published) file can show it; the overlay's executor has no base.
    """
    services = _services(compose)
    for name in ("api", "executor") if compose == _PUBLISHED else ("executor",):
        service = services[name]
        assert _env(service)["DOCKER_HOST"] == "tcp://docker-socket-proxy:2375", name
        assert "docker-proxy" in (service.get("networks") or []), name
        volumes = [str(v) for v in service.get("volumes") or []]
        assert any(v.endswith("workspaces:/workspaces") for v in volumes), name


@_COMPOSES
def test_the_executor_has_its_own_limits_and_grace(compose: Path) -> None:
    executor = _services(compose)["executor"]
    limits = executor["deploy"]["resources"]["limits"]  # type: ignore[index]
    assert str(limits["memory"]).startswith("${EXECUTOR_MEMORY_LIMIT:-")
    assert str(limits["cpus"]).startswith("${EXECUTOR_CPU_LIMIT:-")
    # api's comes from docker-compose.yaml, so it is read from the merged file.
    assert executor["stop_grace_period"] == _services(_PUBLISHED)["api"]["stop_grace_period"]


def test_the_published_executor_is_the_api_image() -> None:
    services = _services(_PUBLISHED)
    assert services["executor"]["image"] == services["api"]["image"]
    assert "build" not in services["executor"]
    assert "github_app_private_key" in services["executor"]["secrets"]  # type: ignore[operator]


def test_a_bare_list_entry_stays_a_passthrough() -> None:
    """``- KEY`` in list form passes the host variable through, like ``KEY:``.

    Rendering it as ``""`` would turn "unset" into "set to empty", the #954
    false pass, for any service whose overlay uses list form (the executor's).
    """
    executor = _env(_services(_PUBLISHED)["executor"])
    assert "SYN_WORKSPACE_DOCKER_IMAGE" in executor
    assert executor["SYN_WORKSPACE_DOCKER_IMAGE"] is None


@_COMPOSES
def test_the_executor_starts_only_under_the_run_queue_profile(compose: Path) -> None:
    """A default install runs no executor (#1310 1.6): an idle container holding
    docker-proxy access, /workspaces and every credential is surface for
    nothing. ``COMPOSE_PROFILES=run-queue`` is what starts it."""
    services = _services(compose)
    assert services["executor"].get("profiles") == ["run-queue"]
    # api is never profiled: it is the platform, not an opt-in.
    assert "profiles" not in services["api"]


def test_enabling_the_run_queue_documents_the_profile() -> None:
    """The flag alone admits runs nothing would claim; the operator reading
    .env.example must learn the profile from the same place."""
    example = (_DOCKER.parent / ".env.example").read_text()
    flag = example.index("SYN_EXECUTION_RUN_QUEUE_ENABLED=")
    comment = example[example.rindex("\n\n", 0, flag) : flag]
    assert "COMPOSE_PROFILES=run-queue" in comment
