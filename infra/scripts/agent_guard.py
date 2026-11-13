#!/usr/bin/env python3
"""Install and validate dcg, the destructive command guard, on an agent host.

Agents on a syn137 host (Claude Code, Codex, Gemini CLI) run shell commands
with no approval prompt. dcg is a pre-execution hook that denies destructive
ones (``git reset --hard``, ``rm -rf ./src``, ``docker volume rm``, ``DROP
TABLE``). This module puts it where an agent cannot switch it off:

``ensure`` (root)
    Download the release pinned in ``infra/agent-guard/dcg-version.toml``,
    verify SHA256 then minisign, and install root-owned: the binary at
    ``/usr/local/bin/dcg``, the policy at ``/etc/dcg/config.toml``, and the
    hook in each harness's ROOT-OWNED settings layer (Claude Code
    managed-settings.json, Codex requirements.toml managed hooks, Gemini system
    settings). Every output is computed and every destination checked BEFORE
    anything is written; a failed write restores what was there.

    The hook runs dcg with an EMPTY environment and HOME=/nonexistent, so the
    agent's environment (DCG_BYPASS, DCG_CONFIG, ...) and its ~/.config/dcg
    cannot weaken it: only the root-owned /etc/dcg/config.toml applies.

``validate`` (the agent account, never root)
    Exit 1 unless: nothing in the chain is a symlink or writable by a non-root
    user; the binary is the pinned version; each harness registration is
    exactly the expected matcher/type/command; the policy is fail-closed with
    the required packs; the four known-bad payloads are denied and ``ls`` is
    allowed through each harness's hook protocol, run with the exact
    registered command; no unregistered agent CLI is installed; Codex is new
    enough to run PreToolUse hooks (read from its package.json, never run).

dcg is a guardrail, not a sandbox: an agent can still write a script to disk
and run it, and Codex's ``unified_exec`` path can skip PreToolUse. Workspace
containers carry their own copy (agentic-workspace images).

Standard library only: ``ensure`` runs as root with the system python3.
Test overrides (honoured only when NOT root): SYN_AGENT_GUARD_ROOT (path
prefix for every host path), SYN_AGENT_GUARD_OWNER_UID, SYN_AGENT_GUARD_RELEASE_URL,
SYN_AGENT_GUARD_PLATFORM, SYN_AGENT_GUARD_VERSION_FILE, SYN_AGENT_GUARD_MINISIGN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import pwd
import re
import shlex
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

IS_ROOT = os.geteuid() == 0


def override(name: str, default: str) -> str:
    """A test override, ignored as root so a preserved env cannot steer an install."""
    return default if IS_ROOT else os.environ.get(name, default)


GUARD_DIR = Path(__file__).resolve().parent.parent / "agent-guard"
VERSION_FILE = Path(override("SYN_AGENT_GUARD_VERSION_FILE", str(GUARD_DIR / "dcg-version.toml")))
POLICY_FILE = GUARD_DIR / "dcg-config.toml"

BIN = "/usr/local/bin/dcg"
POLICY = "/etc/dcg/config.toml"
HOOK_COMMAND = f"/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent DCG_NO_UPDATE_CHECK=1 {BIN}"
MARKER = "# Managed by syntropic137 infra/scripts/agent_guard.py."
WORK_DIR = "/var/lib/syn137-agent-guard"  # root-owned 0700 download/probe area

CLAUDE_SETTINGS = "/etc/claude-code/managed-settings.json"
CODEX_REQUIREMENTS = "/etc/codex/requirements.toml"
GEMINI_SETTINGS = "/etc/gemini-cli/settings.json"
CLAUDE_HOOK: JsonObject = {"type": "command", "command": HOOK_COMMAND}
GEMINI_HOOK: JsonObject = {
    "name": "dcg",
    "type": "command",
    "command": HOOK_COMMAND,
    "timeout": 5000,
}

REQUIRED_PACKS = ("core.git", "core.filesystem", "database.postgresql", "containers.docker")
BAD_COMMANDS = (
    "rm -rf ./src",
    "git reset --hard",
    "docker volume rm x",
    "psql -c 'DROP TABLE x'",
)
SUPPORTED_HARNESSES = ("claude", "codex", "gemini")
# Agent CLIs this host step does not register: present means unguarded.
UNSUPPORTED_HARNESSES = (
    "opencode", "grok", "cursor-agent", "amp", "droid", "crush", "agy", "hermes",
)  # fmt: skip
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
class Output:
    """One file ``ensure`` writes: computed in full before anything is touched."""

    path: Path
    data: bytes
    mode: int


def host(path: str) -> Path:
    """A host path, under SYN_AGENT_GUARD_ROOT in tests."""
    return Path(override("SYN_AGENT_GUARD_ROOT", "/")) / path.lstrip("/")


def expected_owner() -> int:
    return int(override("SYN_AGENT_GUARD_OWNER_UID", "0"))


def platform_key() -> str:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    return override("SYN_AGENT_GUARD_PLATFORM", f"{machine}-{platform.system().lower()}")


def load_pin() -> Pin:
    data = tomllib.loads(VERSION_FILE.read_text())
    key = platform_key()
    if key not in data["assets"]:
        raise GuardError(f"no pinned dcg asset for platform {key} in {VERSION_FILE}")
    entry = data["assets"][key]
    return Pin(
        version=str(data["version"]),
        release_url=override("SYN_AGENT_GUARD_RELEASE_URL", str(data["release_url"])),
        minisign_public_key=str(data["minisign_public_key"]),
        asset=Asset(name=str(entry["name"]), sha256=str(entry["sha256"])),
    )


# --- path safety --------------------------------------------------------------


def chain_problems(path: Path) -> list[str]:
    """PATH and its ancestors: no symlinks, owned by root, not group/world writable."""
    problems: list[str] = []
    owner = expected_owner()
    top = host("/")
    for p in [path, *path.parents]:
        if not p.is_relative_to(top):
            break
        try:
            st = p.lstat()
        except FileNotFoundError:
            continue  # a missing parent is created root-owned by ensure
        if stat.S_ISLNK(st.st_mode):
            problems.append(f"{p} is a symlink")
        elif st.st_uid != owner:
            problems.append(f"{p} is owned by uid {st.st_uid}, not {owner}")
        elif st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            problems.append(f"{p} is group/world writable")
        if p == top:
            break
    return problems


def check_locked(path: Path) -> list[str]:
    if not path.exists() and not path.is_symlink():
        return [f"{path} is missing"]
    return chain_problems(path)


def own_by_root(path: Path) -> None:
    if IS_ROOT:
        os.chown(path, 0, 0, follow_symlinks=False)


def make_dirs(directory: Path) -> None:
    missing = [p for p in [directory, *directory.parents] if not p.exists()]
    for p in reversed(missing):
        p.mkdir(mode=0o755)
        own_by_root(p)


def stage_file(path: Path, data: bytes, mode: int) -> Path:
    """Write DATA to an exclusive, randomly named sibling of PATH; return it."""
    make_dirs(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(mode)
        own_by_root(tmp)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def commit_outputs(outputs: list[Output]) -> None:
    """Stage every new file AND every rollback copy first (the step that can run
    out of space), then swap them in with renames. A failed swap is undone item
    by item, each restore attempted even if another fails."""
    staged: list[tuple[Output, Path, Path | None]] = []
    try:
        for out in outputs:
            backup = (
                stage_file(out.path, out.path.read_bytes(), out.mode) if out.path.exists() else None
            )
            staged.append((out, stage_file(out.path, out.data, out.mode), backup))
    except BaseException:
        for _, new, backup in staged:
            new.unlink(missing_ok=True)
            if backup:
                backup.unlink(missing_ok=True)
        raise
    swapped: list[tuple[Output, Path | None]] = []
    try:
        for out, new, backup in staged:
            new.replace(out.path)
            swapped.append((out, backup))
    except BaseException:
        failures: list[str] = []
        for out, backup in reversed(swapped):
            try:
                if backup is None:
                    out.path.unlink(missing_ok=True)
                else:
                    backup.replace(out.path)
            except OSError as exc:
                failures.append(f"{out.path}: {exc}")
        if failures:
            print("  ❌ agent guard: could not restore " + "; ".join(failures), file=sys.stderr)
        raise
    finally:
        for _, new, backup in staged:
            new.unlink(missing_ok=True)
            if backup:
                backup.unlink(missing_ok=True)


# --- ensure ------------------------------------------------------------------


def trusted_tool(name: str, absolute: str) -> str:
    """A tool by absolute system path; tests may point at a stand-in (not as root)."""
    return override(f"SYN_AGENT_GUARD_{name.upper()}", absolute)


def fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def minisign_binary() -> str:
    minisign = trusted_tool("minisign", "/usr/bin/minisign")
    if not Path(minisign).is_file() and IS_ROOT and Path("/usr/bin/apt-get").is_file():
        subprocess.run(["/usr/bin/apt-get", "install", "-y", "-qq", "minisign"], check=True)
    if not Path(minisign).is_file():
        raise GuardError(f"{minisign} is required to verify the dcg release; install minisign")
    return minisign


def verified_binary(pin: Pin, work: Path) -> bytes:
    """Download the pinned archive; verify SHA256, then minisign; return dcg's bytes."""
    archive = work / pin.asset.name
    signature = work / f"{pin.asset.name}.minisig"
    base = f"{pin.release_url}/{pin.version}"
    fetch(f"{base}/{pin.asset.name}", archive)
    fetch(f"{base}/{pin.asset.name}.minisig", signature)
    actual = sha256_of(archive)
    if actual != pin.asset.sha256:
        raise GuardError(f"{pin.asset.name}: sha256 {actual} is not the pinned {pin.asset.sha256}")
    verify = subprocess.run(
        [minisign_binary(), "-V", "-q", "-m", str(archive), "-x", str(signature),
         "-P", pin.minisign_public_key],
        capture_output=True,
        text=True,
    )  # fmt: skip
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
        with source:
            data = source.read()
    probe = work / "dcg"
    probe.write_bytes(data)
    probe.chmod(0o700)
    if (version := run_version(probe)) != pin.version.lstrip("v"):
        raise GuardError(f"downloaded dcg reports {version!r}, pinned {pin.version}")
    return data


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


