"""The API and event store memory defaults must reach the containers (#1552, #1553).

Both were OOM-killed at the 512m compose default: the API at ~443MB anon RSS
with 8 runs, taking every in-flight execution with it (#1552), and the event
store in a restart loop at ~520MB while serving a projection rebuild (#1553).
The default is written in two places nothing ties together: the InfraSettings
field, which documents it in ``infra/.env.example``, and the ``${VAR:-default}``
fallback in the selfhost overlay, which is what docker actually applies when the
variable is unset. Raising one and not the other ships the documented value
while the stack keeps running on the old one.

Read from the PUBLISHED file, because that is what a self-hoster downloads and
runs; it is generated from the selfhost overlay, so a stale regeneration fails
here too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from syn_shared.settings.infra import InfraSettings

pytestmark = pytest.mark.unit

_PUBLISHED = Path(__file__).resolve().parents[3] / "docker" / "docker-compose.syntropic137.yaml"

_INTERPOLATION = re.compile(r"^\$\{(?P<name>[A-Z_]+):-(?P<default>[^}]*)\}$")

#: Where the event store settled under 2g in #1553, in MiB: the only stable
#: figure either issue reports.
_EVENT_STORE_STABLE_MIB = 749


def _memory_default(service: str, variable: str) -> str:
    services = yaml.safe_load(_PUBLISHED.read_text())["services"]
    expression = services[service]["deploy"]["resources"]["limits"]["memory"]
    match = _INTERPOLATION.match(str(expression))
    assert match is not None, f"expected ${{{variable}:-...}}, got {expression!r}"
    assert match["name"] == variable
    return match["default"]


def _mib(limit: str) -> int:
    """Docker's memory notation (``512m``, ``2g``) in MiB."""
    match = re.fullmatch(r"(\d+)([mg])", limit)
    assert match is not None, f"unsupported memory limit {limit!r}"
    return int(match[1]) * (1024 if match[2] == "g" else 1)


@pytest.mark.parametrize(
    ("service", "variable"),
    [("api", "API_MEMORY_LIMIT"), ("event-store", "EVENT_STORE_MEMORY_LIMIT")],
)
def test_memory_default_follows_settings(service: str, variable: str) -> None:
    published = _memory_default(service, variable)

    assert published == InfraSettings.model_fields[variable.lower()].default


@pytest.mark.parametrize(
    ("service", "variable", "oom_killed_at_mib"),
    [
        ("api", "API_MEMORY_LIMIT", 443),  # #1552: anon RSS with 8 runs
        ("event-store", "EVENT_STORE_MEMORY_LIMIT", 520),  # #1553: under replay
    ],
)
def test_memory_default_clears_the_measured_oom(
    service: str, variable: str, oom_killed_at_mib: int
) -> None:
    """The shipped default must sit well above where the service was killed."""
    limit_mib = _mib(_memory_default(service, variable))

    assert limit_mib >= 2 * oom_killed_at_mib


def test_event_store_default_keeps_headroom_over_its_stable_footprint() -> None:
    """749MB was measured on a 46k-event store and grows with stream length.

    At 1g it would already be at 73% of the limit; require the measured figure
    to stay under half, since nothing yet bounds the replay's memory.
    """
    limit_mib = _mib(_memory_default("event-store", "EVENT_STORE_MEMORY_LIMIT"))

    assert limit_mib / 2 > _EVENT_STORE_STABLE_MIB
