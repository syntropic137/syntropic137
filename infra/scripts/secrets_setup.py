#!/usr/bin/env python3
"""
Secrets management for Syn137 infrastructure.
Cross-platform (Windows, macOS, Linux).

Usage:
    just secrets-generate  # Generate new secrets
    just secrets-check     # Verify secrets exist
    just secrets-rotate    # Rotate secrets (regenerate)
    just secrets-seal      # Encrypt secrets (safe to commit .enc)
    just secrets-unseal    # Decrypt .enc files back to plain text

Examples:
    # First-time setup
    just secrets-generate

    # Verify before deployment
    just secrets-check

    # Rotate secrets (use with caution - restarts required)
    just secrets-rotate --force

    # Encrypt secrets for safe storage / git commit
    just secrets-seal

    # Decrypt .enc files to restore plain-text secrets
    just secrets-unseal
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import subprocess
import sys
from typing import TYPE_CHECKING

from shared import REQUIRED_SECRETS, SECRET_GITHUB_KEY, SECRETS_DIR, set_secure_permissions

if TYPE_CHECKING:
    from pathlib import Path

# Optional secrets that must be provided manually
OPTIONAL_SECRETS: dict[str, str] = {}


def generate_secret(length: int) -> str:
    """Generate a cryptographically secure random hex string."""
    return secrets.token_hex(length)


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

    # Ensure GitHub App PEM placeholder exists (Docker Compose requires the file
    # even when GitHub integration is not configured — the app handles empty files
    # gracefully by checking is_configured before reading the key).
    pem_placeholder = SECRETS_DIR / SECRET_GITHUB_KEY
    if not pem_placeholder.exists():
        pem_placeholder.touch(mode=0o600)
        print(f"  ✓ {SECRET_GITHUB_KEY} (placeholder created)")

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
        print("  Run: just secrets-generate")
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


# ---------------------------------------------------------------------------
# Seal / Unseal (openssl AES-256-CBC encryption)
# ---------------------------------------------------------------------------

ENCRYPTION_CIPHER = "aes-256-cbc"
PBKDF2_ITERATIONS = 600_000
_SEALABLE_GLOBS = ("*.txt", "*.secret", "*.pem")


def _check_openssl() -> bool:
    """Verify that openssl is available."""
    try:
        subprocess.run(
            ["openssl", "version"],
            capture_output=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def seal_secrets(passphrase: str | None = None) -> bool:
    """Encrypt plain-text secrets to ``.enc`` files using openssl.

    Each ``*.txt`` and ``*.pem`` file in the secrets directory is encrypted
    with AES-256-CBC (PBKDF2 key derivation).  The original plain-text
    file is removed after successful encryption.  The ``.enc`` files are
    safe to commit to version control.

    Args:
        passphrase: Encryption passphrase.  Prompted interactively if *None*.

    Returns:
        True if all files were sealed successfully.
    """
    if not _check_openssl():
        print("openssl not found. Install OpenSSL to use seal/unseal.")
        return False

    if not SECRETS_DIR.exists():
        print(f"Secrets directory not found: {SECRETS_DIR}")
        return False

    # Collect files to seal
    files: list[Path] = []
    for pattern in _SEALABLE_GLOBS:
        files.extend(SECRETS_DIR.glob(pattern))

    if not files:
        print("No plain-text secrets found to seal.")
        return True

    if passphrase is None:
        passphrase = getpass.getpass("  Passphrase for sealing secrets: ")
        confirm = getpass.getpass("  Confirm passphrase: ")
        if passphrase != confirm:
            print("Passphrases do not match.")
            return False

    if not passphrase:
        print("Passphrase cannot be empty.")
        return False

    # Phase 1: Encrypt all files (without deleting originals yet).
    enc_pairs: list[tuple[Path, Path]] = []
    for path in files:
        enc_path = path.with_name(path.name + ".enc")
        result = subprocess.run(
            [
                "openssl",
                "enc",
                f"-{ENCRYPTION_CIPHER}",
                "-salt",
                "-pbkdf2",
                "-iter",
                str(PBKDF2_ITERATIONS),
                "-in",
                str(path),
                "-out",
                str(enc_path),
                "-pass",
                "stdin",
            ],
            input=passphrase,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  FAIL {path.name}: {result.stderr.strip()}")
            enc_path.unlink(missing_ok=True)
            # Roll back any .enc files created in this run
            for _, rollback_enc in enc_pairs:
                rollback_enc.unlink(missing_ok=True)
            return False

        set_secure_permissions(enc_path)
        enc_pairs.append((path, enc_path))
        print(f"  encrypted {path.name} -> {enc_path.name}")

    # Phase 2: All encryptions succeeded — remove plain-text originals.
    for plain, _enc in enc_pairs:
        plain.unlink()

    print(f"\n{len(enc_pairs)} file(s) sealed. Plain-text originals removed.")
    print("The .enc files are safe to commit to version control.")
    return True


def unseal_secrets(passphrase: str | None = None) -> bool:
    """Decrypt ``.enc`` files back to plain-text secrets.

    The ``.enc`` files are preserved after decryption so they remain
    available as encrypted backups (and for version control).

    Args:
        passphrase: Decryption passphrase.  Prompted interactively if *None*.

    Returns:
        True if all files were unsealed successfully.
    """
    if not _check_openssl():
        print("openssl not found. Install OpenSSL to use seal/unseal.")
        return False

    if not SECRETS_DIR.exists():
        print(f"Secrets directory not found: {SECRETS_DIR}")
        return False

    enc_files = list(SECRETS_DIR.glob("*.enc"))
    if not enc_files:
        print("No .enc files found to unseal.")
        return True

    if passphrase is None:
        passphrase = getpass.getpass("  Passphrase for unsealing secrets: ")

    if not passphrase:
        print("Passphrase cannot be empty.")
        return False

    unsealed = 0
    for enc_path in enc_files:
        # Restore original filename: foo.txt.enc -> foo.txt
        # Use stem of the .enc to strip exactly the .enc suffix.
        plain_name = enc_path.name.removesuffix(".enc")
        plain_path = enc_path.with_name(plain_name)
        result = subprocess.run(
            [
                "openssl",
                "enc",
                f"-{ENCRYPTION_CIPHER}",
                "-d",
                "-salt",
                "-pbkdf2",
                "-iter",
                str(PBKDF2_ITERATIONS),
                "-in",
                str(enc_path),
                "-out",
                str(plain_path),
                "-pass",
                "stdin",
            ],
            input=passphrase,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            plain_path.unlink(missing_ok=True)
            if "bad decrypt" in stderr.lower():
                print("  Wrong passphrase.")
            else:
                print(f"  FAIL {enc_path.name}: {stderr}")
            return False

        set_secure_permissions(plain_path)
        print(f"  unsealed {enc_path.name} -> {plain_path.name}")
        unsealed += 1

    print(f"\n{unsealed} file(s) unsealed. (.enc files preserved as backups)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Syn137 deployment secrets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s generate          Generate missing secrets
  %(prog)s generate --force  Regenerate all secrets
  %(prog)s check             Verify secrets are configured
  %(prog)s rotate            Alias for generate --force
  %(prog)s seal              Encrypt secrets (creates .enc files)
  %(prog)s unseal            Decrypt .enc files back to plain text
        """,
    )
    parser.add_argument(
        "command",
        choices=["generate", "check", "rotate", "seal", "unseal"],
        help="Command to run",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regenerate existing secrets",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("Syn137 Secrets Management")
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
    elif args.command == "seal":
        success = seal_secrets()
    elif args.command == "unseal":
        success = unseal_secrets()

    print()
    if success:
        print("✓ Done!")
    else:
        print("⚠ Action required - see above")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
