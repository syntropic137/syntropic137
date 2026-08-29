"""SYN_WORKSPACE_DOCKER_IMAGE must reach the api container (#954).

The documented image hot-swap was INERT on a real deployment: the variable was
absent from the generated compose env map, so setting it in `.env` never reached
the container. The API silently kept its `PINNED_DIGESTS` default while an
operator believed they had swapped images -- so a validation run "against the new
image" actually ran against the old one, with nothing anywhere saying so.

That is a false pass, which is worse than an outage: it produces confident wrong
evidence.

Scope note: overlays inherit the api environment from `docker-compose.yaml`, so
only two artifacts need to carry the variable -- the base that defines it once,
and the generated file operators actually run. Asserting it in every overlay
would be three more places to drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"
_VAR = "SYN_WORKSPACE_DOCKER_IMAGE"

# The base defines the shared api environment; the published file is what a
# selfhost operator runs. Between them they cover every deployed path.
_MUST_CARRY = ("docker-compose.yaml", "docker-compose.syntropic137.yaml")


def _api_environment(path: Path) -> dict[str, str]:
    compose: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    api = (compose.get("services") or {}).get("api") or {}
    env = api.get("environment")
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    out: dict[str, str] = {}
    for entry in env or []:
        key, _, value = str(entry).partition("=")
        out[key] = value
    return out


@pytest.mark.parametrize("name", _MUST_CARRY)
def test_file_exists(name: str) -> None:
    """Negative control: a renamed compose file would make the assertions vacuous."""
    assert (_DOCKER_DIR / name).is_file(), f"{name} is missing; the invariant below is vacuous"


@pytest.mark.parametrize("name", _MUST_CARRY)
def test_api_passes_the_workspace_image_through(name: str) -> None:
    env = _api_environment(_DOCKER_DIR / name)
    assert env, f"{name}: api service has no environment map"
    assert _VAR in env, (
        f"{name}: api does not pass {_VAR} through, so the documented hot-swap "
        "is inert and a swapped image would be silently ignored"
    )


@pytest.mark.parametrize("name", _MUST_CARRY)
def test_passthrough_interpolates_rather_than_hardcoding_a_digest(name: str) -> None:
    """A baked digest would drift from PINNED_DIGESTS; it must interpolate."""
    value = _api_environment(_DOCKER_DIR / name)[_VAR]
    assert value.startswith("${") and _VAR in value, (
        f"{name}: expected an interpolation of {_VAR}, got {value!r}"
    )
