#!/usr/bin/env python3
"""
Secrets management for AEF infrastructure.
Cross-platform (Windows, macOS, Linux).

Usage:
    python secrets_setup.py generate  # Generate new secrets
    python secrets_setup.py check     # Verify secrets exist
    python secrets_setup.py rotate    # Rotate secrets (regenerate)

Examples:
    # First-time setup
    python infra/scripts/secrets_setup.py generate

    # Verify before deployment
    python infra/scripts/secrets_setup.py check

    # Rotate secrets (use with caution - restarts required)
    python infra/scripts/secrets_setup.py rotate --force
"""

import argparse
import contextlib
import secrets
import stat
import sys
from pathlib import Path

# Resolve secrets directory relative to this script
SCRIPT_DIR = Path(__file__).parent.resolve()
SECRETS_DIR = SCRIPT_DIR.parent / "docker" / "secrets"

# Required secrets with their byte lengths (generates 2x chars in hex)
REQUIRED_SECRETS = {
    "db-password.txt": 32,  # 64 hex chars
    "github-webhook-secret.txt": 32,  # 64 hex chars
}

# Optional secrets that must be provided manually
OPTIONAL_SECRETS = {
    "github-private-key.pem": "Copy from GitHub App settings",
}


def generate_secret(length: int) -> str:
    """Generate a cryptographically secure random hex string."""
    return secrets.token_hex(length)


def set_secure_permissions(path: Path) -> None:
    """Set file permissions to owner read/write only (600)."""
    # Works on Unix-like systems; silently ignored on Windows
    with contextlib.suppress(OSError, AttributeError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def generate_secrets(force: bool = False) -> bool:
    """
    Generate all required secrets.

    Args:
        force: If True, regenerate existing secrets.

    Returns:
        True if all secrets are ready, False if manual action needed.
    """
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)

    all_ok = True
    generated = 0
    skipped = 0

    print(f"Secrets directory: {SECRETS_DIR}\n")

    # Generate required secrets
    for filename, length in REQUIRED_SECRETS.items():
        path = SECRETS_DIR / filename

        if path.exists() and not force:
            print(f"  ✓ {filename} (exists)")
            skipped += 1
            continue

        secret = generate_secret(length)
        path.write_text(secret)
        set_secure_permissions(path)
        print(f"  ✓ {filename} (generated)")
        generated += 1

    print()

    # Check for optional secrets
    for filename, instructions in OPTIONAL_SECRETS.items():
        path = SECRETS_DIR / filename
        if path.exists():
            print(f"  ✓ {filename} (exists)")
        else:
            print(f"  ⚠ {filename} MISSING")
            print(f"    → {instructions}")
            all_ok = False

    print()
    print(f"Generated: {generated}, Skipped: {skipped}")

    if not all_ok:
        print("\n⚠ Some optional secrets are missing. See instructions above.")

    return all_ok


def check_secrets() -> bool:
    """
    Verify all required secrets exist.

    Returns:
        True if all required secrets exist.
    """
    all_ok = True
    print(f"Secrets directory: {SECRETS_DIR}\n")

    if not SECRETS_DIR.exists():
        print("✗ Secrets directory does not exist!")
        print(f"  Run: python {__file__} generate")
        return False

    # Check required secrets
    print("Required secrets:")
    for filename in REQUIRED_SECRETS:
        path = SECRETS_DIR / filename
        if path.exists():
            # Check if file is not empty
            content = path.read_text().strip()
            if content:
                print(f"  ✓ {filename} ({len(content)} chars)")
            else:
                print(f"  ✗ {filename} (empty)")
                all_ok = False
        else:
            print(f"  ✗ {filename} MISSING")
            all_ok = False

    print()

    # Check optional secrets
    print("Optional secrets:")
    for filename in OPTIONAL_SECRETS:
        path = SECRETS_DIR / filename
        if path.exists():
            print(f"  ✓ {filename}")
        else:
            print(f"  ⚠ {filename} (not configured)")

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage AEF deployment secrets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s generate          Generate missing secrets
  %(prog)s generate --force  Regenerate all secrets
  %(prog)s check             Verify secrets are configured
  %(prog)s rotate            Alias for generate --force
        """,
    )
    parser.add_argument(
        "command",
        choices=["generate", "check", "rotate"],
        help="Command to run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regenerate existing secrets",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("AEF Secrets Management")
    print("=" * 50)
    print()

    if args.command == "generate":
        success = generate_secrets(force=args.force)
    elif args.command == "check":
        success = check_secrets()
    elif args.command == "rotate":
        print("⚠ Rotating secrets requires service restart!")
        print()
        success = generate_secrets(force=True)

    print()
    if success:
        print("✓ Done!")
    else:
        print("⚠ Action required - see above")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
