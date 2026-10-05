"""The control plane must out-rank the agent workspaces it dispatches (#1600).

With 9 runs on a 16-core host the API was capped at 0.5 CPU, Postgres at 1.0,
and every workspace at 2.0: load reached 21 and a /sessions read took 55 s. The
fix has two halves, and both have to reach the containers docker starts:

* the CPU limits of api and timescaledb default to InfraSettings' values, so
  what ``infra/.env.example`` documents is what an unset variable gets;
* api, timescaledb, event-store and gateway carry ``cpu_shares`` above
  Docker's default of 1024, which is what every workspace runs at, so under
  contention they win.

Read from the PUBLISHED file, because that is what a self-hoster downloads and
runs; it is generated from the selfhost overlay, so a stale regeneration fails
here too. The default inside each ``${VAR:-default}`` is compared with the
Settings field rather than with a literal, so the two cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from syn_shared.settings.infra import InfraSettings

pytestmark = pytest.mark.unit

_PUBLISHED = Path(__file__).resolve().parents[3] / "docker" / "docker-compose.syntropic137.yaml"

#: Docker's cpu_shares when none is set -- what every agent workspace runs at.
_DOCKER_DEFAULT_CPU_SHARES = 1024

_CONTROL_PLANE = ("api", "timescaledb", "event-store", "gateway")

_INTERPOLATION = re.compile(r"^\$\{(?P<name>[A-Z_]+):-(?P<default>[^}]*)\}$")


def _services() -> dict[str, dict[str, object]]:
    return yaml.safe_load(_PUBLISHED.read_text())["services"]


def _default_of(expression: object, variable: str) -> str:
    """The value docker uses for ``${variable:-default}`` when it is unset."""
    match = _INTERPOLATION.match(str(expression))
    assert match is not None, f"expected ${{{variable}:-...}}, got {expression!r}"
    assert match["name"] == variable
    return match["default"]


def _field_default(name: str) -> object:
    return InfraSettings.model_fields[name].default


@pytest.mark.parametrize("service", _CONTROL_PLANE)
def test_control_plane_outweighs_workspaces(service: str) -> None:
    shares = _default_of(_services()[service].get("cpu_shares"), "CONTROL_PLANE_CPU_SHARES")

    assert int(shares) == _field_default("control_plane_cpu_shares")
    assert int(shares) > _DOCKER_DEFAULT_CPU_SHARES


@pytest.mark.parametrize(
    ("service", "variable"),
    [("api", "API_CPU_LIMIT"), ("timescaledb", "POSTGRES_CPU_LIMIT")],
)
def test_cpu_limit_defaults_follow_settings(service: str, variable: str) -> None:
    limits = _services()[service]["deploy"]["resources"]["limits"]  # type: ignore[index]

    assert _default_of(limits["cpus"], variable) == _field_default(variable.lower())


def test_control_plane_is_not_capped_below_a_workspace() -> None:
    """A workspace gets 2 cores; the API and Postgres serve all of them."""
    workspace_cores = 2.0
    assert float(str(_field_default("api_cpu_limit"))) >= workspace_cores
    assert float(str(_field_default("postgres_cpu_limit"))) >= workspace_cores
