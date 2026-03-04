#!/usr/bin/env python3
"""
Syn137 Turnkey Setup Wizard.

Zero-dependency setup script (Python 3.12 stdlib only) that takes a user
from ``git clone`` to a fully running Syn137 stack in one command.

Design Philosophy — Superconducting Onboarding
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Syn137 is a powerful system, but power means nothing if nobody can get it
running.  Every manual step, missing file, or unclear prompt is friction
that kills adoption.  This wizard exists to make ``just setup`` a true
turnkey experience:

  - **One command, answer prompts, running stack.**  No README scavenger
    hunts, no "now copy this file", no silent failures.
  - **Browser-assisted flows.**  When we need the user to create something
    external (Cloudflare tunnel, GitHub App), we open the right page for
    them instead of making them find it.
  - **Secrets written end-to-end.**  Every value collected by the wizard is
    written to the file that Docker Compose actually reads.  Collecting a
    value and not wiring it is worse than not collecting it at all.
  - **Sensible defaults, skip-friendly.**  Stages default to the
    recommended path (e.g., Cloudflare=Yes) but can always be skipped.
  - **Re-runnable stages.**  Any single stage can be re-run with
    ``--stage <name>`` without blowing away prior work.

The lower the friction, the more adoption.  Optimise for the first-run
experience above all else.

Usage:
    just setup                    # Full interactive setup
    just setup --skip-github      # Skip GitHub App config
    just setup --non-interactive  # Read from env / .env
    just setup --stage <name>     # Re-run a single stage

Stages:
    check_prerequisites, init_submodules, generate_secrets,
    configure_1password, validate_environment, configure_cloudflare,
    configure_smee, configure_github_app, configure_env,
    security_audit, build_and_start, wait_for_health,
    seed_workflows, print_summary
"""

from __future__ import annotations

import argparse
import binascii
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import urllib.error
import webbrowser
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

from shared import (
    COMPOSE_SELFHOST,
    ENV_APP_ENVIRONMENT,
    ENV_CLOUDFLARE_TUNNEL_TOKEN,
    ENV_DEPLOY_ENV,
    ENV_EXAMPLE,
    ENV_FILE,
    ENV_GITHUB_APP_ID,
    ENV_GITHUB_APP_NAME,
    ENV_GITHUB_PRIVATE_KEY,
    ENV_GITHUB_WEBHOOK_SECRET,
    ENV_INCLUDE_OP_CLI,
    ENV_OP_VAULT,
    ENV_SYN_DOMAIN,
    INFRA_DIR,
    PORT_UI,
    PROJECT_ROOT,
    SCRIPTS_DIR,
    SECRETS_DIR,
    compose_file_args,
    format_access_urls,
    parse_env_file,
)

REQUIRED_PORTS = {
    PORT_UI: "UI (nginx)",
}

# ---------------------------------------------------------------------------
# SetupContext — typed wizard state
# ---------------------------------------------------------------------------


@dataclass
class SetupContext:
    """Wizard state passed between stages.

    All fields have safe defaults so the context can be constructed with
    just the CLI flags and progressively populated by each stage.

    Producers and consumers:
      skip_github            — main() → configure_github_app
      non_interactive        — main() → all stages
      github_app_id          — configure_github_app → configure_env
      github_app_name        — configure_github_app → configure_env
      github_private_key_b64 — configure_github_app → configure_env
      github_webhook_secret  — configure_github_app → configure_env
      cloudflare_tunnel_token — configure_cloudflare → configure_env, configure_smee
      syn_domain             — configure_cloudflare → configure_env, print_summary
      needs_smee_fallback    — configure_cloudflare → configure_smee
      webhook_url            — configure_smee → configure_github_app
      op_vault               — configure_1password → validate_environment, configure_env
      include_op_cli         — configure_1password → configure_env
      op_fields              — validate_environment → configure_cloudflare, configure_github_app
    """

    skip_github: bool = False
    non_interactive: bool = False
    github_app_id: str = ""
    github_app_name: str = ""
    github_private_key_b64: str = ""
    github_webhook_secret: str = ""
    cloudflare_tunnel_token: str = ""
    syn_domain: str = ""
    needs_smee_fallback: bool = False
    webhook_url: str = ""
    op_vault: str = ""
    include_op_cli: str = ""
    op_fields: set[str] | None = None


# Stage order matters:
#   1. 1Password first — so vault creds are available to later stages.
#   2. Cloudflare + smee — so webhook_url exists for the GitHub App manifest.
#   3. GitHub App — needs both vault creds and webhook_url.
#   4. configure_env — writes defaults (APP_ENVIRONMENT, DEPLOY_ENV) and acts
#      as a safety net.  Collection stages write their own values to .env
#      immediately via _update_env_file() so --stage X works in isolation.
#   5. Security audit — reads .env, so runs after configure_env.
STAGES = [
    "check_prerequisites",
    "init_submodules",
    "generate_secrets",
    "configure_1password",
    "validate_environment",
    "configure_cloudflare",
    "configure_smee",
    "configure_github_app",  # needs webhook_url from cloudflare/smee
    "configure_env",  # must follow all collection stages
    "security_audit",  # reads .env, so runs after configure_env
    "build_and_start",
    "wait_for_health",
    "seed_workflows",
    "print_summary",
]

# ---------------------------------------------------------------------------
# Terminal colours & helpers
# ---------------------------------------------------------------------------

