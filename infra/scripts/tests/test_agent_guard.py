"""The agent-guard host step installs dcg root-owned and refuses a weak guard.

Runs the real ``infra/scripts/agent_guard.py`` against a temporary host root,
a file:// release with a stand-in dcg, and a stand-in minisign. The stand-in
dcg answers the hook protocol the way dcg 0.16.0 does (verified live: deny
JSON on stdout, exit 0; empty stdout means allow), so these tests pin the
installer and the validator, not dcg's rules.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "infra" / "scripts" / "agent_guard.py"
_WRAPPER = _REPO / "infra" / "scripts" / "agent-guard-setup.sh"
_POLICY = _REPO / "infra" / "agent-guard" / "dcg-config.toml"
_HOOK = (
    "/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent DCG_NO_UPDATE_CHECK=1 /usr/local/bin/dcg"
)

# A stand-in for dcg 0.16.0. Knobs (files beside it): ALLOW_ALL lets every
# command through, DENY_ALL denies everything, FAIL_OPEN allows bad JSON,
# WEAK_POLICY reports fail_closed off, LEAKY honours DCG_BYPASS from the env.
_FAKE_DCG = r"""#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
here = Path(__file__).resolve().parent
args = sys.argv[1:]
if args == ["--version"]:
    print("dcg 0.16.0"); sys.exit(0)
if args == ["config"]:
    weak = (here / "WEAK_POLICY").exists()
    print("General:")
    print(f"  Fail closed: {'false' if weak else 'true'}")
    print("  Unverified decision: deny")
    print("  Check updates: false")
    print("Enabled packs:")
    for p in ["containers.docker", "core.filesystem", "core.git", "database.postgresql"]:
        print(f"  - {p}")
    print("Disabled packs:")
    sys.exit(0)
if os.environ.get("DCG_BYPASS"):
    sys.exit(0)
raw = sys.stdin.read()
def deny(gemini):
    out = {"decision": "deny", "reason": "BLOCKED"} if gemini else {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"}}
    print(json.dumps(out)); sys.exit(0)
try:
    body = json.loads(raw)
except ValueError:
    if (here / "FAIL_OPEN").exists():
        sys.exit(0)
    deny(False)
gemini = body.get("hook_event_name") == "BeforeTool"
cmd = body.get("tool_input", {}).get("command", "")
if (here / "DENY_ALL").exists():
    deny(gemini)
if (here / "ALLOW_ALL").exists():
    sys.exit(0)
if re.search(r"rm -rf|reset --hard|volume rm|DROP TABLE", cmd):
    deny(gemini)
sys.exit(0)
"""


def _exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def _release(tmp: Path) -> tuple[Path, str]:
    """A file:// release dir holding v0.16.0's tarball + .minisig; returns (dir, sha256)."""
    rel = tmp / "release" / "v0.16.0"
    rel.mkdir(parents=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        data = _FAKE_DCG.encode()
        info = tarfile.TarInfo("dcg")
        info.size, info.mode = len(data), 0o755
        tar.addfile(info, io.BytesIO(data))
    archive = rel / "dcg-x86_64-unknown-linux-musl.tar.xz"
    archive.write_bytes(buf.getvalue())
    (rel / f"{archive.name}.minisig").write_text("untrusted comment: fake\n")
    return rel.parent, hashlib.sha256(buf.getvalue()).hexdigest()


class Host:
    def __init__(self, tmp: Path, *, minisign_ok: bool = True, sha: str | None = None) -> None:
        self.root = tmp / "root"
        self.root.mkdir()
        self.home = tmp / "home"
        self.home.mkdir()
        release, real_sha = _release(tmp)
        version = tmp / "dcg-version.toml"
        version.write_text(
            f'version = "v0.16.0"\nrelease_url = "file://{release}"\n'
            'minisign_public_key = "RWtest"\n'
            "[assets.x86_64-linux]\n"
            'name = "dcg-x86_64-unknown-linux-musl.tar.xz"\n'
            f'sha256 = "{sha or real_sha}"\n'
        )
        self.log = tmp / "minisign.log"
        minisign = _exe(
            tmp / "bin" / "minisign",
            f'#!/usr/bin/env bash\necho "$@" >> {self.log}\nexit {0 if minisign_ok else 1}\n',
        )
        self.env = {
            **os.environ,
            "SYN_AGENT_GUARD_ROOT": str(self.root),
            "SYN_AGENT_GUARD_OWNER_UID": str(os.getuid()),
            "SYN_AGENT_GUARD_PLATFORM": "x86_64-linux",
            "SYN_AGENT_GUARD_VERSION_FILE": str(version),
            "SYN_AGENT_GUARD_MINISIGN": str(minisign),
        }

    def run(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            env={**self.env, **(extra_env or {})},
            capture_output=True,
            text=True,
            timeout=120,
        )

    def validate(self, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.run("validate", "--home", str(self.home), extra_env=extra_env)

    def path(self, p: str) -> Path:
        return self.root / p.lstrip("/")

    def knob(self, name: str) -> None:
        (self.path("/usr/local/bin") / name).write_text("")

    def edit_json(self, p: str, change: Callable[[dict[str, object]], None]) -> None:
        data = json.loads(self.path(p).read_text())
        change(data)
        self.path(p).write_text(json.dumps(data))


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def _installed(host: Host) -> Host:
    result = host.run("ensure")
    assert result.returncode == 0, result.stderr
    return host


def _nothing_installed(host: Host) -> None:
    for p in ("/usr/local/bin/dcg", "/etc/dcg/config.toml", "/etc/claude-code/managed-settings.json",
              "/etc/gemini-cli/settings.json"):  # fmt: skip
        assert not host.path(p).exists(), p


def test_ensure_installs_binary_policy_and_all_three_harness_hooks(host: Host) -> None:
    _installed(host)

    assert host.path("/usr/local/bin/dcg").stat().st_mode & 0o777 == 0o755
    assert host.path("/etc/dcg/config.toml").read_bytes() == _POLICY.read_bytes()
    claude = json.loads(host.path("/etc/claude-code/managed-settings.json").read_text())
    assert claude["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": _HOOK}]}
    ]
    gemini = json.loads(host.path("/etc/gemini-cli/settings.json").read_text())
    assert gemini["hooks"]["BeforeTool"][0]["hooks"][0]["command"] == _HOOK
    assert f'command = "{_HOOK}"' in host.path("/etc/codex/requirements.toml").read_text()
    assert "-P RWtest" in host.log.read_text()  # minisign checked against the pinned key


