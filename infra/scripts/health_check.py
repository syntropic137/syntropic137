#!/usr/bin/env python3
"""
Health check for AEF infrastructure services.
Cross-platform (Windows, macOS, Linux).

Usage:
    python health_check.py              # Check all services once
    python health_check.py --wait       # Wait for all services to be ready
    python health_check.py --timeout 60 # Set timeout for --wait (default: 120s)
    python health_check.py --json       # Output as JSON

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
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass


@dataclass
class Service:
    """Service definition for health checking."""

    name: str
    host: str
    port: int
    health_path: str | None = None
    protocol: str = "http"
    description: str = ""


@dataclass
class ServiceStatus:
    """Health check result for a service."""

    name: str
    healthy: bool
    message: str
    response_time_ms: float | None = None


# Default services to check (localhost for local checks)
SERVICES = [
    Service(
        name="PostgreSQL",
        host="localhost",
        port=5432,
        description="Database",
    ),
    Service(
        name="Event Store",
        host="localhost",
        port=50051,
        description="Event sourcing gRPC service",
    ),
    Service(
        name="Collector",
        host="localhost",
        port=8080,
        health_path="/health",
        description="Event collection HTTP API",
    ),
    Service(
        name="Dashboard",
        host="localhost",
        port=8000,
        health_path="/health",
        description="AEF Dashboard API",
    ),
    Service(
        name="UI",
        host="localhost",
        port=80,
        health_path="/health",
        description="AEF Dashboard UI",
    ),
]


def check_port(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float]:
    """
    Check if a TCP port is open.

    Returns:
        Tuple of (success, response_time_ms)
    """
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
    """
    Check if an HTTP endpoint returns 200.

    Returns:
        Tuple of (success, response_time_ms, message)
    """
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


def check_service(service: Service) -> ServiceStatus:
    """Check if a service is healthy."""
    # First check if port is open
    port_ok, port_time = check_port(service.host, service.port)

    if not port_ok:
        return ServiceStatus(
            name=service.name,
            healthy=False,
            message=f"Port {service.port} not responding",
            response_time_ms=port_time,
        )

    # If service has a health endpoint, check it
    if service.health_path:
        http_ok, http_time, msg = check_http(service.host, service.port, service.health_path)
        return ServiceStatus(
            name=service.name,
            healthy=http_ok,
            message=msg if not http_ok else "Healthy",
            response_time_ms=http_time,
        )

    # Port is open and no health check needed
    return ServiceStatus(
        name=service.name,
        healthy=True,
        message="Port responding",
        response_time_ms=port_time,
    )


def check_all() -> list[ServiceStatus]:
    """Check all services and return status list."""
    return [check_service(svc) for svc in SERVICES]


def print_status(statuses: list[ServiceStatus], as_json: bool = False) -> None:
    """Print service statuses."""
    if as_json:
        print(json.dumps([asdict(s) for s in statuses], indent=2))
        return

    print(f"{'Service':<15} {'Status':<10} {'Response':<12} {'Message'}")
    print("-" * 60)

    for status in statuses:
        symbol = "✓" if status.healthy else "✗"
        status_text = "healthy" if status.healthy else "unhealthy"
        time_str = f"{status.response_time_ms:.0f}ms" if status.response_time_ms else "N/A"
        print(f"{status.name:<15} {symbol} {status_text:<8} {time_str:<12} {status.message}")


def wait_for_services(timeout: int = 120, interval: int = 2) -> bool:
    """
    Wait for all services to be ready.

    Args:
        timeout: Maximum time to wait in seconds
        interval: Time between checks in seconds

    Returns:
        True if all services became ready within timeout
    """
    start = time.time()
    attempt = 0

    while time.time() - start < timeout:
        attempt += 1
        statuses = check_all()
        all_healthy = all(s.healthy for s in statuses)

        if all_healthy:
            print(f"\n✓ All services ready after {attempt} attempts ({time.time() - start:.1f}s)")
            print_status(statuses)
            return True

        unhealthy = [s.name for s in statuses if not s.healthy]
        remaining = timeout - (time.time() - start)
        print(f"[{attempt}] Waiting for: {', '.join(unhealthy)} ({remaining:.0f}s remaining)")

        time.sleep(interval)

    print(f"\n✗ Timeout after {timeout}s - some services not ready")
    print_status(check_all())
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check AEF service health",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    Check all services
  %(prog)s --wait             Wait for services to be ready
  %(prog)s --wait --timeout 60  Wait up to 60 seconds
  %(prog)s --json             Output as JSON
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
    args = parser.parse_args()

    if not args.json:
        print("=" * 50)
        print("AEF Infrastructure Health Check")
        print("=" * 50)
        print()

    if args.wait:
        success = wait_for_services(args.timeout)
    else:
        statuses = check_all()
        print_status(statuses, as_json=args.json)
        success = all(s.healthy for s in statuses)

        if not args.json:
            print()
            if success:
                print("✓ All services healthy!")
            else:
                print("✗ Some services unhealthy")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
