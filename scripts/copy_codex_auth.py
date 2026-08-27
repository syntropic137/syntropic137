"""Copy the local codex auth (~/.codex/auth.json) to the clipboard, ready to paste.

The pretty-printed, multi-line auth.json breaks when used as an environment
variable value, so this compacts it to a single line and copies it to the
system clipboard in one of two formats:

- default:   the raw single-line JSON value   -> paste into a 1Password field
- --dotenv:  ``CODEX_AUTH_JSON='<value>'``     -> paste as a line into root .env

Cross-platform: uses pbcopy (macOS), clip (Windows), or wl-copy / xclip / xsel
(Linux). The secret is never printed unless --stdout is passed explicitly.

Run via:
    uv run python scripts/copy_codex_auth.py [--dotenv] [--stdout]

See ADR-004 (environment configuration) and the codex-runner workflow phases.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from syn_shared.env_constants import ENV_CODEX_AUTH_JSON

# 1Password item field / .env key that the resolver (op_env_export.py) reads.
_AUTH_MODE_KEY = "auth_mode"


def _auth_path() -> Path:
    """Resolve the codex auth file, honoring CODEX_HOME like the codex CLI does."""
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "auth.json"


def _load_compact(path: Path) -> tuple[str, str, dict[str, object]]:
    """Read auth.json; return its compact single-line JSON and its auth_mode.

    Raises SystemExit with actionable guidance when the file is missing or not
    a JSON object.
    """
    if not path.is_file():
        raise SystemExit(
            f"error: {path} not found.\n"
            "  Run `codex login` first to create it, then re-run this command."
        )
    raw = path.read_text(encoding="utf-8")
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} is not valid JSON ({exc}).") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise SystemExit(f"error: {path} does not contain a JSON object.")
    data = cast("dict[str, object]", parsed)

    compact = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    mode = data.get(_AUTH_MODE_KEY)
    auth_mode = mode if isinstance(mode, str) else "?"
    return compact, auth_mode, data


def _token_status(data: dict[str, object]) -> list[str]:
    """Human-readable, NON-SECRET lines describing the token's freshness.

    WHY this exists: the copy step is not the failure mode. Copying a burned
    token succeeds silently and the breakage only surfaces later, inside a
    container, as `refresh_token_reused`. Reporting expiry here turns a
    ten-minute container-log dig into a line of output.

    Only the JWT `exp` claim is decoded, and only to compute a duration. No
    token material is returned, printed, or logged.
    """
    lines: list[str] = []
    last = data.get("last_refresh")
    if isinstance(last, str):
        lines.append(f"  last_refresh: {last}")

    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return lines
    access = tokens.get("access_token")
    if not isinstance(access, str) or access.count(".") != 2:
        return lines

    body = access.split(".")[1]
    body += "=" * (-len(body) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return lines
    if not isinstance(claims, dict):
        return lines
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return lines

    remaining = exp - time.time()
    if remaining < 0:
        lines.append(f"  access_token: EXPIRED {abs(remaining) / 3600:.1f}h ago")
        lines.append("  -> run `codex login` before copying; this value is dead.")
    else:
        lines.append(f"  access_token: valid, {remaining / 3600:.1f}h left")
    return lines


def _clipboard_command() -> list[str] | None:
    """First available clipboard-write command for this platform, or None."""
    if sys.platform == "darwin":
        candidates = [["pbcopy"]]
    elif sys.platform.startswith("win"):
        candidates = [["clip"]]
    else:
        candidates = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    for argv in candidates:
        if shutil.which(argv[0]) is not None:
            return argv
    return None


def _build_payload(compact: str, *, dotenv: bool) -> str:
    """Wrap the compact JSON for the target: raw value, or a `.env` line.

    Raises SystemExit if a `.env` line is requested but the value contains a
    single quote (which single-quote wrapping cannot safely escape).
    """
    if not dotenv:
        return compact
    if "'" in compact:
        raise SystemExit(
            "error: auth.json contains a single quote; a single-quoted .env "
            "line would be unsafe. Use the default (1Password) format instead."
        )
    return f"{ENV_CODEX_AUTH_JSON}='{compact}'"


def _copy_to_clipboard(payload: str) -> bool:
    """Pipe payload into the platform clipboard tool. False if none is available."""
    argv = _clipboard_command()
    if argv is None:
        return False
    try:
        subprocess.run(argv, input=payload.encode("utf-8"), check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SystemExit(f"error: clipboard tool {argv[0]!r} failed ({exc}).") from exc
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy ~/.codex/auth.json (compacted to one line) to the clipboard, "
            "ready to paste into 1Password or .env."
        ),
    )
    parser.add_argument(
        "--dotenv",
        "-e",
        action="store_true",
        help=(
            f"copy a ready-to-paste `{ENV_CODEX_AUTH_JSON}='<value>'` .env line "
            "(default: the raw value, for a 1Password field)."
        ),
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the payload to stdout instead of the clipboard (exposes the secret).",
    )
    args = parser.parse_args()

    compact, auth_mode, data = _load_compact(_auth_path())

    payload = _build_payload(compact, dotenv=args.dotenv)
    if args.dotenv:
        fmt = "dotenv line"
        target = "the root .env (replace any existing CODEX_AUTH_JSON line)"
    else:
        fmt = "raw value"
        target = f"the 1Password field named {ENV_CODEX_AUTH_JSON}"

    if args.stdout:
        sys.stdout.write(payload + "\n")
        return 0

    if not _copy_to_clipboard(payload):
        raise SystemExit(
            "error: no clipboard tool found (need pbcopy / clip / wl-copy / xclip / xsel).\n"
            "  Re-run with --stdout to print the value instead."
        )

    print(f"Copied codex auth to clipboard ({fmt}, {len(payload)} bytes, auth_mode={auth_mode}).")
    for line in _token_status(data):
        print(line)
    print(f"  Paste into: {target}")
    print()
    print("  THEN REBUILD, or the paste does nothing:")
    print("    just dev-down && just dev")
    print("  Environment variables are fixed when a container is created, so a")
    print("  running stack keeps the old value. `docker restart` is NOT enough:")
    print("  it reuses the existing container and its environment.")
    if not args.dotenv:
        print()
        print("  NOTE: the dev stack reads the ROOT .env (justfile set dotenv-load),")
        print("  not 1Password. Updating the vault alone will not reach `just dev`.")
        print("  For the dev stack use: just codex-auth-clip --dotenv")
    print()
    print("  WHY THIS KEEPS BREAKING: this laptop and the container share ONE")
    print("  OAuth refresh token, and refresh tokens are single-use. Whichever")
    print("  side refreshes first invalidates the other, and the loser fails")
    print("  with `refresh_token_reused`. Running codex locally during a")
    print("  containerized run is enough to break it. See issue #893.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