# ANSI escape codes — disabled automatically when output is not a terminal
# (piped to file, CI, etc.) so we never pollute logs with escape sequences.
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_BOLD = "\033[1m" if _USE_COLOR else ""
_DIM = "\033[2m" if _USE_COLOR else ""
_RST = "\033[0m" if _USE_COLOR else ""
_GREEN = "\033[32m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_CYAN = "\033[36m" if _USE_COLOR else ""
_BLUE = "\033[34m" if _USE_COLOR else ""
_PURPLE = "\033[35m" if _USE_COLOR else ""


def banner(text: str) -> None:
    width = 60
    print()
    print(f"{_CYAN}{_BOLD}{'=' * width}{_RST}")
    print(f"  {_BOLD}{text}{_RST}")
    print(f"{_CYAN}{_BOLD}{'=' * width}{_RST}")
    print()


def step(text: str) -> None:
    print(f"  {_BLUE}->{_RST} {text}")


def ok(text: str) -> None:
    print(f"  {_GREEN}{_BOLD}[OK]{_RST} {text}")


def warn(text: str) -> None:
    print(f"  {_YELLOW}{_BOLD}[WARN]{_RST} {text}")


def fail(text: str) -> None:
    print(f"  {_RED}{_BOLD}[FAIL]{_RST} {text}")


def hint(text: str) -> None:
    """Dimmed helper text for instructions the user can skim."""
    print(f"  {_DIM}{text}{_RST}")


def callout(text: str) -> None:
    """Purple task header — the things the user needs to DO."""
    print(f"  {_PURPLE}{_BOLD}>{_RST} {_PURPLE}{text}{_RST}")


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
        # Split flag so "compose version" becomes ["compose", "version"]
        args = [cmd, *flag.split()]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
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


def check_prerequisites(ctx: SetupContext) -> bool:  # noqa: ARG001
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
    os_name = platform.system()
    arch = platform.machine()
    print()
    step(f"Platform: {os_name} / {arch}")
    if os_name == "Darwin" and arch == "arm64":
        step("Apple Silicon — Rust event-store first build will be slow (~5-10 min)")

    return all_ok


def init_submodules(ctx: SetupContext) -> bool:  # noqa: ARG001
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


def generate_secrets(ctx: SetupContext) -> bool:  # noqa: ARG001
    """Generate deployment secrets via secrets_setup.py."""
    banner("Stage: Generate Secrets")
    secrets_script = SCRIPTS_DIR / "secrets_setup.py"
    result = run(
        [sys.executable, str(secrets_script), "generate"],
        check=False,
    )
    if result.returncode == 0:
        ok("Secrets generated")
        return True
    if result.returncode == 1:
        # Exit code 1 = optional secrets missing (expected for first-time setup)
        warn("Some optional secrets missing (expected for first-time setup)")
        return True
    fail(f"secrets_setup.py failed with exit code {result.returncode}")
    return False


def configure_github_app(ctx: SetupContext) -> bool:
    """GitHub App configuration — manifest flow (new), manual, or skip."""
    banner("Stage: Configure GitHub App")

    if ctx.skip_github:
        step("Skipped (--skip-github)")
        return True

    if ctx.non_interactive:
        step("Non-interactive mode — reading from environment")
        ctx.github_app_id = os.environ.get(ENV_GITHUB_APP_ID, "")
        ctx.github_app_name = os.environ.get(ENV_GITHUB_APP_NAME, "")
        if all([ctx.github_app_id, ctx.github_app_name]):
            ok("GitHub App config read from environment")
            return True
        warn("GitHub App env vars not fully set — skipping")
        return True

    # Check if GitHub App is already fully configured (1Password or .env)
    op_fields = _get_op_fields(ctx)
    env_vals = parse_env_file(ENV_FILE)
    gh_keys = {
        ENV_GITHUB_APP_ID,
        ENV_GITHUB_APP_NAME,
        ENV_GITHUB_PRIVATE_KEY,
        ENV_GITHUB_WEBHOOK_SECRET,
    }
    has_all_in_op = gh_keys.issubset(op_fields)
    has_all_in_env = all(
        os.environ.get(k, "").strip() or env_vals.get(k, "").strip() for k in gh_keys
    )
    if has_all_in_op or has_all_in_env:
        source = "1Password" if has_all_in_op else ".env"
        ok(f"GitHub App already fully configured ({source})")
        if not confirm("Reconfigure GitHub App?", default=False):
            step("Keeping existing GitHub App configuration")
            # Populate ctx from existing values for configure_env
            ctx.github_app_id = os.environ.get(ENV_GITHUB_APP_ID, "") or env_vals.get(
                ENV_GITHUB_APP_ID, ""
            )
            ctx.github_app_name = os.environ.get(ENV_GITHUB_APP_NAME, "") or env_vals.get(
                ENV_GITHUB_APP_NAME, ""
            )
            return True
        print()

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
        ctx.skip_github = True
        return True


def _persist_github_app_to_env(ctx: SetupContext) -> None:
    """Write GitHub App credentials from ctx to .env immediately."""
    env_updates: dict[str, str] = {}
    if ctx.github_app_id:
        env_updates[ENV_GITHUB_APP_ID] = ctx.github_app_id
    if ctx.github_app_name:
        env_updates[ENV_GITHUB_APP_NAME] = ctx.github_app_name
    if ctx.github_private_key_b64:
        env_updates[ENV_GITHUB_PRIVATE_KEY] = ctx.github_private_key_b64
    if ctx.github_webhook_secret:
        env_updates[ENV_GITHUB_WEBHOOK_SECRET] = ctx.github_webhook_secret
    _update_env_file(env_updates)


def _configure_github_app_manifest(ctx: SetupContext) -> bool:
    """Create a new GitHub App using the manifest flow."""
    from github_manifest import run_manifest_flow

    app_name = prompt("App name", default="syntropic137")
    org = prompt("GitHub org (leave blank for personal)", default="")
    webhook_url = ctx.webhook_url or None

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
        print("    just setup --stage configure_github_app")
        return False
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as exc:
        fail(f"Manifest flow failed: {exc}")
        print()
        if confirm("Fall back to manual configuration?"):
            return _configure_github_app_manual(ctx)
        return False

    ctx.github_app_id = str(result["id"])
    ctx.github_app_name = result.get("slug", app_name)

    # Extract crown-jewel secrets into ctx for .env injection
    import base64 as _b64

    pem = result.get("pem", "")
    if pem:
        ctx.github_private_key_b64 = _b64.b64encode(pem.encode()).decode()
    webhook_secret = result.get("webhook_secret", "")
    if webhook_secret:
        ctx.github_webhook_secret = webhook_secret

    _persist_github_app_to_env(ctx)

    ok("GitHub App created and configured via manifest flow")
    return True


def _configure_github_app_manual(ctx: SetupContext) -> bool:
    """Manual GitHub App configuration (existing app)."""
    import base64

    print()
    print("  Enter your existing GitHub App credentials.")
    print("  (Find them at https://github.com/settings/apps)")
    print()

    ctx.github_app_id = prompt("GitHub App ID (numeric)")
    ctx.github_app_name = prompt("GitHub App name (slug)")

    # Private key — base64-encode and store in ctx for .env
    print()
    pem_dest = SECRETS_DIR / "github-private-key.pem"
    pem_text = ""
    if pem_dest.exists():
        ok("Private key found at infra/docker/secrets/github-private-key.pem")
        pem_text = pem_dest.read_text()
    else:
        pem_path = prompt("Path to .pem private key file")
        if pem_path and Path(pem_path).expanduser().exists():
            src = Path(pem_path).expanduser()
            pem_text = src.read_text()
            # Keep a backup copy in secrets dir (not consumed by Docker Compose)
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, pem_dest)
            ok(f"Private key backup saved to {pem_dest}")
        else:
            warn("Private key not found — you'll need to add it to .env manually")
            hint("  base64 < /path/to/your-app.pem | tr -d '\\n'")

    if pem_text:
        ctx.github_private_key_b64 = base64.b64encode(pem_text.encode()).decode()

    # Webhook secret — generate or read existing, store in ctx for .env
    import secrets as _secrets

    webhook_file = SECRETS_DIR / "github-webhook-secret.txt"
    if webhook_file.exists():
        webhook_secret = webhook_file.read_text().strip()
    else:
        webhook_secret = _secrets.token_hex(32)

    ctx.github_webhook_secret = webhook_secret
    print()
    print("  Webhook secret (paste into GitHub App settings):")
    print(f"    {webhook_secret}")

    _persist_github_app_to_env(ctx)

    # Remind user to subscribe to the right webhook events — the manifest
    # flow does this automatically, but existing apps need manual config.
    print()
    callout("Subscribe to webhook events")
    step(f"Go to https://github.com/settings/apps/{ctx.github_app_name}")
    step("Permissions & events → Subscribe to events → check:")
    step(f"  {_PURPLE}Check run{_RST}, {_PURPLE}Issue comment{_RST}, {_PURPLE}Pull request{_RST},")
    step(f"  {_PURPLE}Pull request review{_RST}, {_PURPLE}Push{_RST}")
    step("Save changes")
    print()
    input("  Press Enter when done...")

    ok("GitHub App configured (manual)")
    return True