def json_output(path: Path, event: str, matcher: str, hook: JsonObject) -> Output:
    current: JsonObject = {}
    if path.exists():
        loaded = json.loads(path.read_text() or "{}")
        if not isinstance(loaded, dict):
            raise GuardError(f"{path} is not a JSON object")
        current = loaded
    updated = merged_hook(current, event, matcher, hook)
    return Output(path, (json.dumps(updated, indent=2) + "\n").encode(), 0o644)


def codex_output(path: Path) -> Output:
    # Ours only if byte-identical: anything an administrator added (sandbox
    # limits, other hooks) is never silently dropped by a refresh.
    if path.exists() and path.read_text() != CODEX_REQUIREMENTS_BODY:
        raise GuardError(
            f"{path} exists and is not exactly the managed file; merge the dcg [hooks] block by hand"
        )
    return Output(path, CODEX_REQUIREMENTS_BODY.encode(), 0o644)


def ensure() -> None:
    if not IS_ROOT and "SYN_AGENT_GUARD_ROOT" not in os.environ:
        raise GuardError("ensure installs root-owned files: run it as root (sudo)")
    pin = load_pin()
    # Plan every output and check every destination before touching anything.
    outputs = [
        Output(host(POLICY), POLICY_FILE.read_bytes(), 0o644),
        json_output(host(CLAUDE_SETTINGS), "PreToolUse", "Bash", CLAUDE_HOOK),
        json_output(host(GEMINI_SETTINGS), "BeforeTool", "run_shell_command", GEMINI_HOOK),
        codex_output(host(CODEX_REQUIREMENTS)),
    ]
    # Download and probe inside a root-owned 0700 directory, never under an
    # inherited TMPDIR an agent could own and swap the verified binary in.
    work_parent = host(WORK_DIR)
    unsafe = [
        p
        for path in [*(out.path for out in outputs), host(BIN), work_parent]
        for p in chain_problems(path)
    ]
    if unsafe:
        raise GuardError(
            "refusing to write through an unsafe path: " + "; ".join(sorted(set(unsafe)))
        )
    make_dirs(work_parent)
    work_parent.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="dcg-", dir=work_parent) as tmp:
        outputs.insert(0, Output(host(BIN), verified_binary(pin, Path(tmp)), 0o755))
    commit_outputs(outputs)
    print(f"  dcg {pin.version} installed at {BIN}; policy {POLICY}; hooks: claude, codex, gemini")


