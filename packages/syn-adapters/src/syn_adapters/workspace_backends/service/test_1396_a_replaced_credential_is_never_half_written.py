"""A renewal that fails must leave the credential it was replacing (#1396).

THE RENEWAL IS THE FALLBACK'S ONLY THREAT. The teardown path renews the git
credential and is documented never to raise, so that a renewal that could not
happen still lets the rescue push spend whatever token the container already
holds - see `_renew_credential` in the unpushed-work guard. That promise was
worth nothing while the renewal script truncated ``~/.git-credentials`` and
then appended entries one at a time: a failure after the truncation - a full
disk, a quota, a killed process - left the file empty or partial, so the old
token the fallback was counting on had already been destroyed by the attempt
to improve it. A concurrent ``git credential fill`` could read the gap too.

SO THE TESTS ARE ABOUT INTERMEDIATE STATES, not about the end state, which
was already correct and is already covered by
``test_1393_the_renewed_credential_is_the_one_git_resolves.py``. Every one of
them runs the REAL generated script under real bash and asks real git what it
resolves - killing the script before each of its commands in turn, or reading
the file from another thread while it runs. Nothing asserts on the script's text:
a script whose lines spell atomicity and whose file is briefly empty anyway
would pass a substring test and lose the work.
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets

pytestmark = pytest.mark.unit

_REPO_URL = "https://github.com/org/repo-a"
_REPO_PATH = "org/repo-a"
_SETUP_TOKEN = "tok-from-setup"
_RENEWED_TOKEN = "tok-renewed"

#: What the script is stopped with, after any one of its lines. A distinctive
#: code so a run that failed for some other reason cannot be read as the
#: injection having worked.
_INJECTED_FAILURE = 17

#: Deliberately permissive, because the mode the destination ends up with must
#: come from the script and never from the umask it happened to run under. The
#: first write is the case this catches: the old script created the file at the
#: shell's umask and secured it only after every line was already in it.
_WIDE_UMASK = 0o000


def _secrets(token: str) -> SetupPhaseSecrets:
    return SetupPhaseSecrets(
        repositories=[_REPO_URL], repo_tokens={_REPO_URL: token}, clone_repos=False
    )


class _Home:
    """A HOME the scripts write into and git reads back out of.

    The same stand-in for the container that
    ``test_1393_the_renewed_credential_is_the_one_git_resolves`` uses, plus the
    two things these tests need and that one does not: a script may be expected
    to FAIL here, and the file's own uid, gid and mode are read.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        home.mkdir(parents=True, exist_ok=True)

    @property
    def _env(self) -> dict[str, str]:
        """Isolated, and unable to wait on a human (#1136)."""
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
        }

    def run(self, script: str, *, umask: int | None = None) -> int:
        prefixed = script if umask is None else f"umask {umask:03o}\n{script}"
        return subprocess.run(
            ["bash", "-c", prefixed], env=self._env, capture_output=True, text=True, check=False
        ).returncode

    def resolves(self, path: str = _REPO_PATH) -> str:
        """What git would send as the password for a push to ``path``.

        ``git credential fill`` IS the lookup a push performs, so this is the
        question a reader racing the renewal really asks.
        """
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost=github.com\npath={path}\n\n",
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("password="):
                return line.removeprefix("password=")
        return "<none>"

    def gh_token(self) -> str:
        hosts = self.home / ".config" / "gh" / "hosts.yml"
        if not hosts.exists():
            return "<none>"
        for line in hosts.read_text().splitlines():
            if "oauth_token:" in line:
                return line.split("oauth_token:", 1)[1].strip()
        return "<none>"

    def ownership_and_mode(self, relative: str) -> tuple[int, int, int] | None:
        """``(uid, gid, mode)`` of one file, or None when it is not there."""
        path = self.home / relative
        if not path.exists():
            return None
        info = path.stat()
        return (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))

    def leftovers(self) -> list[str]:
        """Staged files still lying about, which would each hold a token."""
        return sorted(
            str(path.relative_to(self.home))
            for path in self.home.rglob(".git-credentials.*")
            if path.is_file()
        ) + sorted(
            str(path.relative_to(self.home))
            for path in self.home.rglob("hosts.yml.*")
            if path.is_file()
        )