def configure_env(ctx: SetupContext) -> bool:
    """Ensure .env exists and write any remaining defaults / ctx values.

    Collection stages (configure_cloudflare, configure_github_app, etc.)
    already write their values to .env immediately via _update_env_file().
    This stage handles:
      1. Creating .env from template if it doesn't exist yet.
      2. Writing non-secret defaults (APP_ENVIRONMENT, DEPLOY_ENV, OP_VAULT).
      3. Writing any ctx values that earlier stages might have collected but
         not yet persisted (belt-and-suspenders).
    """
    banner("Stage: Configure Environment")

    # Build substitutions — collection stages already wrote secrets to .env,
    # but we include ctx values here as a safety net for full-wizard runs.
    substitutions: dict[str, str] = {}
    if ctx.github_app_id:
        substitutions[ENV_GITHUB_APP_ID] = ctx.github_app_id
    if ctx.github_app_name:
        substitutions[ENV_GITHUB_APP_NAME] = ctx.github_app_name
    if ctx.github_private_key_b64:
        substitutions[ENV_GITHUB_PRIVATE_KEY] = ctx.github_private_key_b64
    if ctx.github_webhook_secret:
        substitutions[ENV_GITHUB_WEBHOOK_SECRET] = ctx.github_webhook_secret
    if ctx.cloudflare_tunnel_token:
        substitutions[ENV_CLOUDFLARE_TUNNEL_TOKEN] = ctx.cloudflare_tunnel_token
    if ctx.syn_domain:
        substitutions[ENV_SYN_DOMAIN] = ctx.syn_domain

    # Infer DEPLOY_ENV from what was configured — if the user set up a
    # Cloudflare tunnel, they're doing selfhost, not local dev.
    env_vals = parse_env_file(ENV_FILE) if ENV_FILE.exists() else {}
    has_tunnel = (
        ctx.cloudflare_tunnel_token or env_vals.get(ENV_CLOUDFLARE_TUNNEL_TOKEN, "").strip()
    )
    if has_tunnel:
        substitutions[ENV_DEPLOY_ENV] = "selfhost"

    # APP_ENVIRONMENT feeds the poka-yoke vault/environment mismatch guard.
    substitutions.setdefault(ENV_APP_ENVIRONMENT, "development")

    # 1Password settings from the configure_1password stage
    if ctx.op_vault:
        substitutions[ENV_OP_VAULT] = ctx.op_vault
    if ctx.include_op_cli:
        substitutions[ENV_INCLUDE_OP_CLI] = ctx.include_op_cli

    _update_env_file(substitutions)
    ok("Environment configured")

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

    # Webhook secret (now env var, check .env or environment)
    env_vals = parse_env_file(ENV_FILE)
    webhook_secret = (
        os.environ.get(ENV_GITHUB_WEBHOOK_SECRET, "").strip()
        or env_vals.get(ENV_GITHUB_WEBHOOK_SECRET, "").strip()
    )
    if webhook_secret:
        if len(webhook_secret) < 32:
            warn(f"Webhook secret is short ({len(webhook_secret)} chars) — recommend >= 32")
            warnings += 1
        else:
            ok(f"Webhook secret length OK ({len(webhook_secret)} chars)")
    else:
        step("Webhook secret not yet configured — skipping")

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
    compose_file = COMPOSE_SELFHOST
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
        "api": "API",
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


def _audit_github_app(ctx: SetupContext) -> tuple[int, int]:
    """Check GitHub App configuration. Returns (warnings, info)."""
    warnings = 0
    info = 0

    # Check private key — could be base64-encoded env var, 1Password, or raw PEM file
    import base64 as _b64

    op_fields = _get_op_fields(ctx)
    env_vals = parse_env_file(ENV_FILE)
    pem_b64 = (
        os.environ.get(ENV_GITHUB_PRIVATE_KEY, "").strip()
        or env_vals.get(ENV_GITHUB_PRIVATE_KEY, "").strip()
    )
    pem_path = SECRETS_DIR / "github-private-key.pem"

    if pem_b64:
        # Env var path: base64-encoded PEM — decode and validate
        try:
            decoded = _b64.b64decode(pem_b64).decode("utf-8", errors="replace")
            if "BEGIN RSA PRIVATE KEY" in decoded or "BEGIN PRIVATE KEY" in decoded:
                ok("Private key (env var, base64-encoded PEM) — valid")
            else:
                warn(f"{ENV_GITHUB_PRIVATE_KEY} is set but decoded content lacks PEM header")
                warnings += 1
        except (ValueError, binascii.Error):
            warn(f"{ENV_GITHUB_PRIVATE_KEY} is set but could not be base64-decoded")
            warnings += 1
    elif ENV_GITHUB_PRIVATE_KEY in op_fields:
        # Key is in 1Password but not resolved into env yet (runtime resolves it)
        ok("Private key configured in 1Password")
    elif pem_path.exists():
        # Legacy file path: raw PEM on disk
        content = pem_path.read_text()
        if "BEGIN RSA PRIVATE KEY" in content or "BEGIN PRIVATE KEY" in content:
            ok("Private key (file) contains valid PEM header")
        else:
            warn("Private key file missing expected PEM header")
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


