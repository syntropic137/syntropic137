"""Install the local codex credential into the root .env, or report its freshness.

WHY THIS EXISTS RATHER THAN A CLIPBOARD STEP. `just codex-auth-clip` copies the
value and tells you where to paste it. That is one manual step too many for
something that has to happen every time the credential is re-minted, and a
manual paste is where a stale value survives: the clipboard copy succeeds, the
paste is forgotten, and the deployment keeps serving the old credential with no
signal until a phase fails.

The clipboard recipe is still right when the destination is a vault, which this
cannot write to. This one handles the root `.env`, which is what `just dev`
actually reads.

SECURITY. The credential is never printed. `--status-only` reports freshness
only, via the same non-secret describer the API health endpoint uses, so the
warning you see locally and the warning an operator queries are the same
computation rather than two that can drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from syn_shared.codex_auth_status import CodexAuthState, describe_codex_auth
from syn_shared.env_constants import ENV_CODEX_AUTH_JSON

_ENV_FILE = Path(".env")


def _auth_path() -> Path:
    """Resolve the codex auth file, honouring CODEX_HOME like the codex CLI."""
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "auth.json"


def _read_local_credential() -> str:
    path = _auth_path()
    if not path.is_file():
        raise SystemExit(f"error: {path} not found.\n  Run `codex login` first, then re-run this.")
    raw = path.read_text(encoding="utf-8")
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} is not valid JSON ({exc}).") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise SystemExit(f"error: {path} does not contain a JSON object.")
    return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)


def _current_env_value() -> str | None:
    if not _ENV_FILE.is_file():
        return None
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{ENV_CODEX_AUTH_JSON}="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return None


def _install(compact: str) -> bool:
    """Replace (or append) the CODEX_AUTH_JSON line. True if the file changed.

    Single-quoted because the value is compact JSON full of double quotes. A
    single quote inside it would break the quoting, so that is rejected rather
    than escaped: a silently mangled credential is worse than a refusal.
    """
    if "'" in compact:
        raise SystemExit(
            "error: the credential contains a single quote, which cannot be "
            "safely written as a single-quoted .env value. Use "
            "`just codex-auth-clip` and paste it manually."
        )
    line = f"{ENV_CODEX_AUTH_JSON}='{compact}'"

    if not _ENV_FILE.is_file():
        raise SystemExit("error: no .env in the current directory. Run this from the repo root.")

    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
    out, replaced = [], False
    for existing in lines:
        if existing.startswith(f"{ENV_CODEX_AUTH_JSON}="):
            out.append(line)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(line)
    new_text = "\n".join(out) + "\n"
    if new_text == _ENV_FILE.read_text(encoding="utf-8"):
        return False
    _ENV_FILE.write_text(new_text, encoding="utf-8")
    return True


def _print_status(raw: str | None, label: str) -> CodexAuthState:
    status = describe_codex_auth(raw)
    marker = {
        CodexAuthState.OK: "ok",
        CodexAuthState.EXPIRING: "WARN",
        CodexAuthState.EXPIRED: "FAIL",
        CodexAuthState.ABSENT: "none",
        CodexAuthState.UNREADABLE: "?",
    }[status.state]
    print(f"  [{marker}] {label}: {status.detail}")
    return status.state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install ~/.codex/auth.json into the root .env, or report freshness.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="report freshness of the credential already in .env and exit.",
    )
    args = parser.parse_args()

    if args.status_only:
        state = _print_status(_current_env_value(), ".env")
        # Non-zero only when someone must act, so this is usable as a check.
        return 1 if state in (CodexAuthState.EXPIRED, CodexAuthState.EXPIRING) else 0

    compact = _read_local_credential()
    _print_status(compact, "new credential")
    changed = _install(compact)
    print(f"  {'.env updated' if changed else '.env already had this value'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
