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
    configure_github_app, configure_env, security_audit,
    configure_cloudflare, configure_smee, build_and_start,
    wait_for_health, seed_workflows, print_summary
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
INFRA_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = INFRA_DIR.parent
COMPOSE_DIR = PROJECT_ROOT / "docker"
SECRETS_DIR = INFRA_DIR / "docker" / "secrets"
ENV_EXAMPLE = INFRA_DIR / ".env.example"
ENV_FILE = INFRA_DIR / ".env"

REQUIRED_PORTS = {
    80: "UI (nginx)",
}

STAGES = [
    "check_prerequisites",
    "init_submodules",
    "generate_secrets",
    "configure_github_app",
    "configure_env",
    "security_audit",
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

    # Platform detection
    import platform

    os_name = platform.system()
    arch = platform.machine()
    print()
    step(f"Platform: {os_name} / {arch}")
    if os_name == "Darwin" and arch == "arm64":
        step("Apple Silicon — Rust event-store first build will be slow (~5-10 min)")

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
    """GitHub App configuration — manifest flow (new), manual, or skip."""
    banner("Stage: Configure GitHub App")

    if ctx.get("skip_github"):
        step("Skipped (--skip-github)")
        return True

    if ctx.get("non_interactive"):
        step("Non-interactive mode — reading from environment")
        ctx["github_app_id"] = os.environ.get("SYN_GITHUB_APP_ID", "")
        ctx["github_app_name"] = os.environ.get("SYN_GITHUB_APP_NAME", "")
        ctx["github_installation_id"] = os.environ.get("SYN_GITHUB_INSTALLATION_ID", "")
        if all([ctx["github_app_id"], ctx["github_app_name"], ctx["github_installation_id"]]):
            ok("GitHub App config read from environment")
            return True
        warn("GitHub App env vars not fully set — skipping")
        return True

    print("  AEF uses a GitHub App for secure agent commits, webhooks,")
    print("  and self-healing CI integration.")
    print()
    print("  Options:")
    print("    new      — Create a new GitHub App automatically (recommended)")
    print("    existing — Enter credentials for an app you already created")
    print("    skip     — Skip GitHub App configuration for now")
    print()

    choice = prompt("Create new app or use existing?", default="new")
    choice = choice.strip().lower()

    if choice == "new":
        return _configure_github_app_manifest(ctx)
    elif choice == "existing":
        return _configure_github_app_manual(ctx)
    else:
        step("Skipping GitHub App configuration")
        ctx["skip_github"] = True
        return True


def _configure_github_app_manifest(ctx: dict) -> bool:
    """Create a new GitHub App using the manifest flow."""
    from github_manifest import run_manifest_flow

    app_name = prompt("App name", default="syntropic137")
    org = prompt("GitHub org (leave blank for personal)", default="")
    webhook_url = ctx.get("webhook_url") or None

    print()
    try:
        result = run_manifest_flow(
            app_name=app_name,
            webhook_url=webhook_url,
            secrets_dir=SECRETS_DIR,
            org=org or None,
        )
    except TimeoutError as exc:
        fail(str(exc))
        print()
        print("  You can retry this stage with:")
        print("    python infra/scripts/setup.py --stage configure_github_app")
        return False
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as exc:
        fail(f"Manifest flow failed: {exc}")
        print()
        if confirm("Fall back to manual configuration?"):
            return _configure_github_app_manual(ctx)
        return False

    ctx["github_app_id"] = str(result["id"])
    ctx["github_app_name"] = result.get("slug", app_name)

    # Installation ID — auto-detected from setup_url callback or manual fallback
    installation_id = result.get("installation_id")
    if installation_id:
        ctx["github_installation_id"] = str(installation_id)
        ok(f"Installation ID auto-detected: {installation_id}")
    else:
        print()
        print("  The installation callback was not received.")
        print("  Enter the installation ID from the URL after installing.")
        print(
            "  (It's the numeric ID in the URL, e.g. https://github.com/settings/installations/12345)"
        )
        ctx["github_installation_id"] = prompt("Installation ID")

    ok("GitHub App created and configured via manifest flow")
    return True


def _configure_github_app_manual(ctx: dict) -> bool:
    """Manual GitHub App configuration (existing app)."""
    print()
    print("  Enter your existing GitHub App credentials.")
    print("  (Find them at https://github.com/settings/apps)")
    print()

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

    ok("GitHub App configured (manual)")
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
        substitutions["SYN_GITHUB_APP_ID"] = ctx["github_app_id"]
    if ctx.get("github_app_name"):
        substitutions["SYN_GITHUB_APP_NAME"] = ctx["github_app_name"]
    if ctx.get("github_installation_id"):
        substitutions["SYN_GITHUB_INSTALLATION_ID"] = ctx["github_installation_id"]
    if ctx.get("cloudflare_tunnel_token"):
        substitutions["CLOUDFLARE_TUNNEL_TOKEN"] = ctx["cloudflare_tunnel_token"]
    if ctx.get("syn_domain"):
        substitutions["SYN_DOMAIN"] = ctx["syn_domain"]

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


# ---------------------------------------------------------------------------
# Security Audit Helpers
# ---------------------------------------------------------------------------


def _audit_file_security() -> tuple[int, int]:
    """Check file permissions and secret hygiene. Returns (warnings, info)."""
    warnings = 0

    # PEM file permissions
    pem_path = SECRETS_DIR / "github-private-key.pem"
    if pem_path.exists():
        try:
            mode = pem_path.stat().st_mode
            if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
                warn("Private key has loose permissions — should be 600")
                step(f"  Fix: chmod 600 {pem_path}")
                warnings += 1
            else:
                ok("Private key permissions are restrictive (600)")
        except OSError:
            warn("Could not check private key permissions")
            warnings += 1
    else:
        step("Private key not yet created — skipping permission check")

    # Webhook secret
    webhook_path = SECRETS_DIR / "github-webhook-secret.txt"
    if webhook_path.exists():
        secret = webhook_path.read_text().strip()
        if len(secret) < 32:
            warn(f"Webhook secret is short ({len(secret)} chars) — recommend >= 32")
            warnings += 1
        else:
            ok(f"Webhook secret length OK ({len(secret)} chars)")
    else:
        step("Webhook secret not yet created — skipping")

    # Secrets dir .gitignore
    gitignore = SECRETS_DIR / ".gitignore"
    if SECRETS_DIR.exists():
        if gitignore.exists():
            gi_text = gitignore.read_text()
            gi_lines = [ln.strip() for ln in gi_text.splitlines()]
            # Check that plain-text secrets are ignored (either a bare '*'
            # wildcard or specific '*.txt' / '*.pem' patterns).
            has_blanket = "*" in gi_lines
            has_specific = "*.txt" in gi_lines and "*.pem" in gi_lines
            if has_blanket or has_specific:
                ok("Secrets directory has .gitignore blocking plain-text secrets")
            else:
                warn("Secrets .gitignore may not block plain-text files")
                step(f"  Ensure *.txt and *.pem are listed in {gitignore}")
                warnings += 1
        else:
            warn("Secrets directory missing .gitignore")
            step(f"  Fix: echo '*.txt\\n*.pem' > {gitignore}")
            warnings += 1

    # Misplaced PEM files
    for search_dir in [PROJECT_ROOT, INFRA_DIR]:
        for pem in search_dir.glob("*.pem"):
            if pem.parent == SECRETS_DIR:
                continue
            warn(f"PEM file found outside secrets dir: {pem.relative_to(PROJECT_ROOT)}")
            step(f"  Move to: {SECRETS_DIR}/")
            warnings += 1

    return warnings, 0


def _audit_network_security() -> tuple[int, int]:
    """Check Docker Compose for host-published ports. Returns (warnings, info)."""
    warnings = 0
    compose_file = COMPOSE_DIR / "docker-compose.selfhost.yaml"
    if not compose_file.exists():
        step("docker-compose.yaml not found — skipping network audit")
        return 0, 0

    compose_text = compose_file.read_text()

    # Parse service blocks and check for host port mappings.
    # We look for each internal service and flag if it exposes ports to the host.
    internal_services = {
        "postgres": "PostgreSQL",
        "event-store": "EventStoreDB",
        "redis": "Redis",
        "syn-dashboard": "Dashboard API",
        "minio": "MinIO",
    }

    for svc_key, label in internal_services.items():
        # Find the service block: starts at `^  <service>:` and extends
        # until the next top-level service or section.
        pattern = rf"(?m)^  {re.escape(svc_key)}:\n((?:(?!^  \w).*\n)*)"
        match = re.search(pattern, compose_text)
        if not match:
            continue
        block = match.group(1)
        if re.search(r"^\s+ports:", block, re.MULTILINE):
            warn(f"{label} ({svc_key}) has host-published ports")
            warnings += 1
        else:
            ok(f"{label} — no host port exposure")

    return warnings, 0


def _audit_github_app(ctx: dict) -> tuple[int, int]:  # noqa: ARG001
    """Check GitHub App configuration. Returns (warnings, info)."""
    warnings = 0
    info = 0

    pem_path = SECRETS_DIR / "github-private-key.pem"
    if pem_path.exists():
        content = pem_path.read_text()
        if "BEGIN RSA PRIVATE KEY" in content or "BEGIN PRIVATE KEY" in content:
            ok("Private key contains valid PEM header")
        else:
            warn("Private key missing expected PEM header")
            warnings += 1
    else:
        step("Private key not found — GitHub App not yet configured")

    # Permissions education (informational)
    try:
        from github_manifest import DEFAULT_PERMISSIONS

        print()
        step("GitHub App permissions (from manifest):")
        for perm, level in DEFAULT_PERMISSIONS.items():
            print(f"       {perm}: {level}")
        info += 1

        # Check for dangerous permissions
        if DEFAULT_PERMISSIONS.get("workflows") == "write":
            warn("workflows:write is set — this allows modifying GitHub Actions workflows")
            step("  Consider removing unless AEF needs to create/edit workflow files")
            warnings += 1
        else:
            ok("workflows:write not requested (good)")
    except ImportError:
        step("Could not load manifest permissions — skipping review")

    # Webhook secret configured
    webhook_path = SECRETS_DIR / "github-webhook-secret.txt"
    if pem_path.exists() and not webhook_path.exists():
        warn("GitHub App exists but webhook secret is missing")
        warnings += 1

    return warnings, info


def _audit_environment() -> tuple[int, int]:
    """Check environment configuration. Returns (warnings, info)."""
    warnings = 0

    # .env not tracked by git
    if ENV_FILE.exists():
        try:
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(ENV_FILE)],
                capture_output=True,
                text=True,
                check=False,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                warn(".env is tracked by git — add to .gitignore")
                warnings += 1
            else:
                ok(".env is not tracked by git")
        except FileNotFoundError:
            pass  # git not available

    # Default credential checks
    if ENV_FILE.exists():
        env_content = ENV_FILE.read_text()
        if "POSTGRES_PASSWORD=syn_dev_password" in env_content:
            warn("POSTGRES_PASSWORD is still the default — change for production")
            warnings += 1
        if "MINIO_ROOT_PASSWORD=minioadmin" in env_content:
            warn("MINIO_ROOT_PASSWORD is still the default — change for production")
            warnings += 1
    else:
        step(".env not created yet — skipping credential check")

    return warnings, 0


