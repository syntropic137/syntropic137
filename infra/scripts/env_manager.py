#!/usr/bin/env python3
"""
On-demand environment manager for Syntropic137.

Manages port allocation, environment file generation, Docker Compose lifecycle,
and the registry (infra/environments.json) for on-demand environments.

Usage:
    python infra/scripts/env_manager.py up <branch>       # create + start
    python infra/scripts/env_manager.py down <name>        # stop + destroy
    python infra/scripts/env_manager.py stop <name>        # pause
    python infra/scripts/env_manager.py start <name>       # resume
    python infra/scripts/env_manager.py logs <name>        # stream logs
    python infra/scripts/env_manager.py list               # show all
    python infra/scripts/env_manager.py status <name>      # show details

See: ADR-060 - On-Demand Environment Creation
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
REGISTRY_FILE = REPO_ROOT / "infra" / "environments.json"
REGISTRY_LOCK_FILE = REPO_ROOT / "infra" / ".environments.lock"
DOCKER_DIR = REPO_ROOT / "docker"
COMPOSE_BASE = DOCKER_DIR / "docker-compose.yaml"
COMPOSE_ONDEMAND = DOCKER_DIR / "docker-compose.ondemand.yaml"
RESOLVE_SCRIPT = REPO_ROOT / "scripts" / "resolve_infra_env.py"

# Env var keys that must NOT leak from the parent shell into `docker compose`.
# Docker Compose precedence puts shell env > --env-file, so a stale
# SYN_ENV_PORT_ENVOY in the user's shell (e.g. sourced from a prior
# .env.ondemand-*) would override the slot-correct values in the generated
# env-file and create containers with wrong port bindings.
_LEAK_PREFIXES: tuple[str, ...] = (
    "SYN_ENV_PORT_",
    "SYN_ENV_NAME",
    "SYN_AGENT_NETWORK",
    # SYN_INSTALL_DIR resolves workspace bind mounts. If the justfile's
    # dotenv-load pulls it from a different repo's .env (common when working
    # across worktrees), the API container writes workspaces to one path and
    # mounts them into agents from another - setup.sh never lands.
    "SYN_INSTALL_DIR",
)

# ---------------------------------------------------------------------------
# Environment sanitization
# ---------------------------------------------------------------------------


def _sanitized_env() -> dict[str, str]:
    """Copy os.environ with leak-prone keys stripped.

    Keeps secrets (ANTHROPIC_API_KEY, SYN_GITHUB_*, etc.) flowing through to
    docker compose, but prevents a stale SYN_ENV_PORT_* in the user's shell
    from overriding the generated --env-file.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith(_LEAK_PREFIXES)}