def security_audit(ctx: SetupContext) -> bool:
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


def configure_cloudflare(ctx: SetupContext) -> bool:
    """Cloudflare Tunnel configuration (recommended for selfhost).

    This is the single highest-friction point in onboarding — the user needs
    to create an external resource (a Cloudflare tunnel) and paste back a
    token.  We reduce friction by:
      - Defaulting to Yes (most selfhost users want external access)
      - Opening the exact dashboard page in their browser
      - Extracting the token from the full install command automatically
      - Writing the token directly to the Docker secret file

    Vendor-specific logic (token parsing, URL construction, file persistence)
    lives in ``cloudflare_tunnel.py`` — this function is pure orchestration.
    """
    from cloudflare_tunnel import extract_token

    banner("Stage: Configure Cloudflare Tunnel (Recommended)")

    if ctx.non_interactive:
        ctx.cloudflare_tunnel_token = os.environ.get(ENV_CLOUDFLARE_TUNNEL_TOKEN, "")
        ctx.syn_domain = os.environ.get(ENV_SYN_DOMAIN, "")
        if ctx.cloudflare_tunnel_token:
            ok("Cloudflare tunnel token read from environment")
        else:
            step("No Cloudflare config in environment — skipping")
        return True

    # Re-run safety: if the token file already exists and .env has a domain,
    # offer to keep the existing config instead of redoing everything.
    # Re-run safety: check 1Password, .env, env var
    op_fields = _get_op_fields(ctx)
    existing_token = (
        os.environ.get(ENV_CLOUDFLARE_TUNNEL_TOKEN, "").strip()
        or parse_env_file(ENV_FILE).get(ENV_CLOUDFLARE_TUNNEL_TOKEN, "").strip()
    )
    token_in_op = ENV_CLOUDFLARE_TUNNEL_TOKEN in op_fields
    existing_domain = ctx.syn_domain or os.environ.get(ENV_SYN_DOMAIN, "")
    if existing_token or token_in_op:
        source = "1Password" if token_in_op else ".env"
        ok(f"Tunnel token already configured ({source})")
        if existing_domain:
            ok(f"Domain: {existing_domain}")
        if not confirm("Reconfigure Cloudflare Tunnel?", default=False):
            step("Keeping existing Cloudflare configuration")
            if existing_token:
                ctx.cloudflare_tunnel_token = existing_token
            if existing_domain:
                ctx.syn_domain = existing_domain
            return True
        print()

    # Lead with the "why" — users need to understand the purpose, not
    # just the mechanism.  The tunnel exists so GitHub can reach us.
    callout("GitHub needs to reach your machine to trigger agent jobs.")
    print()
    hint("Cloudflare Tunnel creates a secure public URL for webhooks —")
    hint("no port forwarding, no firewall changes, no static IP needed.")
    hint("Free tier is all you need. No credit card required.")
    print()
    # Be upfront about what's needed so there are no surprises after
    # they say yes.  If they don't have a domain, point them to smee.
    callout("What you'll need:")
    step(f"{_GREEN}FREE{_RST}  Cloudflare account")
    step(f"{_GREEN}~$10{_RST}  A domain on Cloudflare (or bring your own)")
    print()
    hint("Don't have a domain on Cloudflare yet? Here's how:")
    hint(f"  1. Go to {_BOLD}Account Home{_RST} on dash.cloudflare.com")
    hint(
        f"  2. {_BOLD}Buy a domain{_RST} (right there) or {_BOLD}+ Onboard a domain{_RST} you already own"
    )
    hint("  3. Point your registrar's nameservers to the ones Cloudflare gives you")
    hint("     (takes 5-30 min to propagate)")
    print()
    hint("No domain? No problem — choose 'n' and we'll use smee.io instead.")
    print()

    # Default=True because this is the recommended path for selfhost.
    # The old default=False contradicted the "(Recommended)" label.
    if not confirm("Configure Cloudflare Tunnel?", default=True):
        step("Skipping Cloudflare configuration")
        return True

    # One flow: open dashboard, user creates tunnel + adds route in the
    # same Cloudflare wizard, then comes back with the token and hostname.
    # No bouncing between pages, no separate "domain" step.
    zt_url = "https://one.dash.cloudflare.com"
    print()
    warn("If Cloudflare redirects you to dash.cloudflare.com after login,")
    warn("you need to navigate to Zero Trust manually. Use the link below.")
    print()
    step(f"Zero Trust dashboard: {_BOLD}{zt_url}{_RST}")
    print()
    if confirm("Open Cloudflare Zero Trust dashboard?", default=True):
        webbrowser.open(zt_url)
        ok("Opened browser")
        print()

    env_suffix = os.environ.get(ENV_APP_ENVIRONMENT, "dev")

    # Step-by-step with callout() for actions (bold, visible) and
    # step() for details.  No hint() for critical instructions —
    # grey/dim text was too easy to miss.
    callout("Step 1: Create the tunnel")
    print()
    step(f"In the Zero Trust dashboard ({_BOLD}{zt_url}{_RST}):")
    step(f"Networks  >  Connectors  >  {_PURPLE}+ Create a tunnel{_RST}")
    step(f"Type: {_PURPLE}Cloudflared{_RST}")
    step(f"Name: {_PURPLE}syn137-{env_suffix}{_RST}  {_DIM}(or whatever you like){_RST}")
    print()

    callout("Step 2: Copy the install command")
    print()
    # Buttery onboarding: Cloudflare shows a full shell command, not
    # a bare token.  We accept whatever they paste and extract it.
    raw = getpass("  Paste the install command or token (hidden): ")
    ctx.cloudflare_tunnel_token = extract_token(raw)

    if ctx.cloudflare_tunnel_token:
        ok("Tunnel token captured")
        # Write immediately so --stage configure_cloudflare persists the value
        _update_env_file({ENV_CLOUDFLARE_TUNNEL_TOKEN: ctx.cloudflare_tunnel_token})
        # If using 1Password, remind user to store there too for portability
        if ctx.op_vault:
            print()
            hint(f"You're using 1Password (vault: {ctx.op_vault}).")
            hint("Add CLOUDFLARE_TUNNEL_TOKEN to your syntropic137-config item")
            hint("so it resolves automatically on future deployments.")
    print()

    callout("Step 3: Add a published application route")
    print()
    step(f"Click the {_PURPLE}Published application routes{_RST} tab at the top")
    step(f"Click {_PURPLE}Add a published application route{_RST}")
    # cloudflared runs inside Docker on the same network as gateway (nginx),
    # which reverse-proxies to api:8000 with rate limiting, security
    # headers, WebSocket support, and SPA routing.  Always route through
    # nginx — never expose the raw API directly.
    step("Subdomain: pick yours  Domain: select from dropdown")
    step(f"Service type: {_PURPLE}HTTP{_RST}  URL: {_PURPLE}gateway:8081{_RST}")
    hint("Port 8081 enables basic auth on tunnel access (set SYN_API_PASSWORD in .env)")
    step(f"Click {_PURPLE}Save{_RST}")
    print()

    input("  Press Enter when done...")
    print()

    # Just grab the final hostname they configured.  One input.
    ctx.syn_domain = prompt(
        "What's the full hostname you set up? (e.g., syn137-dev.yourdomain.com, or blank)",
        default="",
    )

    if ctx.syn_domain:
        ok(f"Domain: {ctx.syn_domain}")
        _update_env_file({ENV_SYN_DOMAIN: ctx.syn_domain})
    else:
        ctx.needs_smee_fallback = True
        step("No domain — we'll set up smee.io for webhooks next.")

    ok("Cloudflare Tunnel configured")
    return True


