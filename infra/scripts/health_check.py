#!/usr/bin/env python3
"""
Health check for Syn137 infrastructure services.
Cross-platform (Windows, macOS, Linux).

Usage:
    python health_check.py              # Check all services once
    python health_check.py --wait       # Wait for all services to be ready
    python health_check.py --timeout 60 # Set timeout for --wait (default: 120s)
    python health_check.py --json       # Output as JSON
    python health_check.py --docker     # Use Docker health status (default when ports not exposed)

Examples:
    # Quick status check
    python infra/scripts/health_check.py

    # Wait for stack to be ready after startup
    python infra/scripts/health_check.py --wait --timeout 180

    # CI/CD health verification
    python infra/scripts/health_check.py --json
"""

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass

from shared import (
    PORT_API,
    PORT_COLLECTOR,
    PORT_EVENT_STORE,
    PORT_MINIO,
    PORT_POSTGRES,
    PORT_REDIS,
    PORT_UI,
)


@dataclass
class Service:
    """Service definition for health checking."""

    name: str
    host: str
    port: int
    health_path: str | None = None
    protocol: str = "http"
    description: str = ""
    container_name: str = ""


@dataclass
class ServiceStatus:
    """Health check result for a service."""

    name: str
    healthy: bool
    message: str
    response_time_ms: float | None = None


def _container_prefix() -> str:
    """Container name prefix for selfhost stack (docker-compose.selfhost.yaml).

    This script is only invoked by ``just selfhost-*`` recipes.
    Dev containers use a different prefix (``syn-``) and do not use this script.
    """
    return "syn137-"


def _build_services() -> list[Service]:
    """Build the service list with the current container name prefix."""
    prefix = _container_prefix()
    return [
        Service(
            name="PostgreSQL",
            host="localhost",
            port=PORT_POSTGRES,
            description="Database",
            container_name=f"{prefix}timescaledb",
        ),
        Service(
            name="Event Store",
            host="localhost",
            port=PORT_EVENT_STORE,
            description="Event sourcing gRPC service",
            container_name=f"{prefix}event-store",
        ),
        Service(
            name="Collector",
            host="localhost",
            port=PORT_COLLECTOR,
            health_path="/health",
            description="Event collection HTTP API",
            container_name=f"{prefix}collector",
        ),
        Service(
            name="API",
            host="localhost",
            port=PORT_API,
            health_path="/health",
            description="Syn137 API",
            container_name=f"{prefix}api",
        ),
        Service(
            name="Gateway",
            host="localhost",
            port=PORT_UI,
            health_path="/health",
            description="Syn137 Gateway (nginx)",
            container_name=f"{prefix}gateway",
        ),
        Service(
            name="MinIO",
            host="localhost",
            port=PORT_MINIO,
            health_path="/minio/health/live",
            description="Object storage",
            container_name=f"{prefix}minio",
        ),
        Service(
            name="Redis",
            host="localhost",
            port=PORT_REDIS,
            description="Cache and message broker",
            container_name=f"{prefix}redis",
        ),
    ]


# Built lazily via _build_services() — but provide a module-level reference
# for backward compatibility with code that imports SERVICES directly.
SERVICES = _build_services()


def check_port(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float]:
    """Check if a TCP port is open. Returns (success, response_time_ms)."""
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        elapsed = (time.time() - start) * 1000
        return result == 0, elapsed
    except Exception:
        elapsed = (time.time() - start) * 1000
        return False, elapsed


def check_http(host: str, port: int, path: str, timeout: float = 5.0) -> tuple[bool, float, str]:
    """Check if an HTTP endpoint returns 200. Returns (success, response_time_ms, message)."""
    start = time.time()
    try:
        url = f"http://{host}:{port}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = (time.time() - start) * 1000
            return resp.status == 200, elapsed, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - start) * 1000
        return False, elapsed, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        elapsed = (time.time() - start) * 1000
        return False, elapsed, f"Connection failed: {e.reason}"
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return False, elapsed, str(e)


# ---------------------------------------------------------------------------
# Docker-native health checking
# ---------------------------------------------------------------------------