def security_audit(ctx: dict) -> bool:
    """Validate security posture — warnings only, never blocks setup."""
    banner("Stage: Security Audit (Tier 1)")

    print("  Security tier: Tier 1 (single-tenant, localhost trust)")
    print("  All checks are advisory — nothing will block setup.")
    print()

    total_warnings = 0
    total_info = 0

    # File security
    step("File security...")
    w, i = _audit_file_security()
    total_warnings += w
    total_info += i
    print()

    # Network security
    step("Network security...")
    w, i = _audit_network_security()
    total_warnings += w
    total_info += i
    print()

    # GitHub App
    step("GitHub App configuration...")
    w, i = _audit_github_app(ctx)
    total_warnings += w
    total_info += i
    print()

    # Environment
    step("Environment configuration...")
    w, i = _audit_environment()
    total_warnings += w
    total_info += i
    print()

    # Summary
    if total_warnings == 0:
        ok("Security audit passed — no warnings")
    else:
        warn(f"Security audit complete — {total_warnings} warning(s)")
        step("These are advisory for Tier 1 (localhost). Review before exposing externally.")

    return True  # Never blocks


def configure_cloudflare(ctx: dict) -> bool:
    """Optional Cloudflare Tunnel configuration."""
    banner("Stage: Configure Cloudflare Tunnel (Optional)")

    if ctx.get("non_interactive"):
        ctx["cloudflare_tunnel_token"] = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "")
        ctx["syn_domain"] = os.environ.get("SYN_DOMAIN", "")
        if ctx["cloudflare_tunnel_token"]:
            ok("Cloudflare config read from environment")
        else:
            step("No Cloudflare config in environment — skipping")
        return True

    if not confirm("Configure Cloudflare Tunnel for external access?", default=False):
        step("Skipping Cloudflare configuration")
        return True

    ctx["cloudflare_tunnel_token"] = prompt("Cloudflare Tunnel token")
    ctx["syn_domain"] = prompt("Domain (e.g., syn.yourdomain.com)")

    ok("Cloudflare Tunnel configured")
    return True


