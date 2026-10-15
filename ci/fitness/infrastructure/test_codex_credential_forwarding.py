"""Every service that receives CODEX_AUTH_JSON also receives OPENAI_API_KEY (#1971).

Codex phases authenticate with ``CODEX_AUTH_JSON`` or, failing that,
``OPENAI_API_KEY``. Both are resolved inside the API process, so a compose file
that forwards one and not the other leaves the fallback inert on that
deployment, silently: the setting is documented, written in ``.env``, and
never reaches the process that reads it.

The setup CLI also vendors the published selfhost compose and detects support
for the key from its forwarding line, so the published file is pinned by name
as well as by the sweep.

Standard: ADR-062 (docs/adrs/ADR-062-architectural-fitness-function-standard.md)
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.architecture]

_ROOT: Final = Path(__file__).resolve().parents[3]
_DOCKER: Final = _ROOT / "docker"
_PUBLISHED: Final = _DOCKER / "docker-compose.syntropic137.yaml"

_AUTH_JSON: Final = "CODEX_AUTH_JSON"
_API_KEY: Final = "OPENAI_API_KEY"


def _environment_names(environment: object) -> frozenset[str]:
    """Variable names in a compose ``environment:`` block, map or list form."""
    if isinstance(environment, dict):
        return frozenset(str(name) for name in environment)
    if isinstance(environment, list):
        return frozenset(str(entry).split("=", 1)[0] for entry in environment)
    return frozenset()


def _services_forwarding(compose_yaml: str, name: str) -> frozenset[str]:
    """Names of the services whose environment forwards ``name``."""
    parsed: object = yaml.safe_load(compose_yaml)
    if not isinstance(parsed, dict):
        return frozenset()
    services: object = parsed.get("services")
    if not isinstance(services, dict):
        return frozenset()
    found: set[str] = set()
    for service_name, service in services.items():
        if isinstance(service, dict) and name in _environment_names(service.get("environment")):
            found.add(str(service_name))
    return frozenset(found)


def _compose_files() -> list[Path]:
    return sorted(_DOCKER.rglob("*.yaml"))


def _files_forwarding_auth_json() -> list[Path]:
    return [p for p in _compose_files() if _services_forwarding(p.read_text(), _AUTH_JSON)]


def test_the_sweep_is_not_vacuous() -> None:
    """A glob that matched nothing would pass every check below."""
    files = _files_forwarding_auth_json()
    assert _PUBLISHED in files
    assert len(files) >= 2


@pytest.mark.parametrize(
    "path", _files_forwarding_auth_json(), ids=lambda p: str(p.relative_to(_ROOT))
)
def test_every_codex_auth_json_service_also_forwards_the_api_key(path: Path) -> None:
    text = path.read_text()
    missing = _services_forwarding(text, _AUTH_JSON) - _services_forwarding(text, _API_KEY)
    assert not missing, (
        f"{path.relative_to(_ROOT)}: services {sorted(missing)} forward {_AUTH_JSON} "
        f"but not {_API_KEY}, so the codex API-key fallback is inert there (#1971)"
    )


def test_the_check_can_fail() -> None:
    """The comparison flags a service that forwards only the auth file."""
    only_auth_json = f"services:\n  api:\n    environment:\n      - {_AUTH_JSON}=x\n"
    both = f"services:\n  api:\n    environment:\n      {_AUTH_JSON}: x\n      {_API_KEY}: y\n"
    assert _services_forwarding(only_auth_json, _AUTH_JSON) == {"api"}
    assert _services_forwarding(only_auth_json, _API_KEY) == frozenset()
    assert _services_forwarding(both, _API_KEY) == {"api"}