# --- validate ----------------------------------------------------------------


def run_version(binary: Path) -> str:
    result = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, env=hook_env(), timeout=30
    )
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", result.stdout)
    return match.group(1) if match else ""


def hook_env() -> dict[str, str]:
    """Exactly what the registered command gives dcg."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "DCG_NO_UPDATE_CHECK": "1",
        "NO_COLOR": "1",
    }


def registered_argv() -> list[str]:
    """The registered command as argv, with dcg's path under the test root."""
    argv = shlex.split(HOOK_COMMAND)
    argv[-1] = str(host(argv[-1]))
    return argv


def hook_groups(data: object, event: str) -> list[object]:
    if not isinstance(data, dict):
        return []
    hooks = data.get("hooks")
    groups = hooks.get(event) if isinstance(hooks, dict) else None
    return groups if isinstance(groups, list) else []


def has_handler(groups: list[object], matcher: str, handler: JsonObject) -> bool:
    """A group with exactly MATCHER holding an enabled handler with HANDLER's fields."""
    for group in groups:
        if not isinstance(group, dict) or group.get("matcher") != matcher:
            continue
        for h in group.get("hooks") or []:
            if (
                isinstance(h, dict)
                and all(h.get(k) == v for k, v in handler.items())
                and h.get("enabled", True) is not False
            ):
                return True
    return False