def _docker_health_statuses() -> dict[str, str]:
    """Query Docker for container health status. Returns {container_name: status}."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    statuses: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            statuses[parts[0]] = parts[1]
    return statuses


def check_service_docker(service: Service, docker_statuses: dict[str, str]) -> ServiceStatus:
    """Check a service using Docker container health status."""
    if not service.container_name:
        return ServiceStatus(
            name=service.name, healthy=False, message="No container name configured"
        )

    status_str = docker_statuses.get(service.container_name, "")
    if not status_str:
        return ServiceStatus(name=service.name, healthy=False, message="Container not running")

    if "(healthy)" in status_str:
        return ServiceStatus(name=service.name, healthy=True, message="Docker healthy")
    if "(health: starting)" in status_str:
        return ServiceStatus(name=service.name, healthy=False, message="Starting")
    if "(unhealthy)" in status_str:
        return ServiceStatus(name=service.name, healthy=False, message="Docker unhealthy")
    # Container running but no healthcheck defined — treat as healthy
    if status_str.startswith("Up"):
        return ServiceStatus(name=service.name, healthy=True, message="Running (no healthcheck)")

    return ServiceStatus(name=service.name, healthy=False, message=f"Unknown: {status_str}")


def check_all_docker() -> list[ServiceStatus]:
    """Check all services via Docker container health."""
    statuses = _docker_health_statuses()
    return [check_service_docker(svc, statuses) for svc in SERVICES]


# ---------------------------------------------------------------------------
# Localhost port-based health checking
# ---------------------------------------------------------------------------


def check_service(service: Service) -> ServiceStatus:
    """Check if a service is healthy via localhost port probing."""
    port_ok, port_time = check_port(service.host, service.port)

    if not port_ok:
        return ServiceStatus(
            name=service.name,
            healthy=False,
            message=f"Port {service.port} not responding",
            response_time_ms=port_time,
        )

    if service.health_path:
        http_ok, http_time, msg = check_http(service.host, service.port, service.health_path)
        return ServiceStatus(
            name=service.name,
            healthy=http_ok,
            message=msg if not http_ok else "Healthy",
            response_time_ms=http_time,
        )

    return ServiceStatus(
        name=service.name,
        healthy=True,
        message="Port responding",
        response_time_ms=port_time,
    )


def check_all() -> list[ServiceStatus]:
    """Check all services via localhost port probing."""
    return [check_service(svc) for svc in SERVICES]


# ---------------------------------------------------------------------------
# Auto-detection: use Docker health when ports aren't host-exposed
# ---------------------------------------------------------------------------


def _should_use_docker() -> bool:
    """Return True if Docker health checking is preferred.

    Heuristic: if the majority of service ports aren't reachable on
    localhost but Docker containers exist, use Docker health status.
    """
    docker_statuses = _docker_health_statuses()
    if not docker_statuses:
        return False
    # Check if any of our containers are running
    our_containers = [s.container_name for s in SERVICES if s.container_name]
    running = sum(1 for c in our_containers if c in docker_statuses)
    if running == 0:
        return False
    # Quick port probe — if most ports are closed, prefer Docker
    closed = 0
    for svc in SERVICES:
        ok, _ = check_port(svc.host, svc.port, timeout=0.5)
        if not ok:
            closed += 1
    return closed > len(SERVICES) // 2


def smart_check_all(force_docker: bool = False) -> tuple[list[ServiceStatus], str]:
    """Check all services, auto-selecting the best method.

    Returns (statuses, method) where method is "docker" or "localhost".
    """
    if force_docker or _should_use_docker():
        return check_all_docker(), "docker"
    return check_all(), "localhost"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_status(statuses: list[ServiceStatus], as_json: bool = False) -> None:
    """Print service statuses."""
    if as_json:
        print(json.dumps([asdict(s) for s in statuses], indent=2))
        return

    print(f"{'Service':<15} {'Status':<10} {'Response':<12} {'Message'}")
    print("-" * 60)

    for status in statuses:
        symbol = "\u2713" if status.healthy else "\u2717"
        status_text = "healthy" if status.healthy else "unhealthy"
        time_str = f"{status.response_time_ms:.0f}ms" if status.response_time_ms else "N/A"
        print(f"{status.name:<15} {symbol} {status_text:<8} {time_str:<12} {status.message}")


def wait_for_services(timeout: int = 120, interval: int = 2, force_docker: bool = False) -> bool:
    """Wait for all services to be ready.

    Returns True if all services became ready within timeout.
    """
    start = time.time()
    attempt = 0

    while time.time() - start < timeout:
        attempt += 1
        statuses, method = smart_check_all(force_docker=force_docker)
        all_healthy = all(s.healthy for s in statuses)

        if all_healthy:
            print(
                f"\n\u2713 All services ready after {attempt} attempts "
                f"({time.time() - start:.1f}s, via {method})"
            )
            print_status(statuses)
            return True

        unhealthy = [s.name for s in statuses if not s.healthy]
        remaining = timeout - (time.time() - start)
        print(f"[{attempt}] Waiting for: {', '.join(unhealthy)} ({remaining:.0f}s remaining)")

        time.sleep(interval)

    print(f"\n\u2717 Timeout after {timeout}s - some services not ready")
    statuses, _ = smart_check_all(force_docker=force_docker)
    print_status(statuses)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check Syn137 service health",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    Check all services
  %(prog)s --wait             Wait for services to be ready
  %(prog)s --wait --timeout 60  Wait up to 60 seconds
  %(prog)s --json             Output as JSON
  %(prog)s --docker           Force Docker health check mode
        """,
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for all services to be ready",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for --wait (default: 120)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Use Docker container health status instead of localhost port probing",
    )
    args = parser.parse_args()

    if not args.json:
        print("=" * 50)
        print("Syn137 Infrastructure Health Check")
        print("=" * 50)
        print()

    if args.wait:
        success = wait_for_services(args.timeout, force_docker=args.docker)
    else:
        statuses, method = smart_check_all(force_docker=args.docker)
        if not args.json:
            print(f"(checking via {method})\n")
        print_status(statuses, as_json=args.json)
        success = all(s.healthy for s in statuses)

        if not args.json:
            print()
            if success:
                print("\u2713 All services healthy!")
            else:
                print("\u2717 Some services unhealthy")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