def configure_smee(ctx: dict) -> bool:
    """Optional smee.io webhook proxy configuration."""
    banner("Stage: Configure Webhook Proxy (Optional)")

    if ctx.get("non_interactive"):
        smee_url = os.environ.get("DEV__SMEE_URL", "")
        if smee_url:
            ok(f"DEV__SMEE_URL read from environment: {smee_url}")
        else:
            step("No DEV__SMEE_URL in environment — skipping")
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

    smee_url = prompt("DEV__SMEE_URL")
    if smee_url:
        # Write to root .env for `just dev` integration
        root_env = PROJECT_ROOT / ".env"
        if root_env.exists():
            content = root_env.read_text()
            if "DEV__SMEE_URL=" in content:
                content = re.sub(
                    r"^DEV__SMEE_URL=.*$",
                    f"DEV__SMEE_URL={smee_url}",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content += f"\nDEV__SMEE_URL={smee_url}\n"
            root_env.write_text(content)
        else:
            root_env.write_text(f"DEV__SMEE_URL={smee_url}\n")
        ok(f"DEV__SMEE_URL written to {root_env}")

    return True


def build_and_start(ctx: dict) -> bool:
    """Build and start the Docker Compose stack."""
    banner("Stage: Build & Start Services")

    compose_files = [
        "-f",
        "docker/docker-compose.yaml",
        "-f",
        "docker/docker-compose.selfhost.yaml",
    ]

    # Add Cloudflare overlay if tunnel is configured
    if ctx.get("cloudflare_tunnel_token"):
        compose_files += ["-f", "docker/docker-compose.cloudflare.yaml"]
        step("Using selfhost compose (with Cloudflare Tunnel)")
    else:
        step("Using selfhost compose (local mode)")

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
        cwd=PROJECT_ROOT,
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
        ["uv", "run", "--package", "syn-cli", "syn", "workflow", "seed"],
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

    domain = ctx.get("syn_domain")
    if domain:
        print(f"  UI:            https://{domain}")
        print(f"  API:           https://api.{domain}")
        print(f"  API Docs:      https://api.{domain}/docs")
    else:
        print("  UI:            http://localhost:80")
        print("  Dashboard API: http://localhost:8000")
        print("  API Docs:      http://localhost:8000/docs")

    print()
    print("  Internal services (Docker network only — not exposed to host):")
    print("    PostgreSQL, EventStoreDB, Redis, MinIO, Collector")
    print()
    print("  Security: Tier 1 (single-tenant) — no API auth, Docker network isolation.")
    print("  Run 'just setup --stage security_audit' to re-check security posture.")

    print()
    print("  Useful commands:")
    print("    just health-check      Check service health")
    print("    just selfhost-status    Show container status")
    print("    just selfhost-logs      Follow service logs")
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
    "security_audit": security_audit,
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
    print("  Syntropic137 — Interactive Setup")
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