def configure_smee(ctx: SetupContext) -> bool:
    """Webhook proxy configuration via smee.io.

    This is the zero-barrier fallback for receiving GitHub webhooks.
    If the user has a Cloudflare tunnel + domain, smee is optional.
    If they DON'T have a domain, smee is the only way webhooks can
    reach their machine — so we promote it to recommended.

    smee.io is free, instant, requires no account — just click a link.
    That's the kind of zero-friction path we want for first-timers.
    """
    # Dynamically adjust the framing based on whether the user has a
    # domain configured.  No domain = smee is their webhook lifeline.
    needs_fallback = ctx.needs_smee_fallback

    # If Cloudflare tunnel is configured with a domain, skip smee entirely.
    # smee is a dev tool — no reason to prompt for it when production
    # webhook delivery is already set up.
    env_vals = parse_env_file(ENV_FILE)
    has_tunnel = (
        bool(ctx.cloudflare_tunnel_token)
        or bool(env_vals.get(ENV_CLOUDFLARE_TUNNEL_TOKEN, "").strip())
        or ENV_CLOUDFLARE_TUNNEL_TOKEN in _get_op_fields(ctx)
    )
    has_domain = bool(ctx.syn_domain) or bool(env_vals.get(ENV_SYN_DOMAIN, "").strip())
    if has_tunnel and has_domain:
        banner("Stage: Configure Webhook Proxy (Skipped)")
        step("Cloudflare Tunnel is configured — smee.io not needed")
        return True

    if needs_fallback:
        banner("Stage: Configure Webhook Proxy (Recommended)")
    else:
        banner("Stage: Configure Webhook Proxy (Dev Only)")

    if ctx.non_interactive:
        smee_url = os.environ.get("DEV__SMEE_URL", "")
        if smee_url:
            ok(f"DEV__SMEE_URL read from environment: {smee_url}")
        else:
            step("No DEV__SMEE_URL in environment — skipping")
        return True

    if ctx.skip_github:
        step("Skipping (GitHub App not configured)")
        return True

    if needs_fallback:
        # They have no domain — smee is how webhooks will reach them.
        callout("You don't have a domain yet, so GitHub can't send webhooks")
        callout("to your machine directly. smee.io bridges that gap.")
        print()
        hint("smee.io is free, instant, and needs no account.")
        hint("It creates a public URL that forwards webhooks to localhost.")
        print()
        # Be honest: smee is a bridge, not a destination.
        warn("smee.io is great for getting started but can be fragile.")
        hint("For reliable automation, set up a Cloudflare domain later:")
        hint("  just setup --stage configure_cloudflare")
    else:
        hint("smee.io forwards GitHub webhooks to your local machine.")
        hint("Useful for development or as a backup webhook path.")
    print()

    # Open smee.io/new in the browser — one click to get a URL.
    # This is the ultimate zero-friction move: no signup, no config,
    # just click and copy.
    default_confirm = needs_fallback  # default=True when they need it
    if not confirm("Set up smee.io webhook proxy?", default=default_confirm):
        if needs_fallback:
            print()
            warn("Without a domain or smee, GitHub webhooks can't reach you.")
            warn("Automated workflows won't trigger. You can re-run this with:")
            step("just setup --stage configure_smee")
        else:
            step("Skipping smee configuration")
        return True

    if confirm("Open smee.io/new in your browser to create a channel?", default=True):
        webbrowser.open("https://smee.io/new")
        ok("Opened smee.io — copy the URL from the page")
        print()

    smee_url = prompt("Paste the smee.io URL")
    if smee_url:
        # Write to root .env for `just dev` integration
        _update_env_file(
            {"DEV__SMEE_URL": smee_url},
            target=PROJECT_ROOT / ".env",
        )

    return True


def _prompt_keychain_token(vault: str) -> None:
    """Ensure a 1Password SA token is stored in macOS Keychain for *vault*.

    On macOS: checks Keychain, prompts if missing, offers replacement if present.
    On Linux: prints the env var the user needs to export.
    """
    if platform.system() != "Darwin":
        svc = _keychain_service_name(vault)
        step("On Linux, set the vault-specific env var:")
        step(f"  export {svc}=ops_...")
        return

    existing = _keychain_read(vault)
    svc = _keychain_service_name(vault)

    if existing:
        ok(f"Token already in Keychain ({svc})")
        if confirm("Replace token?", default=False):
            token = getpass("  Paste new service account token (hidden): ")
            if token and _keychain_write(vault, token):
                ok(f"Token updated in Keychain as {svc}")
        return

    # No existing token — prompt for one
    token = getpass("  Paste service account token (hidden): ")
    if token and _keychain_write(vault, token):
        ok(f"Token stored in Keychain as {svc}")
    else:
        warn("No token provided — you can add it later via Keychain")


