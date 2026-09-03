#!/usr/bin/env python3
"""Every documented setting must reach the API container, or say why it doesn't.

WHY THIS EXISTS. On a selfhost box `SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES=true`
was added to `~/.syntropic137/.env` and the API restarted. Nothing changed:
provisioning still refused the image the switch exists to allow.
`docker exec syn137-api env | grep SYN_IMAGE_VERIFY` printed nothing. Compose
injects a variable into a container only if the service NAMES it, and no
compose file named any `SYN_IMAGE_VERIFY_*` key, so the setting never left the
host. (#1101)

WHY IT WAS INVISIBLE. `.env.example` is generated from the Settings classes
(ADR-004), so every setting appears there and looks available. The compose
`environment:` block was maintained by hand. Two lists, maintained
independently, and nothing compared them - so an operator could set a
documented security switch, restart, get no error, and get the old behaviour.
On a security setting that is worse than a crash.

WHAT THIS ASSERTS. For every deployment stack an operator configures through
`.env`, each name in `.env.example` must reach the `api` service. A stack
satisfies that in one of two ways: it forwards the operator's whole `.env` via
`env_file:` (dev, ondemand), or it names the variable in `environment:`
(selfhost, which has no `env_file` and is where the bug was). The only third
option is an entry in `HOST_ONLY` below, which cannot be added without a
reason because the reason is a constructor argument.

Absence is never an option. That is the whole point: absence is what the
operator could not see.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_env_example import generate_env_example  # noqa: E402
from scripts.generate_published_compose import env_to_dict, generate  # noqa: E402

DOCKER_DIR: Final = PROJECT_ROOT / "docker"
BASE_COMPOSE: Final = DOCKER_DIR / "docker-compose.yaml"

#: The service that runs the process which reads the Settings classes.
API_SERVICE: Final = "api"

#: `env_file:` entries that name the operator's own `.env` - the same file
#: `.env.example` is copied to. A service with one of these forwards every
#: variable in it, so no per-name list exists there to drift.
OPERATOR_ENV_FILES: Final = frozenset({".env", "../.env"})


@dataclass(frozen=True)
class HostOnly:
    """A documented setting that deliberately never reaches the container.

    The reason is required, not optional. #1101 asked for "an entry in the
    exclusion list with a reason, not an absence", and a reason nobody had to
    supply is the absence wearing a different hat.
    """

    name: str
    reason: str


#: Settings the API container is deliberately NOT given. Each reason names the
#: code that makes it true, so a reviewer can check it rather than trust it.
HOST_ONLY: Final[tuple[HostOnly, ...]] = (
    HostOnly(
        "DEV__API_URL",
        "Points HOST-side tooling at the API (scripts/replay_webhooks.py, the "
        "seed scripts, E2E). The API never calls itself, and the default "
        "http://localhost:9137 would be wrong inside the container anyway.",
    ),
    HostOnly(
        "DEV__SMEE_URL",
        "Read by scripts/manage_webhook_url.py and `just dev` on the host to "
        "start a smee.io proxy. No container process reads it.",
    ),
    HostOnly(
        "SYN_GITHUB_PRIVATE_KEY",
        "The published selfhost stack delivers the PEM as a Docker file secret "
        "instead - generate_published_compose._apply_api_overrides drops this "
        "env var and sets SYN_GITHUB_APP_PRIVATE_KEY_FILE, deliberately, so "
        "the key never sits in the container environment.",
    ),
)


@dataclass(frozen=True)
class ApiEnvironment:
    """How one deployment stack builds the API container's environment.

    Callers ask `forwards(name)` and never learn which of the two mechanisms
    answered - that is the point. Adding `env_file:` to a stack, or naming one
    more variable in it, changes nothing here.
    """

    stack: str
    named: frozenset[str]
    forwards_operator_env_file: bool

    def forwards(self, setting: str) -> bool:
        return self.forwards_operator_env_file or setting in self.named

    @classmethod
    def of(cls, stack: str, api_service: Mapping[str, object]) -> ApiEnvironment:
        return cls(
            stack=stack,
            named=frozenset(_named_variables(api_service)),
            forwards_operator_env_file=_has_operator_env_file(api_service),
        )

    def merged_with(self, other: ApiEnvironment) -> ApiEnvironment:
        """Base compose merged with one overlay, as Compose would merge them."""
        return ApiEnvironment(
            stack=other.stack,
            named=self.named | other.named,
            forwards_operator_env_file=(
                self.forwards_operator_env_file or other.forwards_operator_env_file
            ),
        )


def _named_variables(api_service: Mapping[str, object]) -> frozenset[str]:
    raw = api_service.get("environment")
    if not isinstance(raw, dict | list):
        return frozenset()
    return frozenset(env_to_dict(raw))


def _has_operator_env_file(api_service: Mapping[str, object]) -> bool:
    raw = api_service.get("env_file")
    if isinstance(raw, str):
        return raw in OPERATOR_ENV_FILES
    if isinstance(raw, list):
        return any(str(entry) in OPERATOR_ENV_FILES for entry in raw)
    return False


def documented_settings() -> frozenset[str]:
    """Every name `.env.example` offers an operator.

    Taken from the generator rather than the committed file, so this answer
    does not depend on whether anyone has run `just gen-env` yet.
    """
    return frozenset(
        line.partition("=")[0].strip()
        for line in generate_env_example().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def api_service_of(compose_file: Path) -> Mapping[str, object]:
    """The `api` service as one compose file declares it (may be empty)."""
    document = yaml.safe_load(compose_file.read_text())
    if not isinstance(document, dict):
        return {}
    services = document.get("services")
    if not isinstance(services, dict):
        return {}
    api = services.get(API_SERVICE)
    return api if isinstance(api, dict) else {}


def deployment_stacks() -> tuple[ApiEnvironment, ...]:
    """Every stack an operator configures through a `.env` file.

    `docker-compose.test.yaml` is absent on purpose: it defines no `api`
    service and nobody configures it from `.env`.
    """
    base = ApiEnvironment.of("base", api_service_of(BASE_COMPOSE))
    return (
        # What self-hosters actually download and run. Built the same way
        # `just gen-compose` builds it, so a fix to either source file counts
        # immediately and this cannot disagree with `just check-compose`.
        ApiEnvironment.of("selfhost (published)", _published_api_service()),
        base.merged_with(
            ApiEnvironment.of("dev", api_service_of(DOCKER_DIR / "docker-compose.dev.yaml"))
        ),
        base.merged_with(
            ApiEnvironment.of(
                "ondemand", api_service_of(DOCKER_DIR / "docker-compose.ondemand.yaml")
            )
        ),
    )


def _published_api_service() -> Mapping[str, object]:
    services = generate().get("services", {})
    api = services.get(API_SERVICE) if isinstance(services, dict) else None
    return api if isinstance(api, dict) else {}


def unforwarded(env: ApiEnvironment, documented: frozenset[str]) -> tuple[str, ...]:
    """Documented settings this stack silently drops."""
    excused = {entry.name for entry in HOST_ONLY}
    return tuple(sorted(n for n in documented if n not in excused and not env.forwards(n)))


def stale_host_only(documented: frozenset[str]) -> tuple[str, ...]:
    """HOST_ONLY entries that are no longer settings at all.

    An exclusion list nobody prunes stops describing reality, and then quietly
    excuses a name that comes back later meaning something else.
    """
    return tuple(sorted(entry.name for entry in HOST_ONLY if entry.name not in documented))


def main() -> None:
    documented = documented_settings()
    failed = False

    for env in deployment_stacks():
        missing = unforwarded(env, documented)
        if not missing:
            how = "env_file" if env.forwards_operator_env_file else f"{len(env.named)} named"
            print(f"  OK   {env.stack}: all {len(documented)} settings reach the API ({how})")
            continue
        failed = True
        print(f"  FAIL {env.stack}: {len(missing)} documented settings never reach the API")
        for name in missing:
            print(f"         {name}")

    stale = stale_host_only(documented)
    if stale:
        failed = True
        print(f"  FAIL HOST_ONLY names {len(stale)} settings that no longer exist")
        for name in stale:
            print(f"         {name}")

    if failed:
        print()
        print("An operator can set these in .env, restart, and get no error and no effect.")
        print("Either name them in the api service's environment: block in")
        print("docker/docker-compose.yaml (then run `just gen-compose`), or add a")
        print("HOST_ONLY entry in scripts/check_env_forwarding.py with a reason.")
        sys.exit(1)

    print(f"OK: {len(documented)} documented settings, {len(HOST_ONLY)} host-only with reasons")


if __name__ == "__main__":
    main()
