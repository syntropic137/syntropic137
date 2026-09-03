"""Behavioral tests that EXECUTE the generated setup script.

The sibling substring tests in ``test_setup_phase_secrets`` pin the rendered
text. They cannot prove what the script *does*: a mutation that keeps the
expected substring but breaks the surrounding shell leaves them green. These
tests run the real script under ``bash -e`` with a recording ``git`` stub, so
the assertions are about observed behavior.

The generated script hardcodes ``/workspace``; tests rewrite that prefix to a
tmpdir since they do not run as root. Nothing else about the script is altered.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets

pytestmark = pytest.mark.unit

GIT_STUB = """#!/bin/bash
# Emit explicit CALL: markers rather than raw argv. Counting substrings over argv
# is unreliable here because the tmpdir path is named after the running test, so a
# test whose name contains "clone" would match its own directory path.
printf 'ARGV:%s\\n' "$*" >> "$GIT_ARGV_LOG"
case "$*" in
  *"submodule update"*)
    printf 'CALL:submodule GIT_ALLOW_PROTOCOL=%s\\n' "${GIT_ALLOW_PROTOCOL-<unset>}" \\
      >> "$GIT_ARGV_LOG"
    exit "$FAKE_SUBMODULE_EXIT"
    ;;
  clone*)
    printf 'CALL:clone\\n' >> "$GIT_ARGV_LOG"
    for arg in "$@"; do dest="$arg"; done
    mkdir -p "$dest"
    exit 0
    ;;