@pytest.fixture
def container(tmp_path: Path) -> _Home:
    """A container whose setup phase has run, holding a token about to expire."""
    home = _Home(tmp_path / "home")
    assert home.run(_secrets(_SETUP_TOKEN).build_setup_script(), umask=_WIDE_UMASK) == 0
    return home


def _killed_before_command(script: str, nth: int) -> str:
    """The same script, dying just before its ``nth`` command runs.

    COMMANDS RATHER THAN LINES, and a DEBUG trap rather than a truncation,
    because the script is not a list of independent lines: truncating it
    inside an `if` or a heredoc produces something bash parses differently or
    refuses outright, so the states reached would be states this script can
    never be in. Counting commands reaches every state it CAN be in - which is
    what a process killed at an arbitrary instant leaves behind - and leaves
    the script's own text untouched, cleanup traps and all.
    """
    return (
        "syn_injected=0\n"
        "trap 'if [ $((syn_injected=syn_injected+1)) -ge "
        f"{nth} ]; then exit {_INJECTED_FAILURE}; fi' DEBUG\n" + script
    )


def _every_death(home: _Home, script: str, *, umask: int = _WIDE_UMASK) -> Iterator[int]:
    """Run ``script`` once per point it can die at, yielding that point.

    Ends when the injection has run out of commands to kill and the script
    completed - so the caller's assertions cover every intermediate state
    there is, and the last run leaves the workspace fully renewed rather than
    half way through anything.
    """
    nth = 1
    while home.run(_killed_before_command(script, nth), umask=umask) == _INJECTED_FAILURE:
        yield nth
        nth += 1
    assert nth > 1, "the injection never fired, so nothing below was tested"


def test_a_renewal_killed_at_any_point_leaves_a_whole_credential_behind(
    container: _Home, tmp_path: Path
) -> None:
    """THE INVARIANT, at every point the renewal can die at.

    ENTIRELY THE OLD ONE OR ENTIRELY THE NEW ONE. Never empty, never the first
    of two entries, never a file the teardown push resolves ``<none>`` from.
    The old script failed this at the command after its truncation, which is
    the whole of the finding: the fallback the teardown path is documented to
    spend had already been destroyed by the attempt to improve it.

    The complete replacement is read out of a container that ran the script to
    the end rather than spelled out here, so this compares two things the code
    produced and asserts nothing about what either should contain.
    """
    whole_new = _Home(tmp_path / "reference")
    assert whole_new.run(_secrets(_RENEWED_TOKEN).build_setup_script(), umask=_WIDE_UMASK) == 0
    complete = {
        (container.home / ".git-credentials").read_text(),
        (whole_new.home / ".git-credentials").read_text(),
    }
    before = container.ownership_and_mode(".git-credentials")
    assert before is not None and container.resolves() == _SETUP_TOKEN

    for killed in _every_death(container, _secrets(_RENEWED_TOKEN).build_credential_script()):
        assert (container.home / ".git-credentials").read_text() in complete, (
            f"dying before command {killed} left a credential file that is neither "
            f"the whole old one nor the whole new one"
        )
        assert container.resolves() in (_SETUP_TOKEN, _RENEWED_TOKEN), (
            f"dying before command {killed} left no credential a push could resolve"
        )
        assert container.ownership_and_mode(".git-credentials") == before, (
            f"dying before command {killed} changed the file's owner or mode"
        )
        assert container.gh_token() in (_SETUP_TOKEN, _RENEWED_TOKEN), (
            f"dying before command {killed} left gh without a usable token"
        )

    # The loop ends on the run that was never killed, which is the control: the
    # assertions above would all hold of a script that did nothing at all.
    assert container.resolves() == _RENEWED_TOKEN
    assert container.gh_token() == _RENEWED_TOKEN


def test_a_credential_that_survived_a_failed_renewal_is_still_the_only_one_scoped(
    container: _Home,
) -> None:
    """Surviving is not enough: it has to survive with #953's scoping intact.

    A fallback credential that answered for every github.com path would hand
    an unlisted private repo the token this installation happens to hold - the
    defect #953 closed, re-opened by the file a failed renewal leaves behind.
    """
    script = _secrets(_RENEWED_TOKEN).build_credential_script()
    first_command = _killed_before_command(script, 1)

    assert container.run(first_command, umask=_WIDE_UMASK) == _INJECTED_FAILURE

    assert container.resolves(f"{_REPO_PATH}.git") == _SETUP_TOKEN
    assert container.resolves("someoneelse/private-repo") == "<none>"