def test_validate_passes_on_a_fresh_install(host: Host) -> None:
    result = _installed(host).validate()
    assert result.returncode == 0, result.stderr
    assert "bad payloads denied" in result.stdout


def test_the_agent_environment_cannot_switch_the_hook_off(host: Host) -> None:
    """The hook command empties the environment, so DCG_BYPASS never reaches dcg."""
    _installed(host)
    result = host.validate(extra_env={"DCG_BYPASS": "1", "DCG_CONFIG": "/dev/null"})
    assert result.returncode == 0, result.stderr


def test_ensure_is_idempotent_and_keeps_other_managed_hooks(host: Host) -> None:
    settings = host.path("/etc/claude-code/managed-settings.json")
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "permissions": {"deny": ["Read(./.env)"]},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "sdlc-guard"}],
                        },
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "/old/dcg"}]},
                    ]
                },
            }
        )
    )
    _installed(host)
    _installed(host)

    data = json.loads(settings.read_text())
    commands = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commands == ["sdlc-guard", _HOOK]  # second layer kept, stale dcg dropped, no dupes
    assert data["permissions"] == {"deny": ["Read(./.env)"]}


def test_sha256_mismatch_refuses_and_installs_nothing(tmp_path: Path) -> None:
    host = Host(tmp_path, sha="0" * 64)
    result = host.run("ensure")
    assert result.returncode == 1
    assert "is not the pinned" in result.stderr
    _nothing_installed(host)


def test_bad_signature_refuses_and_installs_nothing(tmp_path: Path) -> None:
    host = Host(tmp_path, minisign_ok=False)
    result = host.run("ensure")
    assert result.returncode == 1
    assert "minisign signature did not verify" in result.stderr
    _nothing_installed(host)


@pytest.mark.parametrize(
    "content",
    ['allowed_sandbox_modes = ["read-only"]\n', None],
    ids=["foreign-file", "managed-file-with-admin-additions"],
)
def test_codex_requirements_with_other_content_is_refused_before_any_write(
    host: Host, content: str | None
) -> None:
    req = host.path("/etc/codex/requirements.toml")
    if content is None:  # our file plus an administrator's addition
        _installed(host)
        for p in ("/usr/local/bin/dcg", "/etc/dcg/config.toml", "/etc/claude-code/managed-settings.json",
                  "/etc/gemini-cli/settings.json"):  # fmt: skip
            host.path(p).unlink()
        content = req.read_text() + 'allowed_sandbox_modes = ["read-only"]\n'
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text(content)
    result = host.run("ensure")
    assert result.returncode == 1
    assert "not exactly the managed file" in result.stderr
    assert req.read_text() == content
    _nothing_installed(host)


