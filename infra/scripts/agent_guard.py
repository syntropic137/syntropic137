#!/usr/bin/env python3
"""Install and validate dcg, the destructive command guard, on an agent host.

Agents on a syn137 host (Claude Code, Codex, Gemini CLI) run shell commands
with no approval prompt. dcg is a pre-execution hook that denies destructive
ones (``git reset --hard``, ``rm -rf ./src``, ``docker volume rm``, ``DROP
TABLE``). This module puts it where an agent cannot switch it off:

``ensure`` (root)
    Download the release pinned in ``infra/agent-guard/dcg-version.toml``,
    verify its SHA256 and minisign signature, install the binary root-owned at
    ``/usr/local/bin/dcg``, the policy at ``/etc/dcg/config.toml``, and the
    hook in each harness's ROOT-OWNED settings layer:

    - Claude Code  ``/etc/claude-code/managed-settings.json``  PreToolUse/Bash
    - Codex        ``/etc/codex/requirements.toml``  managed PreToolUse/Bash
      (managed hooks need no per-user trust; user hooks are silently skipped
      until trusted)
    - Gemini CLI   ``/etc/gemini-cli/settings.json``  BeforeTool/run_shell_command

    Per-user settings are agent-writable, so they are never the guard. Existing
    user hooks (and the repo's Claude sdlc hook) are left alone as extra layers.

``validate`` (any user)
    Exit 1 unless: the binary is the pinned version and not writable by
    agents; every supported harness is registered; the EFFECTIVE policy each
    agent sees (a user's ~/.config/dcg overrides /etc/dcg) is fail-closed with
    the required packs; every known-bad payload is denied through each
    harness's hook protocol; no unsupported agent harness is installed; Codex
    is new enough to run PreToolUse hooks.

dcg is a guardrail, not a sandbox: an agent can still write a script to disk
and run it, and Codex's ``unified_exec`` path can skip PreToolUse. Workspace
containers carry their own copy (agentic-workspace images).

Standard library only: ``ensure`` runs as root with the system python3.
Test overrides: SYN_AGENT_GUARD_ROOT (path prefix for every host path),
SYN_AGENT_GUARD_OWNER_UID (expected owner, default 0),
SYN_AGENT_GUARD_RELEASE_URL, SYN_AGENT_GUARD_PLATFORM, SYN_AGENT_GUARD_VERSION_FILE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

GUARD_DIR = Path(__file__).resolve().parent.parent / "agent-guard"
VERSION_FILE = Path(os.environ.get("SYN_AGENT_GUARD_VERSION_FILE", GUARD_DIR / "dcg-version.toml"))
POLICY_FILE = GUARD_DIR / "dcg-config.toml"

BIN = "/usr/local/bin/dcg"
POLICY = "/etc/dcg/config.toml"
HOOK_COMMAND = f"/usr/bin/env DCG_NO_UPDATE_CHECK=1 {BIN}"
MARKER = "# Managed by syntropic137 infra/scripts/agent_guard.py."

CLAUDE_SETTINGS = "/etc/claude-code/managed-settings.json"
CODEX_REQUIREMENTS = "/etc/codex/requirements.toml"
GEMINI_SETTINGS = "/etc/gemini-cli/settings.json"

REQUIRED_PACKS = ("core.git", "core.filesystem", "database.postgresql", "containers.docker")
BAD_COMMANDS = ("rm -rf ./src", "git reset --hard", "docker volume rm x", "psql -c 'DROP TABLE x'")
SUPPORTED_HARNESSES = ("claude", "codex", "gemini")
# Agent CLIs dcg can guard but this host step does not register: their
# presence means an unguarded agent, so validation fails until one is added.
UNSUPPORTED_HARNESSES = (
    "opencode",
    "grok",
    "cursor-agent",
    "amp",
    "droid",
    "crush",
    "agy",
    "hermes",
)
CODEX_MIN_VERSION = (0, 125, 0)

CODEX_REQUIREMENTS_BODY = f"""{MARKER} Do not edit on the host.
# dcg as a managed Codex PreToolUse hook: always enabled, needs no per-user trust.
[hooks]