def globally_disabled(data: object) -> bool:
    """Claude's ``disableAllHooks`` or Gemini's ``hooksConfig.enabled = false``."""
    if not isinstance(data, dict):
        return False
    hooks_config = data.get("hooksConfig")
    gemini_off = isinstance(hooks_config, dict) and hooks_config.get("enabled") is False
    return data.get("disableAllHooks") is True or gemini_off


def user_disables(homes: list[Path]) -> list[str]:
    """A user-level settings file that switches every hook off, managed ones included."""
    problems: list[str] = []
    for home in homes:
        for settings in (home / ".claude/settings.json", home / ".gemini/settings.json"):
            try:
                data = json.loads(settings.read_text())
            except (OSError, ValueError):
                continue
            if globally_disabled(data):
                problems.append(f"{settings}: hooks are switched off globally")
    return problems


def registration_problems() -> list[str]:
    problems: list[str] = []
    for name, path, event, matcher, handler in (
        ("claude", CLAUDE_SETTINGS, "PreToolUse", "Bash", CLAUDE_HOOK),
        ("gemini", GEMINI_SETTINGS, "BeforeTool", "run_shell_command", GEMINI_HOOK),
    ):
        try:
            data = json.loads(host(path).read_text())
        except (OSError, ValueError):
            data = None
        if not has_handler(hook_groups(data, event), matcher, handler):
            problems.append(
                f"{name}: dcg not registered in {path} ({event}/{matcher}, type command)"
            )
        if globally_disabled(data):
            problems.append(f"{name}: hooks are switched off globally in {path}")
    try:
        codex = tomllib.loads(host(CODEX_REQUIREMENTS).read_text())
    except (OSError, ValueError):
        codex = None
    if not has_handler(hook_groups(codex, "PreToolUse"), "^Bash$", CLAUDE_HOOK):
        problems.append(
            f"codex: dcg not registered in {CODEX_REQUIREMENTS} (PreToolUse/^Bash$, type command)"
        )
    return problems


