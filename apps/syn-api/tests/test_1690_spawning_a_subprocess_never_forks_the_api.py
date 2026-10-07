"""Spawning a subprocess never forks the API process (#1690).

The API shells out to `docker` all the time: agent streams, sidecars, and the
session-inventory recovery worker, which spawns several per recovery. Under
uvloop every one of those was a real ``fork()`` on the event-loop thread, and
the loop blocked until the child exec'd. Forking a ~330 MB, ~29-thread process
copies its page tables and interrupts every CPU its threads ran on. On the
loaded selfhost that took 22-157 ms per ``clone()`` and froze the whole API
for p50 ~200-330 ms per spawn, so dashboard reads that took 0.2 s idle took
0.5-2.8 s. The stdlib asyncio loop spawns through ``_posixsubprocess``, which
uses vfork: nothing is copied and the loop is back in milliseconds.

What this pins is the loop the shipped image actually runs, read from the
image itself, not a loop chosen in the test. It counts the interpreter's
fork hooks (``os.register_at_fork``) because that is the observable
difference: uvloop calls ``PyOS_BeforeFork`` around every spawn, and
``_posixsubprocess`` calls it only for a ``preexec_fn``, which nothing here
passes. A hook that fires means the loop took the fork path.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest
import uvicorn
import yaml

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_API_DOCKERFILE = _REPO / "infra" / "docker" / "images" / "syn-api" / "Dockerfile"
_COMPOSE_FILES = sorted((_REPO / "docker").glob("docker-compose*.yaml"))


def _image_env(dockerfile: Path) -> dict[str, str]:
    """``ENV NAME=value`` lines of the final stage, as the container sees them."""
    stages = re.split(r"(?m)^FROM\s", dockerfile.read_text())
    env: dict[str, str] = {}
    for match in re.finditer(r"(?m)^ENV\s+([A-Z_][A-Z0-9_]*)=(\S*)\s*$", stages[-1]):
        env[match.group(1)] = match.group(2).strip("\"'")
    return env


def _shipped_loop() -> str:
    """The ``--loop`` uvicorn resolves for the shipped image: its env, else the default."""
    return _image_env(_API_DOCKERFILE).get("UVICORN_LOOP", "auto")


def _forks_on_spawn(loop_name: str) -> int:
    """At-fork hooks fired while that loop spawns and reaps one child."""
    factory = uvicorn.Config("syn_api.main:app", loop=loop_name).get_loop_factory()
    assert factory is not None, f"uvicorn has no loop factory for {loop_name!r}"
    fired: list[int] = []
    # register_at_fork has no unregister; the list goes out of scope with the test.
    os.register_at_fork(before=lambda: fired.append(1))

    async def spawn() -> int:
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        return await proc.wait()

    with asyncio.Runner(loop_factory=factory) as runner:
        assert runner.run(spawn()) == 0
    return len(fired)


def test_the_shipped_loop_spawns_without_forking_the_api() -> None:
    loop_name = _shipped_loop()
    assert _forks_on_spawn(loop_name) == 0, (
        f"The API image runs uvicorn with --loop {loop_name!r}, which fork()s the whole "
        "API on every subprocess spawn and freezes the event loop for it (#1690). "
        "Set ENV UVICORN_LOOP=asyncio in the API Dockerfile."
    )


def test_the_hazard_is_real_under_uvloop() -> None:
    """The counter must see a fork when there is one, or the test above proves nothing."""
    pytest.importorskip("uvloop")
    assert _forks_on_spawn("uvloop") >= 1


def test_no_compose_file_overrides_the_api_loop() -> None:
    """A ``--loop`` on a compose command line would beat the image's env."""
    offenders: list[str] = []
    for compose in _COMPOSE_FILES:
        services = (yaml.safe_load(compose.read_text()) or {}).get("services") or {}
        for name, service in services.items():
            command = service.get("command") if isinstance(service, dict) else None
            text = " ".join(command) if isinstance(command, list) else str(command or "")
            if "syn_api.main:app" in text and "--loop" in text and "--loop asyncio" not in text:
                offenders.append(f"{compose.name}:{name}")
            environment = service.get("environment") if isinstance(service, dict) else None
            if isinstance(environment, dict):
                value = environment.get("UVICORN_LOOP")
                if value is not None and value != "asyncio":
                    offenders.append(f"{compose.name}:{name} UVICORN_LOOP={value}")
    assert not offenders, f"These override the API's event loop (#1690): {offenders}"
