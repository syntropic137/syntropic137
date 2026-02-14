#!/usr/bin/env python3
"""
AEF Interactive Setup Wizard.

Zero-dependency setup script (Python 3.12 stdlib only) that takes a developer
from `git clone` to a fully running AEF stack in one command.

Usage:
    python infra/scripts/setup.py                    # Full interactive setup
    python infra/scripts/setup.py --skip-github      # Skip GitHub App config
    python infra/scripts/setup.py --non-interactive  # Read from env / .env
    python infra/scripts/setup.py --stage <name>     # Re-run a single stage

Stages:
    check_prerequisites, init_submodules, generate_secrets,
    configure_github_app, configure_env, configure_cloudflare,
    configure_smee, build_and_start, wait_for_health,
    seed_workflows, print_summary
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
INFRA_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = INFRA_DIR.parent
COMPOSE_DIR = INFRA_DIR / "docker" / "compose"
SECRETS_DIR = INFRA_DIR / "docker" / "secrets"
ENV_EXAMPLE = INFRA_DIR / ".env.example"
ENV_FILE = INFRA_DIR / ".env"

REQUIRED_PORTS = {
    80: "UI (nginx)",
    5432: "PostgreSQL",
    8000: "Dashboard API",
    8080: "Collector",
    9000: "MinIO API",
    9001: "MinIO Console",
    50051: "Event Store gRPC",
    6379: "Redis",
}

STAGES = [
    "check_prerequisites",
    "init_submodules",
    "generate_secrets",
    "configure_github_app",
    "configure_env",
    "configure_cloudflare",
    "configure_smee",
    "build_and_start",
    "wait_for_health",
    "seed_workflows",
    "print_summary",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def banner(text: str) -> None:
    width = 60
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)
    print()


def step(text: str) -> None:
    print(f"  -> {text}")


def ok(text: str) -> None:
    print(f"  [OK] {text}")


def warn(text: str) -> None:
    print(f"  [WARN] {text}")


def fail(text: str) -> None:
    print(f"  [FAIL] {text}")


def prompt(text: str, default: str = "") -> str:
    """Prompt user for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    value = input(f"  {text}{suffix}: ").strip()
    return value or default