def test_ensure_refuses_to_write_through_a_symlinked_directory(host: Host, tmp_path: Path) -> None:
    elsewhere = tmp_path / "agent-writable"
    elsewhere.mkdir()
    (host.path("/etc")).mkdir(parents=True)
    host.path("/etc/dcg").symlink_to(elsewhere)
    result = host.run("ensure")
    assert result.returncode == 1
    assert "is a symlink" in result.stderr
    assert not any(elsewhere.iterdir())


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (lambda h: h.path("/etc/codex/requirements.toml").unlink(), "requirements.toml is missing"),
        (
            lambda h: h.path("/etc/gemini-cli/settings.json").write_text("{}"),
            "gemini: dcg not registered",
        ),
        (
            lambda h: h.path("/etc/claude-code/managed-settings.json").write_text('{"hooks": {}}'),
            "claude: dcg not registered",
        ),
        (
            lambda h: h.edit_json(
                "/etc/claude-code/managed-settings.json",
                lambda d: d["hooks"]["PreToolUse"][-1].update(matcher="Read"),  # type: ignore[index]
            ),
            "claude: dcg not registered",
        ),
        (
            lambda h: h.edit_json(
                "/etc/gemini-cli/settings.json",
                lambda d: d["hooks"]["BeforeTool"][-1]["hooks"][0].update(type="http"),  # type: ignore[index]
            ),
            "gemini: dcg not registered",
        ),
        (
            lambda h: h.path("/etc/codex/requirements.toml").write_text(
                h.path("/etc/codex/requirements.toml").read_text().replace("^Bash$", "^Read$")
            ),
            "codex: dcg not registered",
        ),
        (lambda h: h.knob("ALLOW_ALL"), "known-bad payload was not denied: git reset --hard"),
        (lambda h: h.knob("DENY_ALL"), "harmless 'ls' was denied"),
        (lambda h: h.knob("FAIL_OPEN"), "unparseable hook input was allowed"),
        (lambda h: h.knob("WEAK_POLICY"), "'Fail closed' is false"),
        (lambda h: h.path("/usr/local/bin/dcg").chmod(0o777), "is group/world writable"),
        (
            lambda h: (
                h.path("/usr/local/bin/real-dcg").write_bytes(
                    h.path("/usr/local/bin/dcg").read_bytes()
                ),
                h.path("/usr/local/bin/dcg").unlink(),
                h.path("/usr/local/bin/dcg").symlink_to(h.path("/usr/local/bin/real-dcg")),
            ),
            "is a symlink",
        ),
        (lambda h: h.path("/etc/dcg/config.toml").write_text("[general]\n"), "differs from"),
        (
            lambda h: _exe(h.home / ".local/bin/opencode", "#!/bin/sh\n"),
            "agent harness with no dcg registration",
        ),
        (
            lambda h: (
                _exe(h.home / ".bun/bin/codex", "#!/bin/sh\necho never run\n"),
                (h.home / ".bun/package.json").write_text(
                    '{"name": "@openai/codex", "version": "0.120.0"}'
                ),
            ),
            "older than 0.125.0",
        ),
    ],
    ids=[
        "codex-unhooked",
        "gemini-unhooked",
        "claude-unhooked",
        "claude-wrong-matcher",
        "gemini-wrong-type",
        "codex-wrong-matcher",
        "bad-payload-allowed",
        "denies-everything",
        "fails-open",
        "policy-not-fail-closed",
        "binary-agent-writable",
        "binary-symlink",
        "policy-drift",
        "unsupported-harness",
        "codex-too-old",
    ],
)
def test_validate_fails_the_deploy_when_the_guard_is_weak(
    host: Host, break_it: Callable[[Host], object], expected: str
) -> None:
    _installed(host)
    break_it(host)
    result = host.validate()
    assert result.returncode == 1
    assert expected in result.stderr


def test_validate_fails_when_nothing_is_installed(host: Host) -> None:
    result = host.validate()
    assert result.returncode == 1
    assert "/usr/local/bin/dcg is missing" in result.stderr


def test_validate_fails_when_no_agent_account_is_found() -> None:
    """Discovery finding nobody must not skip every behavioural check and pass."""
    from infra.scripts import agent_guard

    assert agent_guard.validate([]) == ["no agent account to validate: pass --user or --home"]


def test_ensure_refuses_without_root_outside_tests() -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYN_AGENT_GUARD_")}
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "ensure"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "run it as root" in result.stderr


def _deploy_hook(host: Host) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_WRAPPER), "--if-installed"],
        env={**host.env, "SYN_AGENT_GUARD_SUDO": ""},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_deploy_hook_skips_a_host_that_never_opted_in(host: Host) -> None:
    result = _deploy_hook(host)
    assert result.returncode == 0, result.stderr
    assert "not installed on this host" in result.stdout
    _nothing_installed(host)


@pytest.mark.parametrize(
    "left", ["/etc/dcg/config.toml", "/usr/local/bin/dcg", "/etc/codex/requirements.toml"]
)
def test_deploy_hook_treats_a_partial_install_as_enrolled(host: Host, left: str) -> None:
    """A damaged or half-removed guard is re-installed, never skipped as 'not installed'."""
    _installed(host)
    for p in ("/usr/local/bin/dcg", "/etc/dcg/config.toml", "/etc/codex/requirements.toml"):
        if p != left:
            host.path(p).unlink()
    if left == "/etc/dcg/config.toml":
        host.path(left).write_text("[general]\nfail_closed = false\n")
    result = _deploy_hook(host)
    assert "not installed on this host" not in result.stdout
    assert host.path("/usr/local/bin/dcg").exists(), result.stderr
    assert host.path("/etc/dcg/config.toml").read_bytes() == _POLICY.read_bytes()
