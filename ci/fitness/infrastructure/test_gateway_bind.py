"""The published stack must let an operator bind the gateway off loopback (#1017).

Asserted through `docker compose config` rather than by reading the YAML,
because the thing that has to honour `${SYN_GATEWAY_BIND:-127.0.0.1}` is
docker's interpolation, not a regex of mine. A test that greps the compose file
for the variable would pass on a file docker rejects, and would have passed just
as happily on the hand-edit that `setup update` overwrote.

`preflight` already requires docker (check-default-workspace-image pulls and
runs the pinned image), so these do not skip when it is absent: a check that
skips is a check that cannot fail.

Scope: this file is about docker's interpolation of the PUBLISHED file, and
nothing else. Two neighbouring properties that it cannot see, and which would
otherwise have no owner, are covered where they can actually be exercised:

* that the source overlay and the published file agree, and that the address is
  handed to the container at all, is in
  ``infra/scripts/tests/test_gateway_auth_binding.py`` -- it reads the compose
  YAML rather than ``docker compose config``, because it asserts the two
  *expressions* match, which interpolation destroys by resolving them;
* that binding off loopback demands the authenticated path is in the same file,
  by running the gateway entrypoint.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

_ROOT = Path(__file__).resolve().parents[3]
_PUBLISHED = _ROOT / "docker" / "docker-compose.syntropic137.yaml"

#: TEST-NET-3 (RFC 5737). Cannot be a default, a LAN address, or anything the
#: generator could produce on its own, so seeing it proves interpolation ran.
_SENTINEL_ADDRESS = "203.0.113.7"


def _gateway_host_ip(env: dict[str, str] | None = None) -> str:
    """The address docker would actually bind the gateway to."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(_PUBLISHED),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home()), **(env or {})},
        cwd=_PUBLISHED.parent,
        check=False,
    )
    assert result.returncode == 0, f"docker compose config failed:\n{result.stderr}"

    config = json.loads(result.stdout)
    ports = config["services"]["gateway"]["ports"]
    # `str(p.get("published"))` was the predicate here and filtered nothing:
    # str(None) is "None", which is truthy. Only `target` ever narrowed the list.
    published = [p for p in ports if p.get("published") is not None and p.get("target") == 80]
    assert len(published) == 1, f"expected exactly one gateway port mapping, got {ports}"
    return str(published[0]["host_ip"])


def test_the_gateway_binds_to_loopback_when_the_operator_sets_nothing() -> None:
    """The default must not change: an unset variable stays host-only."""
    assert _gateway_host_ip() == "127.0.0.1"


def test_an_operator_can_bind_the_gateway_to_another_address() -> None:
    """The selfhost case: reach the API from a second machine.

    Before #1017 this was impossible without hand-editing the generated file,
    which the next `setup update` silently reverted.
    """
    assert _gateway_host_ip({"SYN_GATEWAY_BIND": _SENTINEL_ADDRESS}) == _SENTINEL_ADDRESS


def test_the_port_stays_independently_configurable() -> None:
    """Binding and port are separate knobs; setting one must not pin the other."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(_PUBLISHED), "config", "--format", "json"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(Path.home()),
            "SYN_GATEWAY_BIND": _SENTINEL_ADDRESS,
            "SYN_GATEWAY_PORT": "18137",
        },
        cwd=_PUBLISHED.parent,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    gateway = json.loads(result.stdout)["services"]["gateway"]["ports"][0]

    assert gateway["host_ip"] == _SENTINEL_ADDRESS
    assert str(gateway["published"]) == "18137"