esac
printf 'CALL:other\\n' >> "$GIT_ARGV_LOG"
exit 0
"""


class _Run:
    def __init__(self, proc: subprocess.CompletedProcess[str], argv: list[str]) -> None:
        self.proc = proc
        self.argv = argv

    def count(self, marker: str) -> int:
        """Count exact CALL: markers emitted by the stub, not argv substrings."""
        return sum(1 for line in self.argv if line == marker)


@pytest.fixture
def harness(tmp_path: Path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "git-argv.log"
    stub = bindir / "git"
    stub.write_text(GIT_STUB)
    stub.chmod(0o755)
    workspace = tmp_path / "ws"

    def run(secrets: SetupPhaseSecrets, *, submodule_exit: int = 0) -> _Run:
        script = secrets.build_setup_script().replace("/workspace", str(workspace))
        script_path = tmp_path / "setup.sh"
        script_path.write_text(script)
        proc = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            env={
                "PATH": f"{bindir}:/usr/bin:/bin",
                "HOME": str(tmp_path / "home"),
                "GIT_ARGV_LOG": str(log),
                "FAKE_SUBMODULE_EXIT": str(submodule_exit),
            },
        )
        argv = log.read_text().splitlines() if log.exists() else []
        return _Run(proc, argv)

    (tmp_path / "home").mkdir()
    return run


def _one_repo() -> SetupPhaseSecrets:
    return SetupPhaseSecrets(
        repositories=["https://github.com/org/repo-a"],
        repo_tokens={"https://github.com/org/repo-a": "tok-a"},
    )


def _isolated_git_env(home: Path) -> dict[str, str]:
    """A git environment that cannot reach outside the test, or block on input.

    `GIT_TERMINAL_PROMPT=0` and an askpass that always fails are not belt and
    braces - without them `git credential fill` for a path no helper matches
    falls through to PROMPTING. On a machine with no terminal that fails fast
    and the test passes; in an agent workspace it hung a full unit run at 77%
    until the phase interrupted it and could not certify anything (#1136).

    A unit test must not be able to wait on a human, whatever is attached to
    its stdin.
    """
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "SSH_ASKPASS": "/bin/false",
    }


class TestHooksAreDisabledForSetupClones:
    """The generated script must not let a workspace git hook fail the clone (#1150).

    The image composes developer hooks at /home/agent/.git-hooks, all beginning
    `#!/usr/bin/env python3`, and has no python3 on PATH. Verified in the real
    image on the real agent network:

        $ git clone --depth 1 <repo> /tmp/a          -> rc=127   (tree landed)
        $ GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath \
          GIT_CONFIG_VALUE_0=/dev/null git clone ... -> rc=0     TREE_OK

    The script runs under `set -e`, so that 127 failed the whole setup phase and
    the execution never started.
    """

    def test_hooks_are_disabled_before_any_clone(self) -> None:
        secrets = SetupPhaseSecrets(repositories=["https://github.com/org/repo-a"])
        script = secrets.build_setup_script()

        assert "GIT_CONFIG_KEY_0=core.hooksPath" in script
        hooks_at = script.index("core.hooksPath")
        clone_at = script.index("git clone")
        assert hooks_at < clone_at, "hooks must be disabled BEFORE the first clone"

    def test_it_is_exported_so_submodule_commands_inherit_it(self) -> None:
        """`git submodule update` re-enters git and would run the same hooks."""
        secrets = SetupPhaseSecrets(repositories=["https://github.com/org/repo-a"])
        script = secrets.build_setup_script()

        line = next(ln for ln in script.splitlines() if "core.hooksPath" in ln)
        assert line.strip().startswith("export "), line


class TestGeneratedScriptBehavior:
    def test_script_succeeds_and_clones_then_inits_submodules(self, harness) -> None:
        run = harness(_one_repo())
        assert run.proc.returncode == 0, run.proc.stderr
        assert run.count("CALL:clone") == 1
        assert run.count("CALL:submodule GIT_ALLOW_PROTOCOL=https") == 1

    def test_failing_submodule_does_not_abort_the_script(self, harness) -> None:
        """The whole point of the `||` handler, proven rather than asserted.

        The script runs under `set -e`; without the handler a non-zero submodule
        update would abort setup and take the usable top-level clone with it.
        """
        run = harness(_one_repo(), submodule_exit=1)
        assert run.proc.returncode == 0
        assert "WARNING: submodule init failed for repo-a" in run.proc.stderr

    def test_rerun_skips_clone_but_still_inits_submodules(self, harness) -> None:
        """A repeat setup phase must repair a checkout with missing submodules."""
        first = harness(_one_repo())
        second = harness(_one_repo())
        assert first.count("CALL:clone") == 1
        # Cumulative across both runs: cloned once, submodules initialized twice.
        assert second.count("CALL:clone") == 1
        assert second.count("CALL:submodule GIT_ALLOW_PROTOCOL=https") == 2

    def test_submodule_update_runs_with_a_pinned_transport_allowlist(self, harness) -> None:
        run = harness(_one_repo())
        assert "CALL:submodule GIT_ALLOW_PROTOCOL=https" in run.argv
        assert "CALL:submodule GIT_ALLOW_PROTOCOL=<unset>" not in run.argv

    def test_submodule_command_targets_the_clone_destination(self, harness) -> None:
        run = harness(_one_repo())
        # Match on how the command ENDS, not on a substring: the tmpdir path is
        # named after this test and therefore contains "submodule" itself.
        submodule_argv = [
            line
            for line in run.argv
            if line.startswith("ARGV:") and line.endswith("submodule update --init --recursive")
        ]
        assert len(submodule_argv) == 1
        assert submodule_argv[0].endswith("submodule update --init --recursive")
        assert "/repos/repo-a " in submodule_argv[0]

    def test_script_is_valid_shell(self, harness) -> None:
        run = harness(_one_repo())
        assert "syntax error" not in run.proc.stderr


class TestSubmoduleTransportIsPinned:
    """Real-git proof that GIT_ALLOW_PROTOCOL blocks a code-executing submodule.

    `.gitmodules` is controlled by the cloned repo. An `ext::` URL makes git run an
    arbitrary command. Git has defaulted `ext=never` since 2.12, but that default can
    be moved by global config or a future base image, and this setup script clones
    repos on the operator's behalf -- so the allowlist is stated per-command.

    The negative control matters as much as the assertion: if the hazard case stopped
    reproducing, the protected case would pass for the wrong reason.
    """

    @staticmethod
    def _parent_repo_with_ext_submodule(tmp_path: Path, sentinel: Path) -> Path:
        parent = tmp_path / "parent"
        parent.mkdir()
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1",
        }

        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", *args], cwd=parent, env=env, capture_output=True, text=True
            )

        git("init", "-q", ".")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (parent / "a.txt").write_text("hi\n")
        git("add", "a.txt")
        git("commit", "-qm", "base")
        head = git("rev-parse", "HEAD").stdout.strip()
        # `touch% <path>` -- ext:: splits on spaces, % is its escape for a literal space.
        (parent / ".gitmodules").write_text(
            f'[submodule "evil"]\n\tpath = evil\n\turl = ext::sh -c "touch% {sentinel}"\n'
        )
        git("add", ".gitmodules")
        git("update-index", "--add", "--cacheinfo", f"160000,{head},evil")
        git("commit", "-qm", "gitlink")
        return parent

    @staticmethod
    def _update(
        parent: Path, tmp_path: Path, *, pin_transport: bool
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if pin_transport:
            env["GIT_ALLOW_PROTOCOL"] = "https"
        return subprocess.run(
            # `-c protocol.ext.allow=always` simulates ambient config or image drift
            # re-enabling the transport. The pin must win over it.
            [
                "git",
                "-c",
                "protocol.ext.allow=always",
                "submodule",
                "update",
                "--init",
                "--recursive",
            ],
            cwd=parent,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_hazard_reproduces_without_the_pin(self, tmp_path: Path) -> None:
        """Negative control: the ext:: submodule really does execute a command."""
        sentinel = tmp_path / "PWNED"
        parent = self._parent_repo_with_ext_submodule(tmp_path, sentinel)
        self._update(parent, tmp_path, pin_transport=False)
        assert sentinel.exists(), (
            "hazard did not reproduce, so the protected case below would prove nothing"
        )

    def test_pin_blocks_the_ext_transport(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "PWNED"
        parent = self._parent_repo_with_ext_submodule(tmp_path, sentinel)
        proc = self._update(parent, tmp_path, pin_transport=True)
        assert not sentinel.exists()
        # Assert the SPECIFIC reason. Run alone, this test would otherwise pass
        # whenever the submodule machinery silently did nothing at all.
        assert "not allowed" in (proc.stderr + proc.stdout)


class TestCredentialsAreScopedToTheirRepo:
    """Real-git proof that a repo token is not handed to an unrelated repo.

    Without `credential.useHttpPath`, git-credential-store matches on host alone and
    returns the FIRST stored github.com entry for any github.com request. That was
    harmless while nothing but the named repos was ever fetched. Initializing
    submodules makes it reachable: a `.gitmodules` URL is chosen by the cloned repo,
    and an installation token routinely covers other private repos in the same org.

    Verified against git 2.50.1.
    """

    @staticmethod
    def _apply_credential_lines(tmp_path: Path, script: str) -> dict[str, str]:
        home = tmp_path / "home"
        home.mkdir()
        env = _isolated_git_env(home)
        lines = [
            ln
            for ln in script.splitlines()
            if "credential" in ln and (ln.startswith("git config") or ln.startswith("printf"))
        ]
        assert lines, "no credential lines found in generated script"
        subprocess.run(
            ["bash", "-e", "-c", "\n".join(lines)], env=env, capture_output=True, text=True
        )

        def ask(path: str) -> str:
            proc = subprocess.run(
                ["git", "credential", "fill"],
                input=f"protocol=https\nhost=github.com\npath={path}\n\n",
                env=env,
                capture_output=True,
                text=True,
            )
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    return line.removeprefix("password=")
            return "<none>"

        return {
            "repo-a": ask("org/repo-a"),
            "repo-b": ask("other/repo-b"),
            "repo-a.git": ask("org/repo-a.git"),
            "unlisted": ask("someoneelse/private-repo"),
        }

    def test_each_repo_gets_its_own_token_and_unlisted_repos_get_none(self, tmp_path: Path) -> None:
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a", "https://github.com/other/repo-b"],
            repo_tokens={
                "https://github.com/org/repo-a": "TOKEN_A",
                "https://github.com/other/repo-b": "TOKEN_B",
            },
        )
        got = self._apply_credential_lines(tmp_path, secrets.build_setup_script())
        assert got["repo-a"] == "TOKEN_A"
        assert got["repo-b"] == "TOKEN_B"
        # A submodule URL carrying the .git suffix must still authenticate.
        assert got["repo-a.git"] == "TOKEN_A"
        # The finding this guards: an unnamed repo must get nothing, not TOKEN_A.
        assert got["unlisted"] == "<none>"


class TestSshSubmoduleFormsAreRewritten:
    """The script must make SSH-form submodule URLs usable with an HTTPS token.

    Git applies `insteadOf` BEFORE the GIT_ALLOW_PROTOCOL check. Verified against
    git 2.50.1 with a live `ls-remote`: the SSH spelling resolves and succeeds with
    the rewrite configured, and reports "transport 'ssh' not allowed" without it.
    """

    def test_both_ssh_spellings_rewrite_to_https(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        env = _isolated_git_env(home)
        secrets = SetupPhaseSecrets(
            repositories=["https://github.com/org/repo-a"],
            repo_tokens={"https://github.com/org/repo-a": "tok-a"},
        )
        config_lines = [
            ln
            for ln in secrets.build_setup_script().splitlines()
            if ln.startswith("git config") and "insteadOf" in ln
        ]
        assert len(config_lines) == 2
        subprocess.run(
            ["bash", "-e", "-c", "\n".join(config_lines)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        got = subprocess.run(
            ["git", "config", "--get-all", "url.https://github.com/.insteadOf"],
            env=env,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert "git@github.com:" in got
        assert "ssh://git@github.com/" in got