def confirm(text: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    suffix = " [Y/n]" if default else " [y/N]"
    answer = input(f"  {text}{suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command."""
    step(f"Running: {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=cwd or PROJECT_ROOT,
        capture_output=capture,
        text=True,
        check=check,
    )


def cmd_version(cmd: str, flag: str = "--version") -> str | None:
    """Get version string from a command, or None if not found."""
    try:
        result = subprocess.run([cmd, flag], capture_output=True, text=True, check=False)
        output = result.stdout.strip() or result.stderr.strip()
        return output
    except FileNotFoundError:
        return None


def parse_version(version_str: str) -> tuple[int, ...] | None:
    """Extract a semver-like tuple from a version string."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if match:
        parts = [int(p) for p in match.groups() if p is not None]
        return tuple(parts)
    return None


def port_in_use(port: int) -> bool:
    """Check if a TCP port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def check_prerequisites(ctx: dict) -> bool:  # noqa: ARG001
    """Validate that required tools are installed."""
    banner("Stage: Check Prerequisites")
    all_ok = True

    # Docker
    ver = cmd_version("docker")
    if ver:
        parsed = parse_version(ver)
        if parsed and parsed >= (24,):
            ok(f"Docker {'.'.join(map(str, parsed))}")
        else:
            warn(f"Docker version {ver} — recommend 24+")
    else:
        fail("Docker not found. Install from https://docs.docker.com/get-docker/")
        all_ok = False

    # Docker Compose (v2 plugin)
    compose_ver = cmd_version("docker", flag="compose version")
    if compose_ver is None:
        # Try standalone docker-compose
        compose_ver = cmd_version("docker-compose")
    if compose_ver:
        parsed = parse_version(compose_ver)
        if parsed and parsed >= (2, 20):
            ok(f"Docker Compose {'.'.join(map(str, parsed))}")
        else:
            warn(f"Docker Compose {compose_ver} — recommend 2.20+")
    else:
        fail("Docker Compose not found")
        all_ok = False

    # Python
    py_ver = sys.version_info
    if py_ver >= (3, 12):
        ok(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        fail(f"Python {py_ver.major}.{py_ver.minor} — need 3.12+")
        all_ok = False

    # uv
    ver = cmd_version("uv")
    if ver:
        ok(f"uv: {ver.splitlines()[0]}")
    else:
        fail("uv not found. Install from https://docs.astral.sh/uv/")
        all_ok = False

    # just
    ver = cmd_version("just")
    if ver:
        ok(f"just: {ver.splitlines()[0]}")
    else:
        fail("just not found. Install from https://github.com/casey/just")
        all_ok = False

    # git
    ver = cmd_version("git")
    if ver:
        ok(f"git: {ver.splitlines()[0]}")
    else:
        fail("git not found")
        all_ok = False

    # Optional: node/pnpm
    for tool in ("node", "pnpm"):
        ver = cmd_version(tool)
        if ver:
            ok(f"{tool}: {ver.splitlines()[0]} (optional)")
        else:
            warn(f"{tool} not found (optional — needed for frontend dev)")

    # Port conflicts
    print()
    step("Checking ports...")
    conflicts = []
    for port, service in REQUIRED_PORTS.items():
        if port_in_use(port):
            conflicts.append((port, service))
            warn(f"Port {port} in use ({service})")
    if not conflicts:
        ok("All required ports are available")
    else:
        warn(f"{len(conflicts)} port(s) in use — services may fail to start")

    return all_ok


def init_submodules(ctx: dict) -> bool:  # noqa: ARG001
    """Initialize git submodules."""
    banner("Stage: Initialize Submodules")
    result = run(
        ["git", "submodule", "update", "--init", "--recursive"],
        check=False,
    )
    if result.returncode == 0:
        ok("Submodules initialized")
        return True
    fail("Submodule initialization failed")
    return False


def generate_secrets(ctx: dict) -> bool:  # noqa: ARG001
    """Generate deployment secrets via secrets_setup.py."""
    banner("Stage: Generate Secrets")
    secrets_script = SCRIPT_DIR / "secrets_setup.py"
    result = run(
        [sys.executable, str(secrets_script), "generate"],
        check=False,
    )
    if result.returncode == 0:
        ok("Secrets generated")
        return True
    # Return True even if optional secrets are missing — that's expected
    warn("Some optional secrets missing (expected for first-time setup)")
    return True


def configure_github_app(ctx: dict) -> bool:
    """Walk the user through GitHub App configuration."""
    banner("Stage: Configure GitHub App")

    if ctx.get("skip_github"):
        step("Skipped (--skip-github)")
        return True

    if ctx.get("non_interactive"):
        step("Non-interactive mode — reading from environment")
        ctx["github_app_id"] = os.environ.get("AEF_GITHUB_APP_ID", "")
        ctx["github_app_name"] = os.environ.get("AEF_GITHUB_APP_NAME", "")
        ctx["github_installation_id"] = os.environ.get("AEF_GITHUB_INSTALLATION_ID", "")
        if all([ctx["github_app_id"], ctx["github_app_name"], ctx["github_installation_id"]]):
            ok("GitHub App config read from environment")
            return True
        warn("GitHub App env vars not fully set — skipping")
        return True

    print("  To use AEF with GitHub, you need a GitHub App.")
    print("  If you don't have one yet, create it at:")
    print("    https://github.com/settings/apps/new")
    print()

    if not confirm("Configure GitHub App now?"):
        step("Skipping GitHub App configuration")
        ctx["skip_github"] = True
        return True

    ctx["github_app_id"] = prompt("GitHub App ID (numeric)")
    ctx["github_app_name"] = prompt("GitHub App name (slug)")
    ctx["github_installation_id"] = prompt("Installation ID")

    # Private key
    print()
    pem_dest = SECRETS_DIR / "github-private-key.pem"
    if pem_dest.exists():
        ok("Private key already exists at infra/docker/secrets/github-private-key.pem")
    else:
        pem_path = prompt("Path to .pem private key file")
        if pem_path and Path(pem_path).expanduser().exists():
            src = Path(pem_path).expanduser()
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, pem_dest)
            ok(f"Private key copied to {pem_dest}")
        else:
            warn("Private key not found — you'll need to copy it manually")
            print(f"    cp /path/to/your-app.pem {pem_dest}")

    # Show webhook secret for the user to paste into GitHub
    webhook_file = SECRETS_DIR / "github-webhook-secret.txt"
    if webhook_file.exists():
        webhook_secret = webhook_file.read_text().strip()
        print()
        print("  Webhook secret (paste into GitHub App settings):")
        print(f"    {webhook_secret}")
    else:
        warn("Webhook secret not found — run 'just secrets-generate' first")

    ok("GitHub App configured")
    return True


def configure_env(ctx: dict) -> bool:
    """Generate .env from .env.example with collected values."""
    banner("Stage: Configure Environment")

    if not ENV_EXAMPLE.exists():
        fail(f"Template not found: {ENV_EXAMPLE}")
        return False

    if (
        ENV_FILE.exists()
        and not ctx.get("non_interactive")
        and not confirm(f"{ENV_FILE} already exists. Overwrite?", default=False)
    ):
        ok("Keeping existing .env")
        return True

    content = ENV_EXAMPLE.read_text()

    # Substitute collected values
    substitutions = {}
    if ctx.get("github_app_id"):
        substitutions["AEF_GITHUB_APP_ID"] = ctx["github_app_id"]
    if ctx.get("github_app_name"):
        substitutions["AEF_GITHUB_APP_NAME"] = ctx["github_app_name"]
    if ctx.get("github_installation_id"):
        substitutions["AEF_GITHUB_INSTALLATION_ID"] = ctx["github_installation_id"]
    if ctx.get("cloudflare_tunnel_token"):
        substitutions["CLOUDFLARE_TUNNEL_TOKEN"] = ctx["cloudflare_tunnel_token"]
    if ctx.get("aef_domain"):
        substitutions["AEF_DOMAIN"] = ctx["aef_domain"]

    for key, value in substitutions.items():
        # Replace KEY= or KEY=default with KEY=value
        content = re.sub(
            rf"^{re.escape(key)}=.*$",
            f"{key}={value}",
            content,
            flags=re.MULTILINE,
        )

    ENV_FILE.write_text(content)
    ok(f"Environment file written to {ENV_FILE}")
    return True


def configure_cloudflare(ctx: dict) -> bool:
    """Optional Cloudflare Tunnel configuration."""
    banner("Stage: Configure Cloudflare Tunnel (Optional)")

    if ctx.get("non_interactive"):
        ctx["cloudflare_tunnel_token"] = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "")
        ctx["aef_domain"] = os.environ.get("AEF_DOMAIN", "")
        if ctx["cloudflare_tunnel_token"]:
            ok("Cloudflare config read from environment")
        else:
            step("No Cloudflare config in environment — skipping")
        return True

    if not confirm("Configure Cloudflare Tunnel for external access?", default=False):
        step("Skipping Cloudflare configuration")
        return True

    ctx["cloudflare_tunnel_token"] = prompt("Cloudflare Tunnel token")
    ctx["aef_domain"] = prompt("Domain (e.g., aef.yourdomain.com)")

    ok("Cloudflare Tunnel configured")
    return True


def configure_smee(ctx: dict) -> bool:
    """Optional smee.io webhook proxy configuration."""
    banner("Stage: Configure Webhook Proxy (Optional)")

    if ctx.get("non_interactive"):
        smee_url = os.environ.get("SMEE_URL", "")
        if smee_url:
            ok(f"SMEE_URL read from environment: {smee_url}")
        else:
            step("No SMEE_URL in environment — skipping")
        return True

    if ctx.get("skip_github"):
        step("Skipping (GitHub App not configured)")
        return True

    print("  smee.io forwards GitHub webhooks to your local machine.")
    print("  Create a channel at: https://smee.io/new")
    print()

    if not confirm("Configure smee.io webhook proxy?", default=False):
        step("Skipping smee configuration")
        return True

    smee_url = prompt("SMEE_URL")
    if smee_url:
        # Write to root .env for `just dev` integration
        root_env = PROJECT_ROOT / ".env"
        if root_env.exists():
            content = root_env.read_text()
            if "SMEE_URL=" in content:
                content = re.sub(
                    r"^SMEE_URL=.*$",
                    f"SMEE_URL={smee_url}",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content += f"\nSMEE_URL={smee_url}\n"
            root_env.write_text(content)
        else:
            root_env.write_text(f"SMEE_URL={smee_url}\n")
        ok(f"SMEE_URL written to {root_env}")

    return True


def build_and_start(ctx: dict) -> bool:
    """Build and start the Docker Compose stack."""
    banner("Stage: Build & Start Services")

    compose_files = ["-f", "docker-compose.yaml"]

    # Add homelab override if Cloudflare is configured
    if ctx.get("cloudflare_tunnel_token"):
        compose_files += ["-f", "docker-compose.homelab.yaml"]
        step("Using homelab compose (with Cloudflare Tunnel)")
    else:
        step("Using base compose (local mode)")

    env = os.environ.copy()
    if ENV_FILE.exists():
        # Load .env for docker compose
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

    result = subprocess.run(
        ["docker", "compose", *compose_files, "up", "-d", "--build"],
        cwd=COMPOSE_DIR,
        env=env,
        check=False,
    )

    if result.returncode == 0:
        ok("Services started")
        return True
    fail("Docker Compose failed — check output above")
    return False


def wait_for_health(ctx: dict) -> bool:  # noqa: ARG001
    """Wait for all services to become healthy."""
    banner("Stage: Health Check")

    health_script = SCRIPT_DIR / "health_check.py"
    result = run(
        [sys.executable, str(health_script), "--wait", "--timeout", "180"],
        check=False,
    )
    if result.returncode == 0:
        ok("All services healthy")
        return True
    warn("Some services may not be ready yet — check 'just health-check'")
    return True  # Non-blocking


def seed_workflows(ctx: dict) -> bool:  # noqa: ARG001
    """Seed workflow definitions."""
    banner("Stage: Seed Workflows")

    uv_path = shutil.which("uv")
    if not uv_path:
        warn("uv not found — skipping workflow seeding")
        return True

    result = run(
        ["uv", "run", "--package", "aef-cli", "aef", "workflow", "seed"],
        check=False,
    )
    if result.returncode == 0:
        ok("Workflows seeded")
        return True
    warn("Workflow seeding failed — you can retry with: just seed-workflows")
    return True  # Non-blocking


def print_summary(ctx: dict) -> bool:
    """Print access URLs and next steps."""
    banner("Setup Complete!")

    domain = ctx.get("aef_domain")
    if domain:
        print(f"  UI:            https://{domain}")
        print(f"  API:           https://api.{domain}")
        print(f"  API Docs:      https://api.{domain}/docs")
    else:
        print("  UI:            http://localhost:80")
        print("  Dashboard API: http://localhost:8000")
        print("  API Docs:      http://localhost:8000/docs")

    print("  MinIO Console: http://localhost:9001")
    print("  PostgreSQL:    localhost:5432")
    print("  Event Store:   localhost:50051")
    print("  Redis:         localhost:6379")

    print()
    print("  Useful commands:")
    print("    just health-check      Check service health")
    print("    just homelab-status    Show container status")
    print("    just homelab-logs      Follow service logs")
    print("    just seed-workflows    Re-seed workflow definitions")
    print()
    if ctx.get("skip_github"):
        print("  GitHub App not configured. To add it later:")
        print("    python infra/scripts/setup.py --stage configure_github_app")
        print()

    return True


# ---------------------------------------------------------------------------
# Stage Registry
# ---------------------------------------------------------------------------

STAGE_FUNCS: dict[str, callable] = {
    "check_prerequisites": check_prerequisites,
    "init_submodules": init_submodules,
    "generate_secrets": generate_secrets,
    "configure_github_app": configure_github_app,
    "configure_env": configure_env,
    "configure_cloudflare": configure_cloudflare,
    "configure_smee": configure_smee,
    "build_and_start": build_and_start,
    "wait_for_health": wait_for_health,
    "seed_workflows": seed_workflows,
    "print_summary": print_summary,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AEF Interactive Setup Wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available stages: {', '.join(STAGES)}",
    )
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Run infrastructure without GitHub App configuration",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Read configuration from env vars / existing .env (no prompts)",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        help="Re-run a specific setup stage",
    )
    args = parser.parse_args()

    ctx: dict = {
        "skip_github": args.skip_github,
        "non_interactive": args.non_interactive,
    }

    print()
    print("  ___  ___ ___   ___      _")
    print(" / _ \\| __| __| / __| ___| |_ _  _ _ __")
    print("| (_| | _|| _|  \\__ \\/ -_)  _| || | '_ \\")
    print(" \\__,_|___|_|   |___/\\___|\\__|\\__,_| .__/")
    print("                                   |_|")
    print()
    print("  Agentic Engineering Framework — Interactive Setup")
    print()

    if args.stage:
        # Run a single stage
        stage_fn = STAGE_FUNCS[args.stage]
        success = stage_fn(ctx)
        sys.exit(0 if success else 1)

    # Run all stages in order
    for stage_name in STAGES:
        stage_fn = STAGE_FUNCS[stage_name]
        success = stage_fn(ctx)
        if not success:
            print()
            fail(f"Stage '{stage_name}' failed. Fix the issue and re-run:")
            print(f"    python infra/scripts/setup.py --stage {stage_name}")
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