def test_a_reader_racing_a_renewal_is_never_answered_with_a_gap(container: _Home) -> None:
    """The concurrent half, which no sequence of script prefixes can stage.

    The container's git does not stop while the credential is being replaced:
    an agent's own push, a submodule fetch and the guard's own walk all resolve
    out of this file whenever they happen to run. With the replacement written
    in place, a reader that arrived between the truncation and the last append
    was answered with nothing, and a push was refused for a credential that
    existed both before and after it looked.
    """
    answers: list[str] = []
    stop = threading.Event()

    def read_until_told_to_stop() -> None:
        while not stop.is_set():
            answers.append(container.resolves())

    reader = threading.Thread(target=read_until_told_to_stop)
    reader.start()
    try:
        for _ in range(12):
            assert container.run(_secrets(_RENEWED_TOKEN).build_credential_script()) == 0
            assert container.run(_secrets(_SETUP_TOKEN).build_credential_script()) == 0
    finally:
        stop.set()
        reader.join()

    assert answers, "the reader never got to ask, so it observed nothing"
    unexpected = sorted(set(answers) - {_SETUP_TOKEN, _RENEWED_TOKEN})
    assert not unexpected, f"a reader was answered with {unexpected} while a renewal ran"


def test_the_replacement_arrives_owned_by_the_same_user_at_0600(container: _Home) -> None:
    """The success path's half of the mode claim, under a umask that hides nothing.

    ``umask 000`` is the point: a file that is 0600 here is 0600 because the
    script made it so. Both files, because both carry the same token and both
    used to be created wide and narrowed afterwards.
    """
    before_credentials = container.ownership_and_mode(".git-credentials")
    before_hosts = container.ownership_and_mode(".config/gh/hosts.yml")

    assert container.run(_secrets(_RENEWED_TOKEN).build_credential_script(), umask=0) == 0

    assert container.resolves() == _RENEWED_TOKEN
    assert container.ownership_and_mode(".git-credentials") == (os.getuid(), os.getgid(), 0o600)
    assert container.ownership_and_mode(".config/gh/hosts.yml") == (
        os.getuid(),
        os.getgid(),
        0o600,
    )
    assert container.ownership_and_mode(".git-credentials") == before_credentials
    assert container.ownership_and_mode(".config/gh/hosts.yml") == before_hosts


def test_the_first_write_is_never_briefly_world_readable(tmp_path: Path) -> None:
    """The case with nothing to fall back to, where the mode is the whole risk.

    On the setup phase's first run the destination does not exist yet, so
    there is no old credential to protect - but there is a token, and it used
    to land at the shell's umask and be narrowed only after every line was in
    it. Under ``umask 000`` that is a world-readable token for the width of
    the script. Stopping the script at each line asserts the file is 0600 the
    first moment it exists, never a moment later.
    """
    home = _Home(tmp_path / "home")
    script = _secrets(_SETUP_TOKEN).build_setup_script()

    for killed in _every_death(home, script):
        for name in (".git-credentials", ".config/gh/hosts.yml"):
            found = home.ownership_and_mode(name)
            assert found is None or found == (os.getuid(), os.getgid(), 0o600), (
                f"{name} existed at {found} before command {killed} secured anything"
            )


def test_a_failed_renewal_leaves_no_staged_token_behind(container: _Home) -> None:
    """The cost of staging, kept to the one case nothing can cover.

    The replacement is built in a file beside the destination, so every failure
    that used to corrupt the credential now has somewhere to leave a copy of
    the token instead. Everything short of SIGKILL cleans up after itself; this
    pins that, because a plaintext token accumulating once per failed renewal
    would be a fair objection to the whole approach.
    """
    for killed in _every_death(container, _secrets(_RENEWED_TOKEN).build_credential_script()):
        assert container.leftovers() == [], (
            f"dying before command {killed} left a staged token in the container"
        )