[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = "{HOOK_COMMAND}"
"""


class GuardError(Exception):
    """A step that must stop the install or fail validation."""


@dataclass(frozen=True)
class Asset:
    name: str
    sha256: str


@dataclass(frozen=True)
class Pin:
    version: str
    release_url: str
    minisign_public_key: str
    asset: Asset


@dataclass(frozen=True)
class Probe:
    harness: str
    command: str


def host(path: str) -> Path:
    """A host path, under SYN_AGENT_GUARD_ROOT in tests."""
    return Path(os.environ.get("SYN_AGENT_GUARD_ROOT", "/")) / path.lstrip("/")


def platform_key() -> str:
    override = os.environ.get("SYN_AGENT_GUARD_PLATFORM")
    if override:
        return override
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    return f"{machine}-{platform.system().lower()}"


def load_pin() -> Pin:
    data = tomllib.loads(VERSION_FILE.read_text())
    key = platform_key()
    assets = data["assets"]
    if key not in assets:
        raise GuardError(f"no pinned dcg asset for platform {key} in {VERSION_FILE}")
    entry = assets[key]
    return Pin(
        version=str(data["version"]),
        release_url=os.environ.get("SYN_AGENT_GUARD_RELEASE_URL", str(data["release_url"])),
        minisign_public_key=str(data["minisign_public_key"]),
        asset=Asset(name=str(entry["name"]), sha256=str(entry["sha256"])),
    )


# --- ensure ------------------------------------------------------------------


def fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_minisign() -> str:
    found = shutil.which("minisign")
    if found:
        return found
    if shutil.which("apt-get"):
        subprocess.run(["apt-get", "install", "-y", "-qq", "minisign"], check=True)
        found = shutil.which("minisign")
    if not found:
        raise GuardError(
            "minisign is required to verify the dcg release; install it with the OS package manager"
        )
    return found


def verified_binary(pin: Pin, work: Path) -> Path:
    """Download the pinned archive, verify SHA256 then minisign, return the dcg binary."""
    archive = work / pin.asset.name
    signature = work / f"{pin.asset.name}.minisig"
    base = f"{pin.release_url}/{pin.version}"
    fetch(f"{base}/{pin.asset.name}", archive)
    fetch(f"{base}/{pin.asset.name}.minisig", signature)
    actual = sha256_of(archive)
    if actual != pin.asset.sha256:
        raise GuardError(f"{pin.asset.name}: sha256 {actual} is not the pinned {pin.asset.sha256}")
    verify = subprocess.run(
        [
            ensure_minisign(),
            "-V",
            "-q",
            "-m",
            str(archive),
            "-x",
            str(signature),
            "-P",
            pin.minisign_public_key,
        ],
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise GuardError(
            f"{pin.asset.name}: minisign signature did not verify: {verify.stderr.strip()}"
        )
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "dcg"]
        if len(members) != 1:
            raise GuardError(
                f"{pin.asset.name}: expected exactly one dcg binary, found {len(members)}"
            )
        source = tar.extractfile(members[0])
        if source is None:
            raise GuardError(f"{pin.asset.name}: dcg member is unreadable")
        binary = work / "dcg"
        with source, binary.open("wb") as out:
            shutil.copyfileobj(source, out)
    binary.chmod(0o755)
    return binary


def own_by_root(path: Path) -> None:
    if os.geteuid() == 0:
        os.chown(path, 0, 0)


def write_root_file(path: Path, data: bytes, mode: int) -> None:
    """Atomically replace PATH with DATA, root-owned, parents 0755."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    tmp = path.with_name(f".{path.name}.new")
    tmp.write_bytes(data)
    tmp.chmod(mode)
    own_by_root(tmp)
    tmp.replace(path)


def merged_hook(settings: JsonObject, event: str, matcher: str, hook: JsonObject) -> JsonObject:
    """SETTINGS with HOOK registered once under EVENT/MATCHER; stale dcg hooks dropped."""
    hooks = settings.get("hooks")
    hooks = dict(hooks) if isinstance(hooks, dict) else {}
    groups = hooks.get(event)
    kept: list[JsonValue] = []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            kept.append(group)
            continue
        handlers = group.get("hooks")
        handlers = handlers if isinstance(handlers, list) else []
        others = [
            h for h in handlers if not (isinstance(h, dict) and is_dcg_command(h.get("command")))
        ]
        if others or not handlers:
            kept.append({**group, "hooks": others})
    kept.append({"matcher": matcher, "hooks": [hook]})
    hooks[event] = kept
    return {**settings, "hooks": hooks}


def is_dcg_command(command: JsonValue) -> bool:
    return isinstance(command, str) and bool(re.search(r"(^|[\s/])dcg$", command.strip()))


def register_json(path: Path, event: str, matcher: str, hook: JsonObject) -> None:
    current: JsonObject = {}
    if path.exists():
        loaded = json.loads(path.read_text() or "{}")
        if not isinstance(loaded, dict):
            raise GuardError(f"{path} is not a JSON object")
        current = loaded
    updated = merged_hook(current, event, matcher, hook)
    write_root_file(path, (json.dumps(updated, indent=2) + "\n").encode(), 0o644)


def register_codex(path: Path) -> None:
    if path.exists() and not path.read_text().startswith(MARKER):
        raise GuardError(
            f"{path} exists and is not managed by agent_guard.py; merge the dcg [hooks] block by hand"
        )
    write_root_file(path, CODEX_REQUIREMENTS_BODY.encode(), 0o644)


def ensure() -> None:
    if os.geteuid() != 0 and "SYN_AGENT_GUARD_ROOT" not in os.environ:
        raise GuardError("ensure installs root-owned files: run it as root (sudo)")
    pin = load_pin()
    with tempfile.TemporaryDirectory(prefix="dcg-") as tmp:
        binary = verified_binary(pin, Path(tmp))
        version = run_version(binary)
        if version != pin.version.lstrip("v"):
            raise GuardError(f"downloaded dcg reports {version!r}, pinned {pin.version}")
        write_root_file(host(BIN), binary.read_bytes(), 0o755)
    write_root_file(host(POLICY), POLICY_FILE.read_bytes(), 0o644)
    register_json(
        host(CLAUDE_SETTINGS), "PreToolUse", "Bash", {"type": "command", "command": HOOK_COMMAND}
    )
    register_json(
        host(GEMINI_SETTINGS),
        "BeforeTool",
        "run_shell_command",
        {"name": "dcg", "type": "command", "command": HOOK_COMMAND, "timeout": 5000},
    )
    register_codex(host(CODEX_REQUIREMENTS))
    print(f"  dcg {pin.version} installed at {BIN}; policy {POLICY}; hooks: claude, codex, gemini")


# --- validate ----------------------------------------------------------------


def run_version(binary: Path) -> str:
    out = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, env=clean_env(None)
    ).stdout
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", out)
    return match.group(1) if match else ""