def payload(harness: str, command: str, cwd: Path) -> str:
    base: JsonObject = {
        "session_id": "agent-guard-validate",
        "cwd": str(cwd),
        "transcript_path": None,
    }
    if harness == "gemini":
        body: JsonObject = {**base, "hook_event_name": "BeforeTool", "timestamp": "1970-01-01T00:00:00Z",
                            "tool_name": "run_shell_command", "tool_input": {"command": command}}  # fmt: skip
    elif harness == "codex":
        body = {**base, "turn_id": "agent-guard-validate", "hook_event_name": "PreToolUse",
                "tool_name": "Bash", "tool_use_id": "agent-guard-validate",
                "tool_input": {"command": command}}  # fmt: skip
    else:
        body = {**base, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": command}}  # fmt: skip
    return json.dumps(body)


def hook_denies(stdin: str, cwd: Path) -> bool:
    """Run the registered hook command as a harness would; True when it denies."""
    result = subprocess.run(
        registered_argv(), input=stdin, capture_output=True, text=True, cwd=cwd, timeout=30
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


def policy_problems(cwd: Path) -> list[str]:
    argv = registered_argv()
    argv = [*argv[:-1], "NO_COLOR=1", argv[-1], "config"]
    out = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=30).stdout
    problems: list[str] = []
    for label, want in (
        ("Fail closed", "true"),
        ("Unverified decision", "deny"),
        ("Check updates", "false"),
    ):
        match = re.search(rf"^\s*{label}:\s*(\S+)", out, re.MULTILINE)
        if not match or match.group(1) != want:
            problems.append(
                f"policy: '{label}' is {match.group(1) if match else 'missing'}, want {want}"
            )
    section = out.split("Enabled packs:", 1)[-1].split("Disabled packs:", 1)[0]
    enabled = set(re.findall(r"^\s+- (\S+)$", section, re.MULTILINE))
    if missing := [p for p in REQUIRED_PACKS if p not in enabled]:
        problems.append(f"policy: required packs not enabled: {', '.join(missing)}")
    return problems


def find_harness(name: str, home: Path) -> Path | None:
    for d in (home / ".local/bin", home / ".bun/bin", home / ".npm-global/bin",
              host("/usr/local/bin"), host("/usr/bin")):  # fmt: skip
        candidate = d / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def codex_version(binary: Path) -> tuple[int, ...]:
    """Codex's version from its npm package.json, without executing anything."""
    for parent in binary.resolve().parents:
        manifest = parent / "package.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text())
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("name") == "@openai/codex":
                match = re.match(r"(\d+)\.(\d+)\.(\d+)", str(data.get("version", "")))
                return tuple(int(x) for x in match.groups()) if match else ()
    return ()


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
    if IS_ROOT:
        raise GuardError(
            "run validate as the agent account, not root: it inspects agent-owned paths"
        )
    if not homes:
        return ["no agent account to validate: pass --user or --home"]
    pin = load_pin()
    problems: list[str] = []
    for path in (host(BIN), host(POLICY), host(CLAUDE_SETTINGS), host(CODEX_REQUIREMENTS),
                 host(GEMINI_SETTINGS)):  # fmt: skip
        problems += check_locked(path)
    if problems:
        return problems  # never execute or trust anything in an unsafe chain
    if (version := run_version(host(BIN))) != pin.version.lstrip("v"):
        problems.append(f"{BIN} reports {version or 'no version'}, pinned {pin.version}")
    if host(POLICY).read_bytes() != POLICY_FILE.read_bytes():
        problems.append(f"{POLICY} differs from {POLICY_FILE}")
    problems += registration_problems()
    if problems:
        return problems
    with tempfile.TemporaryDirectory(prefix="dcg-validate-") as tmp:
        cwd = Path(tmp)
        problems += policy_problems(cwd)
        for harness in SUPPORTED_HARNESSES:
            for command in BAD_COMMANDS:
                if not hook_denies(payload(harness, command, cwd), cwd):
                    problems.append(f"{harness}: known-bad payload was not denied: {command}")
            if hook_denies(payload(harness, "ls", cwd), cwd):
                problems.append(f"{harness}: harmless 'ls' was denied (policy blocks everything)")
            if not hook_denies("not json", cwd):
                problems.append(f"{harness}: unparseable hook input was allowed (not fail-closed)")
    problems += user_disables(homes)
    for home in homes:
        for name in UNSUPPORTED_HARNESSES:
            if found := find_harness(name, home):
                problems.append(f"{found}: agent harness with no dcg registration on this host")
        if (codex := find_harness("codex", home)) and codex_version(codex) < CODEX_MIN_VERSION:
            problems.append(
                f"{codex}: version unknown or older than 0.125.0; PreToolUse hooks do not run"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("ensure", help="install the pinned dcg and register it (root)")
    check = sub.add_parser("validate", help="exit 1 unless every guard check passes")
    check.add_argument(
        "--user", action="append", default=[], help="agent user (default: every login user)"
    )
    check.add_argument("--home", action="append", default=[], type=Path, help="agent home to check")
    args = parser.parse_args(argv)
    try:
        if args.action == "ensure":
            ensure()
            return 0
        problems = validate(args.home or agent_homes(args.user))
    except (GuardError, OSError, subprocess.SubprocessError, KeyError, ValueError) as exc:
        print(f"  ❌ agent guard: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"  ❌ agent guard: {problem}", file=sys.stderr)
    if not problems:
        print(
            "  ✅ agent guard: dcg pinned, root-owned, registered for claude/codex/gemini, bad payloads denied"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
