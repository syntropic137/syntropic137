#!/usr/bin/env python3
"""Which documented settings actually reach the API container, and why not.

`.env.example` is generated from the Settings classes (ADR-004), so EVERY
setting appears there and looks available. But a container only sees what the
compose file forwards, and that list was maintained by hand. The two drifted:
`SYN_IMAGE_VERIFY_ALLOW_LOCAL_IMAGES` was set on a selfhost, the API was
restarted, and nothing happened -- no error, no warning, just the old behaviour
(#1101). Eighty-seven of the 103 documented settings were inert the same way.

This module owns the decision "does setting X reach the API process?" so that
it is made once, in code, instead of twice by hand:

  * `render_generated_env()` renders the compose entries that make a setting
    reachable. `python scripts/settings_forwarding.py` writes them into
    docker/generated/api.env.yaml, a file of its own that the api service in
    docker/docker-compose.yaml pulls in with `extends`; `--check` fails if it
    is stale. Every stack layers on that base, so one file covers all. It is a
    separate file so that adding a setting never edits a compose file: compose
    files carry privilege (mounts, sockets, ports, credentials) and are
    owner-reviewed, while this file is derived and is not.
  * `NOT_FORWARDED` records the settings that genuinely cannot be forwarded,
    each with the reason. Being ignored is allowed; being ignored silently is
    not, so the reason is also emitted into `.env.example` beside the setting.
  * `COMPOSE_OWNED` records the few settings a compose file keeps declaring by
    hand on purpose, each with the reason. Every other documented setting is
    the generator's, and `handlisted()` fails when a compose file restates one.
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

# The generated passthrough. Derived, so deliberately NOT under CODEOWNERS: a
# feature that adds a setting changes this file and its Settings class, and no
# compose file. The api service in BASE_COMPOSE `extends` GENERATED_SERVICE
# from it; compose gives the extending service's own keys precedence, and every
# overlay layers on top, so a hand-written value always wins over a generated one.
GENERATED_DIR = PROJECT_ROOT / "docker" / "generated"
GENERATED_ENV = GENERATED_DIR / "api.env.yaml"
GENERATED_SERVICE = "api-env"

# Every compose file a person writes. The published file is generated (from the
# base, this file and the selfhost overlay), so it is checked by report().
HANDWRITTEN_COMPOSE = tuple(
    path
    for path in sorted((PROJECT_ROOT / "docker").glob("docker-compose*.yaml"))
    if path != PUBLISHED_COMPOSE
)

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
    "SYN_SESSION_INVENTORY_ARCHIVE_DIR": (
        "pinned: the in-container mount point of the session_inventory_data "
        "volume, so captured transcripts outlive the container. Pointing it "
        "anywhere else would write them to the container's ephemeral layer."
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
# Settings forwarded with a default instead of bare
# =============================================================================
# Emitted as `KEY: ${KEY:-default}` rather than `KEY:`. The difference is real:
# a bare key is dropped when unset, so the Settings default applies, while this
# form always sets the variable -- to the default here when the operator wrote
# nothing, and to the default too when they wrote it empty. These were written
# this way by hand in docker-compose.yaml before the passthrough was generated,
# and moving them here kept each one's rendered value byte-for-byte.
#
# It is still forwarding, not a pin: the interpolation names the setting
# itself, so the operator's value always wins. A setting that needs a value of
# its own choosing belongs in NOT_FORWARDED instead.
FORWARD_WITH_DEFAULT: dict[str, str] = {
    # Off unless the operator opts in (#1385): the widget is owner-only.
    "SYN_UI_FEEDBACK_ENABLED": "false",
    # Local session capture. Empty / numeric defaults mirror the Settings class.
    "SYN_SESSION_INVENTORY_SOURCE_INSTANCE_ID": "",
    "SYN_SESSION_INVENTORY_SWEEP_INTERVAL_SECONDS": "30",
    "SYN_SESSION_INVENTORY_SETTLEMENT_GRACE_SECONDS": "1800",
    "SYN_SESSION_INVENTORY_LEASE_SECONDS": "120",
    "SYN_SESSION_INVENTORY_RETRY_SECONDS": "10",
    "SYN_SESSION_INVENTORY_MAX_JOBS_PER_TICK": "2",
    "SYN_SESSION_INVENTORY_MAX_EVIDENCE_RECORDS": "100000",
    "SYN_SESSION_INVENTORY_MAX_EVIDENCE_BATCHES": "10000",
    # Central session store (SeshMagic). An empty URL disables capture, which
    # is a legitimate configuration -- so a stack that failed to forward these
    # looked exactly like one that chose not to (see
    # infra/scripts/tests/test_compose_env_contracts.py for that history).
    "SYN_SESSION_STORE_URL": "",
    "SYN_SESSION_STORE_AUTH_TOKEN": "",
    "SYN_SESSION_STORE_LABEL": "",
    # Operator co-authorship on agent commits (#1265). The workspace image's
    # prepare-commit-msg hook exits silently when either is missing.
    "SYN_OPERATOR_NAME": "",
    "SYN_OPERATOR_EMAIL": "",
}


# =============================================================================
# Settings a compose file keeps declaring by hand, and why
# =============================================================================
# The exception, not the rule. A setting belongs here only when the line that
# forwards it is itself a privilege decision an owner must review -- so it stays
# in a CODEOWNERS-owned compose file instead of in the generated one. The
# generator skips these, and handlisted() lets a compose file name them.
COMPOSE_OWNED: dict[str, str] = {
    "SYN_WORKSPACE_DOCKER_IMAGE": (
        "selects the image every agent runs in, so forwarding it is a "
        "supply-chain decision (#954). Declared bare in docker-compose.yaml, "
        "where the comment beside it explains why unset and empty must differ."
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
# Generating the passthrough file
# =============================================================================


def generated_keys() -> list[str]:
    """The settings the generated file forwards, in `.env.example` order.

    Every documented setting, less those that cannot be forwarded
    (NOT_FORWARDED) and those a compose file owns on purpose (COMPOSE_OWNED).
    Nothing else is skipped -- in particular, NOT whatever a compose file
    happens to list, or hand-listing a setting would quietly take it away from
    the generator. handlisted() reports that instead.
    """
    return [
        name
        for name in documented_settings()
        if name not in NOT_FORWARDED and name not in COMPOSE_OWNED
    ]


def generated_value(name: str) -> str | None:
    """The value the generated file gives `name`: bare, or `${name:-default}`."""
    if name in FORWARD_WITH_DEFAULT:
        return "${" + name + ":-" + FORWARD_WITH_DEFAULT[name] + "}"
    return None


def _render_entry(name: str) -> str:
    value = generated_value(name)
    return f"{_ENV_INDENT}{name}:" + ("" if value is None else f" {value}")


GENERATED_HEADER = """\
# =============================================================================
# GENERATED by scripts/settings_forwarding.py -- do not edit by hand.
# Regenerate: just gen-compose (also run by just codegen)
# =============================================================================
# Every setting .env.example documents, forwarded to the api container so that
# writing one in .env has the effect the docs promise (#1101). The source of
# truth is the Pydantic Settings classes (ADR-004), via .env.example.
#
# docker-compose.yaml's api service pulls this in with `extends`. Its own keys
# take precedence, and every overlay layers on top, so any hand-written value
# for one of these wins. scripts/generate_published_compose.py inlines it into
# the published standalone file.
#
# Bare keys: compose drops an unset one, so an unwritten setting keeps its own
# default. `${KEY:-default}` entries come from FORWARD_WITH_DEFAULT.
# =============================================================================
"""


def render_generated_env() -> str:
    """The full text of GENERATED_ENV."""
    lines = [
        "services:",
        f"  {GENERATED_SERVICE}:",
        "    environment:",
        *(_render_entry(name) for name in generated_keys()),
    ]
    return GENERATED_HEADER + "\n".join(lines) + "\n"


def generated_environment() -> dict[str, str | None]:
    """The committed generated environment, parsed."""
    parsed = yaml.safe_load(GENERATED_ENV.read_text()) or {}
    env = ((parsed.get("services") or {}).get(GENERATED_SERVICE) or {}).get("environment")
    return {str(k): (None if v is None else str(v)) for k, v in (env or {}).items()}


# =============================================================================
# Hand-listed settings the generator owns
# =============================================================================


def _service_environment(compose_yaml: str, service: str) -> dict[str, str | None]:
    parsed = yaml.safe_load(compose_yaml) or {}
    env = ((parsed.get("services") or {}).get(service) or {}).get("environment")
    if isinstance(env, dict):
        return {str(k): (None if v is None else str(v)) for k, v in env.items()}
    result: dict[str, str | None] = {}
    for entry in env or []:
        key, sep, value = str(entry).partition("=")
        result[key] = value if sep else None
    return result


def handlisted(path: Path) -> list[str]:
    """Generator-owned settings that `path` restates by hand, as messages.

    In the base file, the generator owns these outright: any line for one is a
    second source of truth, and the next generated change would be silently
    shadowed by it. A pin belongs in NOT_FORWARDED, a deliberate hand-written
    passthrough in COMPOSE_OWNED.

    An overlay may override a generated setting -- that is what overlays are
    for, and a different default or a fixed value there is a deployment
    decision. What it may not do is restate the generated line verbatim: that
    is a copy, it adds nothing, and it is exactly the per-feature compose edit
    this generator exists to remove.
    """
    owned = set(generated_keys())
    env = _service_environment(path.read_text(), "api")
    is_base = path == BASE_COMPOSE
    problems: list[str] = []
    for name, value in env.items():
        if name not in owned:
            continue
        if is_base:
            problems.append(
                f"{path.name}: hand-lists {name}, which the generator owns. Delete "
                f"the line; {GENERATED_ENV.relative_to(PROJECT_ROOT)} forwards it."
            )
        elif value == generated_value(name) or value == "${" + name + "}":
            problems.append(
                f"{path.name}: restates the generated passthrough for {name} "
                f"({value!r}). Delete the line; the base already forwards it."
            )
    return problems


def base_extends_generated() -> bool:
    """Does the base api service actually pull the generated file in?"""
    parsed = yaml.safe_load(BASE_COMPOSE.read_text()) or {}
    extends = ((parsed.get("services") or {}).get("api") or {}).get("extends") or {}
    if not isinstance(extends, dict):
        return False
    target = (BASE_COMPOSE.parent / str(extends.get("file", ""))).resolve()
    return target == GENERATED_ENV.resolve() and extends.get("service") == GENERATED_SERVICE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forward every documented setting to the api container."
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the file is stale instead of rewriting it"
    )
    args = parser.parse_args(argv)

    rendered = render_generated_env()
    relative = GENERATED_ENV.relative_to(PROJECT_ROOT)

    if args.check:
        current = GENERATED_ENV.read_text() if GENERATED_ENV.exists() else ""
        if rendered != current:
            print(
                f"ERROR: {relative} does not forward every documented setting.\nRun: just gen-compose",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {relative} forwards every documented setting")
        return 0

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_ENV.write_text(rendered)
    print(f"OK: forwarded {len(generated_keys())} settings into {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
