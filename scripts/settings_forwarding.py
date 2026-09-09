#!/usr/bin/env python3
"""Which documented settings actually reach the API container, and why not.

`.env.example` is generated from the Settings classes (ADR-004), so EVERY
setting appears there and looks available. But a container only sees what the
compose file forwards, and that list was maintained by hand. The two drifted:
`SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES` was set on a selfhost, the API was
restarted, and nothing happened -- no error, no warning, just the old behaviour
(#1101). Seventy-six of the 103 documented settings were inert the same way.

This module owns the decision "does setting X reach the API process?" so that
it is made once, in code, instead of twice by hand:

  * `forwarding_block()` renders the compose entries that make a setting
    reachable. `python scripts/settings_forwarding.py` writes them into
    docker/docker-compose.yaml between the markers below; `--check` fails if
    they are stale. Every stack layers on that base, so one block covers all.
  * `NOT_FORWARDED` records the settings that genuinely cannot be forwarded,
    each with the reason. Being ignored is allowed; being ignored silently is
    not, so the reason is also emitted into `.env.example` beside the setting.
  * `report()` proves the two agree, and is asserted by
    ci/fitness/infrastructure/test_compose_env_forwarding.py.

The setting list is read from `.env.example` rather than re-derived from the
Settings classes on purpose: `just check-env-example` already pins that file to
the classes, so parsing it adds no second place for the class list to drift.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
BASE_COMPOSE = PROJECT_ROOT / "docker" / "docker-compose.yaml"

# The published file is what a self-hoster downloads and runs, and it is the
# deployment #1101 was reported against. It is generated from
# docker-compose.yaml + docker-compose.selfhost.yaml, so checking it covers both
# without re-implementing the merge here.
PUBLISHED_COMPOSE = PROJECT_ROOT / "docker" / "docker-compose.syntropic137.yaml"

BEGIN_MARKER = "# --- BEGIN GENERATED: settings forwarded from .env (just gen-compose) ---"
END_MARKER = "# --- END GENERATED ---"

_ENV_INDENT = " " * 6


# =============================================================================
# Settings that do NOT reach the API process, and why
# =============================================================================
# An entry here is a REFUSAL, not an exemption: the operator can still write the
# setting in .env, and the reason below is what .env.example tells them will
# happen instead. Adding an entry to dodge the gate rather than to describe a
# real constraint is the failure this module exists to prevent -- if a setting
# can be forwarded, forward it.
NOT_FORWARDED: dict[str, str] = {
    # -- Host-side tooling: no containerised process reads these ---------------
    "DEV__API_URL": (
        "host-only: the address dev scripts on your machine use to reach the "
        "stack (seed, replay, e2e). The API does not call itself."
    ),
    "DEV__SMEE_URL": "host-only: `just dev` starts the smee webhook proxy on the host, not in a container.",
    # -- Pinned by the deployment: the container needs a specific value --------
    "SYN_OBSERVABILITY_DB_URL": (
        "pinned: points at the bundled timescaledb service, and the selfhost "
        "entrypoint rebuilds it from the db_password Docker secret. Change the "
        "database via POSTGRES_* in infra/.env."
    ),
    "EVENT_STORE_HOST": "pinned: the event-store service name on the compose network.",
    "EVENT_STORE_PORT": "pinned: the port event-store listens on inside the compose network.",
    "REDIS_URL": (
        "pinned: points at the bundled redis service, and the selfhost "
        "entrypoint rebuilds it from the redis_password Docker secret."
    ),
    "SYN_WORKSPACE_CONTAINER_DIR": (
        "pinned: the in-container mount point of the workspaces volume. Set SYN_INSTALL_DIR to move the host side."
    ),
    "SYN_WORKSPACE_HOST_DIR": (
        "pinned: derived from SYN_INSTALL_DIR so it always matches the bind mount. Set SYN_INSTALL_DIR instead."
    ),
    "SYN_STORAGE_PROVIDER": "pinned: the selfhost stack ships MinIO and wires the API to it.",
    "SYN_STORAGE_MINIO_ENDPOINT": "pinned: the bundled minio service address on the compose network.",
    "SYN_STORAGE_MINIO_ACCESS_KEY": "pinned: follows MINIO_ROOT_USER in infra/.env, so the two cannot disagree.",
    "SYN_STORAGE_MINIO_SECURE": "pinned: traffic to the bundled minio stays on the internal network.",
    "SYN_GITHUB_PRIVATE_KEY": (
        "pinned: the published selfhost stack mounts the PEM as a tmpfs-backed "
        "Docker secret and drops this variable, because a key in container env "
        "is readable from `docker inspect`. Put the PEM in "
        "secrets/github-app-private-key.pem instead."
    ),
    "SYN_GITHUB_APP_PRIVATE_KEY_FILE": (
        "pinned: the selfhost stack mounts the PEM as a Docker secret. Put it "
        "in secrets/github-app-private-key.pem, not in .env."
    ),
}


# =============================================================================
# Reading the two sides
# =============================================================================


def documented_settings() -> list[str]:
    """Every variable name `.env.example` offers an operator, in file order."""
    names: list[str] = []
    for line in ENV_EXAMPLE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        names.append(stripped.split("=", 1)[0].strip())
    return names


def api_environment(compose_yaml: str) -> dict[str, str | None]:
    """The api service's environment map, normalized from either compose form.

    ``None`` means the bare `KEY:` form -- pass the host value through, and omit
    the key entirely when it is unset. That is what keeps "unset" and "set to
    empty" distinguishable (#954), so it must survive normalization.
    """
    parsed = yaml.safe_load(compose_yaml) or {}
    env = ((parsed.get("services") or {}).get("api") or {}).get("environment")
    if isinstance(env, dict):
        return {str(k): (None if v is None else str(v)) for k, v in env.items()}
    result: dict[str, str | None] = {}
    for entry in env or []:
        key, _, value = str(entry).partition("=")
        result[key] = value
    return result


def _reaches_process(name: str, value: str | None) -> bool:
    """Does an operator's `.env` value for `name` arrive in the container?

    Either the bare form, or an interpolation that names the variable itself --
    `${FOO}`, `${FOO:-x}`, `${FOO-x}`. An interpolation naming a DIFFERENT
    variable is a pin: it looks like forwarding in the file and is not.
    """
    if value is None:
        return True
    return re.search(r"\$\{" + re.escape(name) + r"[:\-}]", value) is not None


# =============================================================================
# The invariant
# =============================================================================


@dataclass(frozen=True)
class ForwardingReport:
    """Where the documented settings and a compose file disagree."""

    inert: tuple[str, ...]
    """Documented, absent from the api environment, and no recorded reason."""

    silently_pinned: tuple[str, ...]
    """Documented, overridden by a fixed compose value, and no recorded reason."""

    stale_reasons: tuple[str, ...]
    """Recorded in NOT_FORWARDED but forwarded (or no longer documented) now."""

    forwarded: tuple[str, ...]
    """Documented settings whose `.env` value actually reaches the process."""

    def failures(self) -> list[str]:
        """Human-readable violations; empty means the two sides agree."""
        source = Path(__file__).name
        problems: list[str] = []
        for name in self.inert:
            problems.append(
                f"{name}: documented in .env.example but never reaches the api "
                f"container, so setting it does nothing and says nothing. Run "
                f"`just gen-compose` to forward it, or record why it cannot be "
                f"forwarded in NOT_FORWARDED in {source}."
            )
        for name in self.silently_pinned:
            problems.append(
                f"{name}: the compose file pins a fixed value, so an operator's "
                f".env value is discarded without a word. Record the reason in "
                f"NOT_FORWARDED in {source} so .env.example says so."
            )
        for name in self.stale_reasons:
            problems.append(
                f"{name}: listed in NOT_FORWARDED but it is forwarded now (or is "
                f"no longer documented). Drop the entry -- a stale refusal tells "
                f"operators the opposite of the truth."
            )
        return problems


def report(compose: Path = PUBLISHED_COMPOSE) -> ForwardingReport:
    """Classify every documented setting against what `compose` forwards."""
    env = api_environment(compose.read_text())

    inert: list[str] = []
    silently_pinned: list[str] = []
    forwarded: list[str] = []
    explained: set[str] = set()

    for name in documented_settings():
        if name in env and _reaches_process(name, env[name]):
            forwarded.append(name)
        elif name in NOT_FORWARDED:
            explained.add(name)
        elif name in env:
            silently_pinned.append(name)
        else:
            inert.append(name)

    return ForwardingReport(
        inert=tuple(inert),
        silently_pinned=tuple(silently_pinned),
        stale_reasons=tuple(sorted(set(NOT_FORWARDED) - explained)),
        forwarded=tuple(forwarded),
    )


# =============================================================================
# Generating the compose block
# =============================================================================


def _handwritten_api_keys() -> set[str]:
    """Keys the base compose declares OUTSIDE the generated block.

    Those carry deliberate container-internal values and the comments that
    explain them. Re-emitting one would be a duplicate YAML key, so the block
    skips it -- and `report()` then requires it to carry a NOT_FORWARDED reason.
    """
    inside = False
    outside: list[str] = []
    for line in BASE_COMPOSE.read_text().splitlines():
        if BEGIN_MARKER in line:
            inside = True
        elif END_MARKER in line:
            inside = False
        elif not inside:
            outside.append(line)
    return set(api_environment("\n".join(outside)))


def generated_keys() -> list[str]:
    """The settings the block forwards: documented, forwardable, not hand-written."""
    handwritten = _handwritten_api_keys()
    return [
        name
        for name in documented_settings()
        if name not in NOT_FORWARDED and name not in handwritten
    ]


def forwarding_block() -> list[str]:
    """The generated compose lines, markers included, at api-environment indent.

    Bare keys, for the reason in `api_environment`: compose drops an unset one
    entirely, so a setting the operator never wrote keeps its Pydantic default
    instead of being forced to "".
    """
    return [
        f"{_ENV_INDENT}{BEGIN_MARKER}",
        f"{_ENV_INDENT}# Every setting .env.example documents, forwarded so that writing one",
        f"{_ENV_INDENT}# in .env has the effect the docs promise (#1101). Bare keys: compose",
        f"{_ENV_INDENT}# drops an unset one, so an unwritten setting keeps its own default.",
        f"{_ENV_INDENT}# Overlays may still override any of these with a fixed value.",
        *(f"{_ENV_INDENT}{name}:" for name in generated_keys()),
        f"{_ENV_INDENT}{END_MARKER}",
    ]


def render_base_compose() -> str:
    """docker-compose.yaml with the generated block replaced in place."""
    lines = BASE_COMPOSE.read_text().splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if BEGIN_MARKER in line)
        end = next(i for i, line in enumerate(lines) if END_MARKER in line)
    except StopIteration:
        raise SystemExit(
            f"{BASE_COMPOSE}: generated-block markers not found. The api "
            f"service's environment must contain a line holding\n  {BEGIN_MARKER}\n"
            f"and a later line holding\n  {END_MARKER}"
        ) from None
    return "\n".join([*lines[:start], *forwarding_block(), *lines[end + 1 :]]) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forward every documented setting to the api container."
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the block is stale instead of rewriting it"
    )
    args = parser.parse_args(argv)

    rendered = render_base_compose()
    relative = BASE_COMPOSE.relative_to(PROJECT_ROOT)

    if args.check:
        if rendered != BASE_COMPOSE.read_text():
            print(
                f"ERROR: {relative} does not forward every documented setting.\nRun: just gen-compose",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {relative} forwards every documented setting")
        return 0

    BASE_COMPOSE.write_text(rendered)
    print(f"OK: forwarded {len(generated_keys())} settings into {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