def configure_1password(ctx: SetupContext) -> bool:
    """Optional 1Password secret management configuration.

    Without this stage, users had to manually create the Keychain entry
    using an arcane ``security add-generic-password`` command they'd have
    to find in the docs.  Now the wizard does it for them.

    On macOS we store the service account token in Keychain (the OS-native
    credential store) so it never touches disk as plain text.  On Linux we
    print the env var they need to export — not ideal but there's no
    universal credential store to target.
    """
    banner("Stage: Configure 1Password (Optional)")

    if ctx.non_interactive:
        op_vault = os.environ.get(ENV_OP_VAULT, "")
        if op_vault:
            ctx.op_vault = op_vault
            ctx.include_op_cli = "1"
            ok("1Password config read from environment")
        else:
            step("No 1Password config in environment — skipping")
        return True

    # Detect existing configuration
    env_vals = parse_env_file(ENV_FILE)
    existing_vault = env_vals.get(ENV_OP_VAULT, "").strip()
    has_keychain_token = bool(existing_vault and _keychain_read(existing_vault))

    # Already fully configured — offer to keep or reconfigure
    if has_keychain_token:
        ok(f"1Password already configured (vault: {existing_vault}, token in Keychain)")
        if not confirm("Reconfigure 1Password?", default=False):
            ctx.op_vault = existing_vault
            ctx.include_op_cli = "1"
            step("Keeping existing 1Password configuration")
            return True
        # Reconfigure — prompt for vault then token
        print()
        vault = prompt("1Password vault name", default=existing_vault)
        ctx.op_vault = vault
        _prompt_keychain_token(vault)
        ctx.include_op_cli = "1"
        _update_env_file({ENV_OP_VAULT: vault, ENV_INCLUDE_OP_CLI: "1"})
        ok("1Password reconfigured")
        return True

    # Fresh setup — ask if they want 1Password at all
    if not confirm("Use 1Password for secret management?", default=False):
        step("Skipping 1Password — using .env for secrets")
        return True

    vault = prompt("1Password vault name", default=existing_vault or "syn137-dev")
    ctx.op_vault = vault
    _prompt_keychain_token(vault)
    ctx.include_op_cli = "1"
    _update_env_file({ENV_OP_VAULT: vault, ENV_INCLUDE_OP_CLI: "1"})
    ok("1Password configured")
    return True


# ---------------------------------------------------------------------------
# Environment Audit
# ---------------------------------------------------------------------------

# Variable groups for the environment audit table.
# Each group is (label, [(var_name, required)]).
# var_name ending in .txt/.pem → checked as secret file, else as env var.
_OP_ITEM_TITLE = "syntropic137-config"

ENV_AUDIT_GROUPS: list[tuple[str, list[tuple[str, bool]]]] = [
    (
        "Core",
        [
            (ENV_APP_ENVIRONMENT, True),
        ],
    ),
    (
        "GitHub App",
        [
            (ENV_GITHUB_APP_ID, True),
            (ENV_GITHUB_APP_NAME, True),
            (ENV_GITHUB_PRIVATE_KEY, True),
            (ENV_GITHUB_WEBHOOK_SECRET, True),
        ],
    ),
    (
        "Cloudflare (optional — for external access)",
        [
            (ENV_SYN_DOMAIN, False),
            (ENV_CLOUDFLARE_TUNNEL_TOKEN, False),
        ],
    ),
    (
        "LLM Provider (at least one)",
        [
            ("ANTHROPIC_API_KEY", False),
            ("CLAUDE_CODE_OAUTH_TOKEN", False),
        ],
    ),
    (
        "Database",
        [
            ("db-password.txt", True),
            ("redis-password.txt", True),
        ],
    ),
]


def _update_env_file(
    updates: dict[str, str],
    *,
    target: Path | None = None,
    template: Path | None = None,
    quiet: bool = False,
) -> None:
    """Merge key=value pairs into an .env file immediately.

    This is the single write-path for .env — every collection stage calls it
    right after capturing a value so that ``--stage X`` invocations persist
    their results even when ``configure_env`` runs in a separate process.

    Args:
        target: The .env file to update (default: ``ENV_FILE``).
        template: Template to bootstrap from if *target* doesn't exist
                  (default: ``ENV_EXAMPLE``).  Pass ``None`` explicitly to
                  skip templating (e.g. for the root ``.env``).
        quiet: Suppress per-key log lines.
    """
    if not updates:
        return

    env_file = target or ENV_FILE
    env_template = template if template is not None else (None if target else ENV_EXAMPLE)

    if env_file.exists():
        content = env_file.read_text()
    elif env_template and env_template.exists():
        content = env_template.read_text()
    else:
        # No template — start from scratch
        content = ""

    changed = []
    for key, value in updates.items():
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + f"\n{key}={value}\n"
        changed.append(key)

    # Atomic write: write to temp file then os.replace() for crash safety
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=env_file.parent,
        prefix=".env.",
        suffix=".tmp",
    )
    try:
        os.write(tmp_fd, content.encode())
    except BaseException:
        os.close(tmp_fd)
        Path(tmp_path).unlink()
        raise
    os.close(tmp_fd)
    try:
        Path(tmp_path).replace(env_file)
    except BaseException:
        Path(tmp_path).unlink()
        raise

    if not quiet:
        label = env_file.name
        for key in changed:
            if "KEY" in key or "SECRET" in key or "TOKEN" in key:
                ok(f"Wrote {key}=**** to {label}")
            else:
                ok(f"Wrote {key}={updates[key]} to {label}")


# ---------------------------------------------------------------------------
# Keychain helpers (macOS)
# ---------------------------------------------------------------------------
# Single source of truth for all Keychain operations.  Every read/write goes
# through these two functions so the flags (-a, -s, -w) are always consistent
# with the shell equivalent in selfhost-env.sh.


def _keychain_service_name(vault: str) -> str:
    """Derive the macOS Keychain service name for a 1Password vault.

    Must match selfhost-env.sh:
      ``SYN_OP_SERVICE_ACCOUNT_TOKEN_$(echo "$OP_VAULT" | tr '[:lower:]-' '[:upper:]_')``
    """
    vk = vault.upper().replace("-", "_")
    return f"SYN_OP_SERVICE_ACCOUNT_TOKEN_{vk}"