def _warn_if_shell_leaks() -> None:
    """Print a visible warning if the user's shell has leak-prone vars set.

    Our _sanitized_env() protects the docker compose call, but a user who
    runs `docker compose ...` manually afterwards (or `just env-logs`) from
    the same shell could still hit surprises. Surface this early.
    """
    offenders = sorted(k for k in os.environ if k.startswith(_LEAK_PREFIXES))
    if not offenders:
        return
    print(
        "  [warn] Shell has leak-prone env vars set (will be stripped from docker "
        "compose, but may affect manual invocations):",
        file=sys.stderr,
    )
    for key in offenders:
        print(f"    {key}={os.environ[key]}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Port availability
# ---------------------------------------------------------------------------


def _port_free(port: int) -> bool:
    """Return True if the port can be bound on localhost right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _occupied_ports(ports: SlotPorts) -> list[tuple[str, int]]:
    """Return [(service, port), ...] for every port in `ports` not currently free."""
    busy: list[tuple[str, int]] = []
    for field_name in ports.__dataclass_fields__:
        port = getattr(ports, field_name)
        if not _port_free(port):
            busy.append((field_name, port))
    return busy


# ---------------------------------------------------------------------------
# Registry locking
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _registry_lock() -> Iterator[None]:
    """Exclusive advisory lock around a read-modify-write on the registry.

    Prevents two concurrent `env-up` invocations (e.g. from different
    worktrees) from both allocating the same slot. fcntl.flock is cooperative
    and confined to processes on the same host, which matches the scope of
    the on-demand env system.
    """
    REGISTRY_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_LOCK_FILE.open("w") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Port allocation
# ---------------------------------------------------------------------------
#
# Slot 0: dev stack        (hardcoded: 5432, 9137, 8080, ...)
# Slot 1: test stack       (hardcoded: +10000 offset, no API port)
# Slots 2-5: on-demand     (managed here)
#
# Port formula:
#   Most services: dev_port + (slot * 10000)
#   Event store:   separate range starting at 60051 to avoid 50051/55051
#
# Max host port is 65535. Slot 5 worst case: 9137+50000=59137. OK.

_MAX_SLOTS: int = 4  # supports slots 2, 3, 4, 5


@dataclass(frozen=True)
class SlotPorts:
    gateway: int  # primary entry point (nginx + UI) - mirrors selfhost :8137
    api: int  # direct API access (also available through gateway at /api/v1)
    db: int
    event_store: int
    collector: int
    minio: int
    minio_console: int
    redis: int
    envoy: int


def _compute_ports(slot: int) -> SlotPorts:
    if slot < 2 or slot > 5:
        raise ValueError(f"Slot must be 2-5, got {slot}")
    offset = slot * 10000
    return SlotPorts(
        gateway=8137 + offset,  # 28137, 38137, ... - the selfhost port + offset
        api=9137 + offset,  # preserves the 137 branding: 29137, 39137, ...
        db=5432 + offset,
        event_store=60051 + (slot - 2) * 1000,  # 60051, 61051, 62051, 63051
        collector=8080 + offset,
        minio=9000 + offset,
        minio_console=9001 + offset,
        redis=6379 + offset,
        envoy=8081 + offset,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class Environment:
    name: str
    branch: str
    slot: int
    created_at: str
    ports: dict[str, int]


@dataclass
class Registry:
    environments: list[Environment] = field(default_factory=list)

    def find(self, name: str) -> Environment | None:
        return next((e for e in self.environments if e.name == name), None)

    def used_slots(self) -> set[int]:
        return {e.slot for e in self.environments}


def _load_registry() -> Registry:
    if not REGISTRY_FILE.exists():
        return Registry()
    data: dict[str, object] = json.loads(REGISTRY_FILE.read_text())
    envs = [
        Environment(
            name=str(e["name"]),
            branch=str(e["branch"]),
            slot=int(str(e["slot"])),
            created_at=str(e["created_at"]),
            ports={str(k): int(str(v)) for k, v in e["ports"].items()},  # type: ignore[union-attr]
        )
        for e in data.get("environments", [])  # type: ignore[union-attr]
    ]
    return Registry(environments=envs)


def _save_registry(registry: Registry) -> None:
    """Atomically write the registry via temp-file + rename."""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"environments": [asdict(e) for e in registry.environments]}
    tmp = REGISTRY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(REGISTRY_FILE)


# ---------------------------------------------------------------------------
# Slug
# ---------------------------------------------------------------------------


def _slugify(branch: str) -> str:
    """Convert a branch name to a safe slug for container/file names."""
    slug = re.sub(r"^(feat|feature|fix|chore|hotfix|release)/", "", branch)
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower())
    return slug.strip("-")


# ---------------------------------------------------------------------------
# Env file
# ---------------------------------------------------------------------------


def _env_file_path(name: str) -> Path:
    return REPO_ROOT / f".env.ondemand-{name}"


def _write_env_file(env: Environment) -> Path:
    """Write the .env file consumed by docker compose --env-file."""
    ports = env.ports
    path = _env_file_path(env.name)
    path.write_text(
        "\n".join(
            [
                "# Auto-generated by infra/scripts/env_manager.py - DO NOT COMMIT",
                f"# Environment: {env.name}  branch: {env.branch}  slot: {env.slot}",
                "",
                f"SYN_ENV_NAME={env.name}",
                "",
                "# Port mappings (host ports - container ports are fixed)",
                f"SYN_ENV_PORT_GATEWAY={ports['gateway']}",
                f"SYN_ENV_PORT_API={ports['api']}",
                f"SYN_ENV_PORT_DB={ports['db']}",
                f"SYN_ENV_PORT_ES={ports['event_store']}",
                f"SYN_ENV_PORT_COLLECTOR={ports['collector']}",
                f"SYN_ENV_PORT_MINIO={ports['minio']}",
                f"SYN_ENV_PORT_MINIO_CONSOLE={ports['minio_console']}",
                f"SYN_ENV_PORT_REDIS={ports['redis']}",
                f"SYN_ENV_PORT_ENVOY={ports['envoy']}",
                "",
                "# Agent network - must match compose project name: syn-env-{name}_agent-net",
                f"SYN_AGENT_NETWORK=syn-env-{env.name}_agent-net",
                "",
                "# Host repo root - used by workspace bind mounts. Must match the",
                "# worktree compose is running from so agents see workspaces the API wrote.",
                f"SYN_INSTALL_DIR={REPO_ROOT}",
            ]
        )
        + "\n"
    )
    return path


# ---------------------------------------------------------------------------
# Secret resolution (shared with `just dev`)
# ---------------------------------------------------------------------------


def _resolve_secrets() -> None:
    """Resolve infra/.env + 1Password secrets into os.environ.

    Calls the same ``scripts/resolve_infra_env.py`` that ``just dev`` uses so
    Docker Compose inherits credentials (GitHub App PEM, tokens, etc.).
    Without this, on-demand environments start in degraded mode.
    """
    if not RESOLVE_SCRIPT.exists():
        print("  [secrets] resolve_infra_env.py not found - skipping", file=sys.stderr)
        return

    print("  [secrets] Resolving infra env + 1Password secrets...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["uv", "run", "python", str(RESOLVE_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"  [secrets] Failed to resolve secrets: {exc}", file=sys.stderr)
        return

    if result.returncode != 0:
        print(f"  [secrets] resolve_infra_env.py exited {result.returncode}", file=sys.stderr)
        if result.stderr.strip():
            print(f"  [secrets] {result.stderr.strip()}", file=sys.stderr)
        return

    count = 0
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip()
        # Strip surrounding quotes produced by resolve_infra_env.py
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ[key] = value
            count += 1

    print(f"  [secrets] Loaded {count} env vars", file=sys.stderr)

    # Surface any warnings from the script (e.g. deprecated SYN_DOMAIN)
    if result.stderr.strip():
        for warn_line in result.stderr.strip().splitlines():
            print(f"  [secrets] {warn_line}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------


def _compose_args(env: Environment) -> list[str]:
    """Build the docker compose base arguments for an environment."""
    env_file = _env_file_path(env.name)
    return [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_BASE),
        "-f",
        str(COMPOSE_ONDEMAND),
        "--env-file",
        str(env_file),
        "-p",
        f"syn-env-{env.name}",
    ]


def _compose_run(env: Environment, *args: str) -> int:
    """Run a docker compose command, inheriting stdin/stdout/stderr.

    Passes a sanitized env dict so stale SYN_ENV_PORT_* / SYN_ENV_NAME in
    the parent shell cannot override --env-file values (Docker Compose's
    shell > env-file precedence rule).
    """
    cmd = [*_compose_args(env), *args]
    result = subprocess.run(cmd, cwd=str(DOCKER_DIR), env=_sanitized_env())
    return result.returncode


def _compose_exec(env: Environment, *args: str) -> None:
    """Replace this process with a docker compose command (for logs -f)."""
    cmd = [*_compose_args(env), *args]
    os.execvpe(cmd[0], cmd, _sanitized_env())


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _ensure_env(name: str) -> tuple[Registry, Environment] | None:
    """Load registry and find environment. Prints error and returns None if missing."""
    registry = _load_registry()
    env = registry.find(name)
    if env is None:
        print(
            f"Environment '{name}' not found. Run `just env-list` to see available.",
            file=sys.stderr,
        )
        return None
    return registry, env


def _find_free_slot_with_preflight(registry: Registry) -> int:
    """Return the lowest slot whose ports are all free on the host.

    Skips slots where a port is occupied by something outside our registry
    (e.g. `just dev`, `just selfhost`, unrelated processes). Raises if no
    slot in the 2-5 range has a fully clean set.
    """
    used = registry.used_slots()
    first_skip: tuple[int, list[tuple[str, int]]] | None = None
    for slot in range(2, 2 + _MAX_SLOTS):
        if slot in used:
            continue
        ports = _compute_ports(slot)
        busy = _occupied_ports(ports)
        if not busy:
            return slot
        if first_skip is None:
            first_skip = (slot, busy)
        print(
            f"  [preflight] slot {slot} has occupied ports, skipping: "
            + ", ".join(f"{name}={port}" for name, port in busy),
            file=sys.stderr,
        )
    if first_skip is not None:
        slot, busy = first_skip
        busy_str = ", ".join(f"{name}={port}" for name, port in busy)
        raise RuntimeError(
            f"All free on-demand slots have port conflicts. Slot {slot} wants: "
            f"{busy_str}. Stop the offending process (try `lsof -iTCP:PORT`) "
            f"or free a slot with `just env-down <name>`."
        )
    raise RuntimeError(
        f"All {_MAX_SLOTS} on-demand slots are in use. Run `just env-down <name>` to free a slot."
    )


def _allocate(branch: str) -> tuple[Registry, Environment]:
    """Allocate a slot for a branch. Returns existing env if already allocated.

    The read-modify-write of the registry runs under an exclusive file lock
    so concurrent env-up invocations (e.g. from different worktrees) cannot
    race into the same slot.
    """
    with _registry_lock():
        registry = _load_registry()
        slug = _slugify(branch)

        existing = registry.find(slug)
        if existing is not None:
            print(f"Environment '{slug}' already allocated (slot {existing.slot})", file=sys.stderr)
            return registry, existing

        slot = _find_free_slot_with_preflight(registry)
        ports = _compute_ports(slot)

        env = Environment(
            name=slug,
            branch=branch,
            slot=slot,
            created_at=datetime.now(UTC).isoformat(),
            ports={
                "gateway": ports.gateway,
                "api": ports.api,
                "db": ports.db,
                "event_store": ports.event_store,
                "collector": ports.collector,
                "minio": ports.minio,
                "minio_console": ports.minio_console,
                "redis": ports.redis,
                "envoy": ports.envoy,
            },
        )

        _write_env_file(env)
        registry.environments.append(env)
        _save_registry(registry)

        print(f"Allocated slot {slot} for '{slug}' (branch: {branch})", file=sys.stderr)
        return registry, env


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _rollback(env: Environment) -> None:
    """Tear down docker state AND remove registry entry + env file.

    Called when `docker compose up` fails partway through. We explicitly run
    `compose down -v --remove-orphans` so the slot starts clean on the next
    attempt (no leftover volumes, partial containers, or networks).
    """
    # Best-effort docker teardown. If this fails (e.g. nothing was created),
    # we still proceed with registry cleanup.
    _compose_run(env, "down", "-v", "--remove-orphans")

    with _registry_lock():
        registry = _load_registry()
        registry.environments = [e for e in registry.environments if e.name != env.name]
        _save_registry(registry)

    env_file = _env_file_path(env.name)
    if env_file.exists():
        env_file.unlink()

    print(f"Rolled back slot {env.slot} for '{env.name}'.", file=sys.stderr)


def cmd_up(branch: str) -> int:
    """Allocate slot + start the environment."""
    _warn_if_shell_leaks()
    _, env = _allocate(branch)
    _resolve_secrets()
    print(f"Starting environment '{env.name}'...", file=sys.stderr)
    rc = _compose_run(env, "up", "-d", "--build")
    if rc != 0:
        _rollback(env)
        return rc
    print("", file=sys.stderr)
    return cmd_status(env.name)


def cmd_down(name: str) -> int:
    """Stop containers, remove volumes, free the slot."""
    result = _ensure_env(name)
    if result is None:
        return 1
    registry, env = result

    print(f"Destroying environment '{name}'...", file=sys.stderr)
    rc = _compose_run(env, "down", "-v", "--remove-orphans")
    if rc != 0:
        return rc

    with _registry_lock():
        registry = _load_registry()
        registry.environments = [e for e in registry.environments if e.name != name]
        _save_registry(registry)

    env_file = _env_file_path(name)
    if env_file.exists():
        env_file.unlink()

    print(f"Freed slot {env.slot}.", file=sys.stderr)
    return 0


def cmd_stop(name: str) -> int:
    """Pause an environment (containers stopped, slot still held)."""
    result = _ensure_env(name)
    if result is None:
        return 1
    _, env = result
    return _compose_run(env, "stop")


def cmd_start(name: str) -> int:
    """Resume a stopped environment."""
    result = _ensure_env(name)
    if result is None:
        return 1
    _, env = result
    _resolve_secrets()
    return _compose_run(env, "start")


def cmd_logs(name: str) -> int:
    """Stream logs (replaces this process with docker compose logs -f)."""
    result = _ensure_env(name)
    if result is None:
        return 1
    _, env = result
    _compose_exec(env, "logs", "-f")
    return 0  # unreachable after exec


def _env_to_dict(env: Environment) -> dict[str, object]:
    """Structured representation for JSON output and agent consumption."""
    return {
        "name": env.name,
        "branch": env.branch,
        "slot": env.slot,
        "created_at": env.created_at,
        "url": f"http://localhost:{env.ports['gateway']}",
        "api_url": f"http://localhost:{env.ports['gateway']}/api/v1",
        "api_direct_url": f"http://localhost:{env.ports['api']}",
        "api_docs_url": f"http://localhost:{env.ports['gateway']}/api/v1/docs",
        "minio_console_url": f"http://localhost:{env.ports['minio_console']}",
        "agent_network": f"syn-env-{env.name}_agent-net",
        "ports": env.ports,
    }


def cmd_list(*, as_json: bool = False) -> int:
    registry = _load_registry()

    if as_json:
        payload = [_env_to_dict(e) for e in registry.environments]
        print(json.dumps(payload, indent=2))
        return 0

    if not registry.environments:
        print("No on-demand environments. Use `just env-up <branch>` to create one.")
        return 0

    col = "{:<25} {:<35} {:<6} {:<10} {}"
    print(col.format("NAME", "BRANCH", "SLOT", "URL", "CREATED"))
    print("-" * 90)
    for env in registry.environments:
        print(
            col.format(
                env.name,
                env.branch,
                env.slot,
                f":{env.ports['gateway']}",
                env.created_at[:10],
            )
        )
    return 0


def cmd_status(name: str, *, as_json: bool = False) -> int:
    registry = _load_registry()
    env = registry.find(name)
    if env is None:
        print(f"Environment '{name}' not found.")
        return 1

    if as_json:
        print(json.dumps(_env_to_dict(env), indent=2))
        return 0

    print(f"Environment: {env.name}")
    print(f"  Branch:    {env.branch}")
    print(f"  Slot:      {env.slot}")
    print(f"  Created:   {env.created_at[:19].replace('T', ' ')} UTC")
    print()
    print("  URLs:")
    print(f"    Dashboard:     http://localhost:{env.ports['gateway']}")
    print(f"    API (gateway): http://localhost:{env.ports['gateway']}/api/v1")
    print(f"    API (direct):  http://localhost:{env.ports['api']}")
    print(f"    API docs:      http://localhost:{env.ports['gateway']}/api/v1/docs")
    print(f"    MinIO console: http://localhost:{env.ports['minio_console']}")
    print()
    print("  Ports:")
    print(f"    Gateway:       {env.ports['gateway']}")
    print(f"    DB (postgres): {env.ports['db']}")
    print(f"    Event store:   {env.ports['event_store']} (gRPC)")
    print(f"    Collector:     {env.ports['collector']}")
    print(f"    Redis:         {env.ports['redis']}")
    print(f"    Envoy:         {env.ports['envoy']}")
    print()
    print(f"  Agent network: syn-env-{env.name}_agent-net")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="On-demand environment manager (ADR-060)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  %(prog)s up feature/new-triggers    # allocate slot + start\n"
            "  %(prog)s down new-triggers           # stop + free slot\n"
            "  %(prog)s list                        # show all environments\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_up = sub.add_parser("up", help="Allocate slot, write env file, start containers")
    p_up.add_argument("branch", help="Git branch name (e.g. feature/my-thing)")

    p_down = sub.add_parser("down", help="Stop containers, remove volumes, free slot")
    p_down.add_argument("name", help="Environment name (slug)")

    p_stop = sub.add_parser("stop", help="Pause containers (slot still held)")
    p_stop.add_argument("name", help="Environment name (slug)")

    p_start = sub.add_parser("start", help="Resume paused containers")
    p_start.add_argument("name", help="Environment name (slug)")

    p_logs = sub.add_parser("logs", help="Stream container logs")
    p_logs.add_argument("name", help="Environment name (slug)")

    p_list = sub.add_parser("list", help="List all on-demand environments")
    p_list.add_argument(
        "--json", action="store_true", help="Output as JSON (for agent consumption)"
    )

    p_status = sub.add_parser("status", help="Show details for one environment")
    p_status.add_argument("name", help="Environment name (slug)")
    p_status.add_argument(
        "--json", action="store_true", help="Output as JSON (for agent consumption)"
    )

    args = parser.parse_args()

    match args.command:
        case "up":
            return cmd_up(args.branch)
        case "down":
            return cmd_down(args.name)
        case "stop":
            return cmd_stop(args.name)
        case "start":
            return cmd_start(args.name)
        case "logs":
            return cmd_logs(args.name)
        case "list":
            return cmd_list(as_json=args.json)
        case "status":
            return cmd_status(args.name, as_json=args.json)
        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