def clean_env(home: Path | None) -> dict[str, str]:
    """No inherited DCG_* overrides: validate what the files say."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1", "DCG_NO_UPDATE_CHECK": "1"}
    if home is not None:
        env["HOME"] = str(home)
    return env


def expected_owner() -> int:
    return int(os.environ.get("SYN_AGENT_GUARD_OWNER_UID", "0"))


def check_locked(path: Path) -> list[str]:
    """PATH and every ancestor: owned by root, not group/world writable."""
    problems: list[str] = []
    if not path.exists():
        return [f"{path} is missing"]
    owner = expected_owner()
    root = host("/").resolve()
    for p in [path, *path.parents]:
        if os.environ.get("SYN_AGENT_GUARD_ROOT") and not p.resolve().is_relative_to(root):
            break
        st = p.stat()
        if st.st_uid != owner:
            problems.append(f"{p} is owned by uid {st.st_uid}, not {owner}")
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            problems.append(f"{p} is group/world writable")
    return problems


def registered_json(path: Path, event: str) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    groups = data.get("hooks", {}).get(event, []) if isinstance(data, dict) else []
    return any(
        isinstance(h, dict) and h.get("command") == HOOK_COMMAND
        for g in groups
        if isinstance(g, dict)
        for h in (g.get("hooks") or [])
    )


def registered_codex(path: Path) -> bool:
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return False
    groups = data.get("hooks", {}).get("PreToolUse", [])
    return any(h.get("command") == HOOK_COMMAND for g in groups for h in g.get("hooks", []))


def payload(harness: str, command: str, cwd: Path) -> str:
    base: JsonObject = {
        "session_id": "agent-guard-validate",
        "cwd": str(cwd),
        "transcript_path": None,
    }
    if harness == "gemini":
        body: JsonObject = {
            **base,
            "hook_event_name": "BeforeTool",
            "timestamp": "1970-01-01T00:00:00Z",
            "tool_name": "run_shell_command",
            "tool_input": {"command": command},
        }
    elif harness == "codex":
        body = {
            **base,
            "turn_id": "agent-guard-validate",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_use_id": "agent-guard-validate",
            "tool_input": {"command": command},
        }
    else:
        body = {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    return json.dumps(body)


def hook_denies(stdin: str, home: Path, cwd: Path) -> bool:
    """Run the registered hook command as the harness would; True when it denies."""
    argv: list[str] = [*HOOK_COMMAND.split()]
    argv[-1] = str(host(argv[-1]))
    result = subprocess.run(
        argv, input=stdin, capture_output=True, text=True, env=clean_env(home), cwd=cwd, timeout=30
    )
    if result.returncode == 2:
        return True
    try:
        decision = json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        return False
    if not isinstance(decision, dict):
        return False
    specific = decision.get("hookSpecificOutput")
    if isinstance(specific, dict) and specific.get("permissionDecision") == "deny":
        return True
    return decision.get("decision") in ("deny", "block")


def effective_policy(home: Path) -> list[str]:
    out = subprocess.run(
        [str(host(BIN)), "config"],
        capture_output=True,
        text=True,
        env=clean_env(home),
        cwd=home,
        timeout=30,
    ).stdout
    problems: list[str] = []
    for label, want in (
        ("Fail closed", "true"),
        ("Unverified decision", "deny"),
        ("Check updates", "false"),
    ):
        match = re.search(rf"^\s*{label}:\s*(\S+)", out, re.MULTILINE)
        if not match or match.group(1) != want:
            problems.append(
                f"{home}: effective '{label}' is {match.group(1) if match else 'missing'}, want {want}"
            )
    enabled = set(
        re.findall(
            r"^\s+- (\S+)$",
            out.split("Enabled packs:", 1)[-1].split("Disabled packs:", 1)[0],
            re.MULTILINE,
        )
    )
    missing = [p for p in REQUIRED_PACKS if p not in enabled]
    if missing:
        problems.append(f"{home}: required packs not enabled: {', '.join(missing)}")
    return problems


def find_harness(name: str, home: Path) -> Path | None:
    dirs = [
        home / ".local/bin",
        home / ".bun/bin",
        home / ".npm-global/bin",
        host("/usr/local/bin"),
        host("/usr/bin"),
    ]
    for d in dirs:
        candidate = d / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in match.groups()) if match else ()


def agent_homes(users: list[str]) -> list[Path]:
    if users:
        return [Path(pwd.getpwnam(u).pw_dir) for u in users]
    return [
        Path(e.pw_dir)
        for e in pwd.getpwall()
        if 1000 <= e.pw_uid < 65534
        and Path(e.pw_dir).is_dir()
        and e.pw_shell not in ("/usr/sbin/nologin", "/bin/false")
    ]


def validate(homes: list[Path]) -> list[str]:
    pin = load_pin()
    problems: list[str] = []
    for path in (
        host(BIN),
        host(POLICY),
        host(CLAUDE_SETTINGS),
        host(CODEX_REQUIREMENTS),
        host(GEMINI_SETTINGS),
    ):
        problems += check_locked(path)
    if host(BIN).exists() and (v := run_version(host(BIN))) != pin.version.lstrip("v"):
        problems.append(f"{BIN} reports {v or 'no version'}, pinned {pin.version}")
    if host(POLICY).exists() and host(POLICY).read_bytes() != POLICY_FILE.read_bytes():
        problems.append(f"{POLICY} differs from {POLICY_FILE}")
    if not registered_json(host(CLAUDE_SETTINGS), "PreToolUse"):
        problems.append(f"claude: dcg not registered in {CLAUDE_SETTINGS}")
    if not registered_codex(host(CODEX_REQUIREMENTS)):
        problems.append(f"codex: dcg not registered in {CODEX_REQUIREMENTS}")
    if not registered_json(host(GEMINI_SETTINGS), "BeforeTool"):
        problems.append(f"gemini: dcg not registered in {GEMINI_SETTINGS}")
    if problems:
        return problems  # the probes below would only restate a missing install
    with tempfile.TemporaryDirectory(prefix="dcg-validate-") as tmp:
        cwd = Path(tmp)
        for home in homes:
            problems += effective_policy(home)
            for harness in SUPPORTED_HARNESSES:
                probes = [Probe(harness, c) for c in BAD_COMMANDS]
                for probe in probes:
                    if not hook_denies(payload(probe.harness, probe.command, cwd), home, cwd):
                        problems.append(
                            f"{home} {harness}: known-bad payload was not denied: {probe.command}"
                        )
                if hook_denies(payload(harness, "ls", cwd), home, cwd):
                    problems.append(
                        f"{home} {harness}: harmless 'ls' was denied (policy blocks everything)"
                    )
                if not hook_denies("not json", home, cwd):
                    problems.append(
                        f"{home} {harness}: unparseable hook input was allowed (not fail-closed)"
                    )
            for name in UNSUPPORTED_HARNESSES:
                if found := find_harness(name, home):
                    problems.append(f"{found}: agent harness with no dcg registration on this host")
            if codex := find_harness("codex", home):
                out = subprocess.run(
                    [str(codex), "--version"], capture_output=True, text=True, timeout=30
                ).stdout
                if version_tuple(out) < CODEX_MIN_VERSION:
                    problems.append(
                        f"{codex}: {out.strip() or 'unknown version'} is older than 0.125.0; PreToolUse hooks do not run"
                    )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("ensure", help="install the pinned dcg and register it (root)")
    check = sub.add_parser("validate", help="exit 1 unless every guard check passes")
    check.add_argument(
        "--user",
        action="append",
        default=[],
        help="agent user to check (default: every login user)",
    )
    check.add_argument("--home", action="append", default=[], type=Path, help="agent home to check")
    args = parser.parse_args(argv)
    try:
        if args.action == "ensure":
            ensure()
            return 0
        problems = validate(args.home or agent_homes(args.user))
    except (GuardError, OSError, subprocess.SubprocessError, KeyError) as exc:
        print(f"  ❌ agent guard: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"  ❌ agent guard: {problem}", file=sys.stderr)
    if not problems:
        print(
            "  ✅ agent guard: dcg pinned, root-owned, registered for claude/codex/gemini, known-bad payloads denied"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