def _keychain_read(vault: str) -> str | None:
    """Read the 1Password SA token from macOS Keychain. Returns None if absent."""
    if platform.system() != "Darwin":
        return None
    svc = _keychain_service_name(vault)
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                os.environ.get("USER", "unknown"),
                "-s",
                svc,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        token = result.stdout.strip()
        return token if token and result.returncode == 0 else None
    except FileNotFoundError:
        return None


def _keychain_write(vault: str, token: str) -> bool:
    """Store the 1Password SA token in macOS Keychain. Returns success."""
    if platform.system() != "Darwin":
        return False
    svc = _keychain_service_name(vault)
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            os.environ.get("USER", "unknown"),
            "-s",
            svc,
            "-w",
            token,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        warn(f"Keychain write failed: {result.stderr.strip() or 'unknown error'}")
        return False
    return True


def _ensure_op_token(vault: str) -> None:
    """Load the service account token from macOS Keychain if not already set.

    Mirrors the justfile's Keychain lookup so ``op`` works even when the
    setup script is invoked outside of ``just``.
    """
    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
        return  # already set — nothing to do
    token = _keychain_read(vault)
    if token:
        os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = token


def _get_op_fields(ctx: SetupContext) -> set[str]:
    """Get 1Password fields, fetching lazily if not yet cached in *ctx*."""
    if ctx.op_fields is not None:
        return ctx.op_fields
    vault = ctx.op_vault or parse_env_file(ENV_FILE).get(ENV_OP_VAULT, "")
    fields = _fetch_op_fields(vault) if vault else set()
    ctx.op_fields = fields
    return fields


def _fetch_op_fields(vault: str) -> set[str]:
    """Return the set of field labels present in the 1Password vault item.

    Returns an empty set if ``op`` is not installed or the item doesn't exist.
    """
    if not shutil.which("op"):
        return set()
    _ensure_op_token(vault)
    try:
        result = subprocess.run(
            ["op", "item", "get", _OP_ITEM_TITLE, "--vault", vault, "--format", "json"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,  # prevent interactive prompts
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()
    if result.returncode != 0:
        return set()
    try:
        item = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()
    labels: set[str] = set()
    for field in item.get("fields", []):
        label = field.get("label", "").strip()
        value = field.get("value", "")
        if label and value:
            labels.add(label)
    return labels


def _resolve_source(
    var_name: str,
    *,
    op_fields: set[str],
    env_file_vals: dict[str, str],
) -> tuple[str, bool]:
    """Return (source_label, is_set) for a variable."""
    # Secret files — checked by filename in the secrets directory
    if var_name.endswith((".txt", ".pem")):
        path = SECRETS_DIR / var_name
        exists = path.exists() and path.read_text().strip()
        return ("secret file", True) if exists else ("\u2014", False)

    # Env vars: shell > 1Password > .env
    if os.environ.get(var_name):
        if var_name in op_fields:
            return ("1Password", True)  # op_resolver already injected it
        return ("shell", True)
    if var_name in op_fields:
        return ("1Password", True)
    if env_file_vals.get(var_name):
        return (".env", True)
    return ("\u2014", False)


def validate_environment(ctx: SetupContext) -> bool:
    """Audit all environment sources and print a grouped status table.

    In interactive mode, missing required vars prompt the user to continue
    or abort so they can fix the gaps first.  In non-interactive mode,
    missing required vars fail the stage outright.
    """
    banner("Stage: Environment Audit")

    # Determine vault name from ctx or .env
    env_vals = parse_env_file(ENV_FILE)
    vault = ctx.op_vault or env_vals.get(ENV_OP_VAULT, "")

    env_label = vault or "local"
    width = 60
    print(f"  {_BOLD}Environment Audit{_RST} {_DIM}\u2014 {env_label}{_RST}")
    print(f"  {_DIM}{'\u2500' * width}{_RST}")
    print()

    # Fetch 1Password fields (gracefully empty if not configured)
    op_fields: set[str] = set()
    if vault:
        step("Checking 1Password vault...")
        op_fields = _fetch_op_fields(vault)
        if op_fields:
            ok(f"Found {len(op_fields)} field(s) in {_OP_ITEM_TITLE}")
        else:
            step("No 1Password fields found (vault not configured or op unavailable)")
        print()

    required_total = 0
    required_set = 0
    optional_total = 0
    optional_set = 0

    # Stash op_fields in ctx so downstream stages can check 1Password
    ctx.op_fields = op_fields

    for group_label, variables in ENV_AUDIT_GROUPS:
        print(f"  {_BOLD}{group_label}{_RST}")
        for var_name, required in variables:
            source, is_set = _resolve_source(
                var_name,
                op_fields=op_fields,
                env_file_vals=env_vals,
            )
            # Pad columns for alignment
            name_col = f"    {var_name:<35s}"
            source_col = f"{source:<13s}"
            if is_set:
                status = f"{_GREEN}\u2713{_RST}"
            elif required:
                status = f"{_RED}\u2717{_RST}"
            else:
                status = f"{_DIM}(optional){_RST}"
            print(f"{name_col}{source_col}{status}")

            if required:
                required_total += 1
                if is_set:
                    required_set += 1
            else:
                optional_total += 1
                if is_set:
                    optional_set += 1
        print()

    # LLM provider check — at least one of the two must be set for non-dev
    _llm_vars = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
    has_llm = any(
        _resolve_source(v, op_fields=op_fields, env_file_vals=env_vals)[1] for v in _llm_vars
    )
    if not has_llm:
        env_name = env_vals.get(ENV_APP_ENVIRONMENT, "development")
        if env_name not in ("development", "test", "offline"):
            warn(
                "No LLM provider set — one of ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN is required"
            )
            required_total += 1  # count as a missing required
        else:
            hint(f"No LLM key set (ok for {env_name} — mock agent available)")
    print()

    # Summary line
    print(f"  {_DIM}{'\u2500' * width}{_RST}")
    optional_missing = optional_total - optional_set
    required_missing = required_total - required_set
    if required_missing == 0:
        summary = f"{_GREEN}\u2713{_RST} {required_set}/{required_total} required"
    else:
        summary = f"{_RED}\u2717{_RST} {required_set}/{required_total} required"
    if optional_missing > 0:
        summary += f"  \u00b7 {_YELLOW}\u26a0{_RST} {optional_missing} optional not set"
    print(f"  {summary}")
    print()

    if required_missing == 0:
        return True

    # Required vars are missing — decide whether to block.
    if ctx.non_interactive:
        fail(f"{required_missing} required variable(s) not set")
        return False

    step("Missing variables will be configured in the next stages.")
    if not confirm("Continue?", default=True):
        fail("Aborting — fix missing variables and re-run.")
        return False

    return True


def build_and_start(ctx: SetupContext) -> bool:
    """Build and start the Docker Compose stack."""
    banner("Stage: Build & Start Services")

    use_cloudflare = bool(ctx.cloudflare_tunnel_token)
    compose_files = compose_file_args(cloudflare=use_cloudflare)

    if use_cloudflare:
        step("Using selfhost compose (with Cloudflare Tunnel)")
    else:
        step("Using selfhost compose (local mode)")

    env = os.environ.copy()
    if ENV_FILE.exists():
        # Load .env for docker compose
        env.update(parse_env_file(ENV_FILE))

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


def wait_for_health(ctx: SetupContext) -> bool:  # noqa: ARG001
    """Wait for all services to become healthy."""
    banner("Stage: Health Check")

    health_script = SCRIPTS_DIR / "health_check.py"
    result = run(
        [sys.executable, str(health_script), "--wait", "--timeout", "180"],
        check=False,
    )
    if result.returncode == 0:
        ok("All services healthy")
        return True
    warn("Some services may not be ready yet — check 'just health-check'")
    return True  # Non-blocking


def seed_workflows(ctx: SetupContext) -> bool:
    """Seed workflow definitions from workflows/examples/ and workflows/triggers/.

    Seeds run inside the API container via ``docker compose run`` so they
    have network access to the event store and database (ports aren't exposed
    to the host in selfhost mode).
    """
    banner("Stage: Seed Workflows")

    seed_script = PROJECT_ROOT / "scripts" / "seed_workflows.py"
    if not seed_script.exists():
        warn("Seed script not found — skipping")
        hint("Re-seed later with: just seed-workflows")
        return True

    use_cloudflare = bool(ctx.cloudflare_tunnel_token)
    compose_files = compose_file_args(cloudflare=use_cloudflare)

    env = os.environ.copy()
    if ENV_FILE.exists():
        env.update(parse_env_file(ENV_FILE))

    def _run_in_api(
        script_path: str, extra_args: list[str] | None = None
    ) -> subprocess.CompletedProcess:
        """Run a Python script inside a one-off API container."""
        cmd = [
            "docker",
            "compose",
            *compose_files,
            "run",
            "--rm",
            "-e",
            "LOG_LEVEL=WARNING",  # suppress verbose library logs
            "-v",
            f"{PROJECT_ROOT / 'scripts'}:/app/scripts:ro",
            "-v",
            f"{PROJECT_ROOT / 'workflows'}:/app/workflows:ro",
            "--no-deps",
            "api",
            "python",
            script_path,
            *(extra_args or []),
        ]
        return subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, check=False)

    step("Seeding workflow definitions...")
    result = _run_in_api("/app/scripts/seed_workflows.py", ["--dir", "/app/workflows/examples"])
    if result.returncode == 0:
        ok("Workflows seeded")
    else:
        warn("Workflow seeding failed (non-blocking) — retry with: just seed-workflows")

    # Also seed triggers if the script exists
    trigger_script = PROJECT_ROOT / "scripts" / "seed_triggers.py"
    if trigger_script.exists():
        step("Seeding trigger presets...")
        result = _run_in_api("/app/scripts/seed_triggers.py")
        if result.returncode == 0:
            ok("Triggers seeded")
        else:
            warn("Trigger seeding failed (non-blocking) — retry with: just seed-triggers")

    # Restart API so its projection coordinator catches up on seeded events
    step("Restarting API to rebuild projections...")
    subprocess.run(
        ["docker", "compose", *compose_files, "restart", "api"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )
    ok("API restarted — projections will rebuild from event store")

    return True


def print_summary(ctx: SetupContext) -> bool:
    """Print access URLs and next steps."""
    banner("Setup Complete!")

    # Fall back to .env if ctx doesn't have the domain (e.g. re-run that kept existing config)
    domain = ctx.syn_domain or parse_env_file(ENV_FILE).get(ENV_SYN_DOMAIN, "")
    urls = format_access_urls(domain)
    print(f"  UI:            {urls['ui']}")
    print(f"  API:           {urls['api']}")
    print(f"  API Docs:      {urls['api_docs']}")
    print(f"  OpenAPI spec:  {urls['openapi']}")

    print()
    print("  Internal services (Docker network only — not exposed to host):")
    print("    PostgreSQL, EventStoreDB, Redis, MinIO, Collector")
    print()
    print("  Security: Tier 1 (single-tenant) — no API auth, Docker network isolation.")
    print("  Run 'just setup --stage security_audit' to re-check security posture.")

    print()
    callout("Next step: start the stack")
    print(f"    {_BOLD}just selfhost-up-tunnel{_RST}    Start with Cloudflare Tunnel (recommended)")
    print(f"    {_BOLD}just selfhost-up{_RST}           Start local-only (no GitHub triggers)")
    hint("The tunnel is required for GitHub webhooks — without it, self-healing")
    hint("triggers and automated workflows won't fire.")
    print()
    print("  Useful commands:")
    print("    just health-check      Check service health")
    print("    just selfhost-status    Show container status")
    print("    just selfhost-logs      Follow service logs")
    print("    just selfhost-down      Stop the stack")
    print()
    if ctx.skip_github:
        print("  GitHub App not configured. To add it later:")
        print("    just onboard --stage configure_github_app")
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
    "configure_1password": configure_1password,
    "validate_environment": validate_environment,
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

    ctx = SetupContext(
        skip_github=args.skip_github,
        non_interactive=args.non_interactive,
    )

    print()
    print(f"{_CYAN}{_BOLD}  ___  ___ ___   ___      _")
    print(" / _ \\| __| __| / __| ___| |_ _  _ _ __")
    print("| (_| | _|| _|  \\__ \\/ -_)  _| || | '_ \\")
    print(" \\__,_|___|_|   |___/\\___|\\__|\\__,_| .__/")
    print(f"                                   |_|{_RST}")
    print()
    print(f"  {_BOLD}Syntropic137{_RST} {_DIM}— Turnkey Setup{_RST}")
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
            print(f"    just setup --stage {stage_name}")
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
