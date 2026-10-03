"""One credential store, one lookup, and what a renewal has to change in it (#1393).

THE TWO PUSHES WERE NEVER USING DIFFERENT CREDENTIALS. A phase's ordinary
push and the unpushed-work guard's quarantine push both run ``git push origin``
inside the same container as the same user, so both resolve the same entry from
the same ``~/.git-credentials`` that the setup phase wrote. They diverge in
time: the installation token lives one hour, and the quarantine push happens at
teardown. So the fix re-mints the credential before that push - and the only
thing that makes a re-mint a fix rather than a no-op is whether the NEXT
LOOKUP returns the new token.

That is the question these tests ask, and they ask it of ``git credential
fill``, which is the resolution git itself performs on every push. Nothing here
asserts on the text of a script: a renewal script containing the right token
and leaving the stale one winning the lookup would pass a substring test and
lose the work anyway. That is exactly the shape of the bug being closed.

The real scripts run under real bash against a real git with a tmpdir HOME.
Nothing reaches the network: ``clone_repos=False`` means the setup script
configures credentials and clones nothing.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets

pytestmark = pytest.mark.unit

_REPO_URL = "https://github.com/org/repo-a"
_REPO_PATH = "org/repo-a"


def _secrets(token: str) -> SetupPhaseSecrets:
    return SetupPhaseSecrets(
        repositories=[_REPO_URL],
        repo_tokens={_REPO_URL: token},
        clone_repos=False,
    )


class _Container:
    """A HOME that scripts write into and git reads back out of.

    Stands in for the workspace container, which is the only thing both
    scripts have in common in production: the setup phase writes the
    credential into it at provisioning, the renewal rewrites it an hour later,
    and every push in between resolves out of it.
    """

    def __init__(self, home: Path) -> None:
        self._home = home
        home.mkdir(parents=True, exist_ok=True)

    @property
    def _env(self) -> dict[str, str]:
        """Isolated, and unable to wait on a human.

        `GIT_TERMINAL_PROMPT=0` plus a failing askpass are load-bearing, not
        belt and braces: a lookup no helper matches otherwise falls through to
        PROMPTING, which hung a full unit run inside an agent workspace until
        the phase interrupted it (#1136).
        """
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self._home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
        }

    def run(self, script: str) -> None:
        proc = subprocess.run(
            ["bash", "-c", script], env=self._env, capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, proc.stderr

    def resolves(self, path: str = _REPO_PATH) -> str:
        """What git would send as the password for a push to ``path``.

        `git credential fill` IS the step a push performs, so an assertion on
        its answer is an assertion about the push - and about BOTH pushes,
        which issue the identical `git push origin` and so ask this identical
        question.
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

    def stored_credentials(self) -> str:
        """The store's whole contents, for the one claim `fill` cannot make.

        `fill` answers one lookup; "no entry anywhere still carries the
        expired token" is a claim about the file.
        """
        return (self._home / ".git-credentials").read_text()

    def gh_token(self) -> str:
        hosts = self._home / ".config" / "gh" / "hosts.yml"
        if not hosts.exists():
            return "<none>"
        for line in hosts.read_text().splitlines():
            if "oauth_token:" in line:
                return line.split("oauth_token:", 1)[1].strip()
        return "<none>"


@pytest.fixture
def container(tmp_path: Path) -> _Container:
    """A container whose setup phase has run, holding a token about to expire."""
    workspace = _Container(tmp_path / "home")
    workspace.run(_secrets("tok-from-setup").build_setup_script())
    return workspace


def test_the_setup_phase_credential_is_what_a_push_resolves(container: _Container) -> None:
    """The control. Without it every assertion below could pass vacuously.

    This is also the statement the issue's evidence rests on: the phase's
    ordinary push worked, minutes before the quarantine push did not, using
    this entry.
    """
    assert container.resolves() == "tok-from-setup"


def test_a_renewal_becomes_the_credential_the_next_push_resolves(
    container: _Container,
) -> None:
    """THE FIX, as the only question worth asking about it.

    git-credential-store answers with the FIRST entry matching a request. A
    renewal that appended a fresh token behind the stale one would change the
    file, satisfy any test that looked for the new token in it, and leave every
    push still being refused - which is #1393 with an extra line of evidence.
    """
    container.run(_secrets("tok-renewed").build_credential_script())

    assert container.resolves() == "tok-renewed"


def test_a_renewal_leaves_no_way_to_resolve_the_expired_token(
    container: _Container,
) -> None:
    """Not merely "the new one wins" - the old one is gone.

    A stale entry that lost this lookup could still win another: git asks
    again for every remote, and the guard's walk covers one repository per
    lookup. An expired token nobody can reach cannot refuse anything.
    """
    container.run(_secrets("tok-renewed").build_credential_script())

    assert "tok-from-setup" not in container.stored_credentials()


def test_a_renewal_keeps_the_scoping_the_setup_phase_established(
    container: _Container,
) -> None:
    """A renewal must re-establish the credential's SHAPE, not just its token.

    Both properties were won in #953 and both are invisible until something
    breaks: a submodule URL carrying `.git` has to authenticate, and a repo
    this installation was never given has to get nothing rather than the first
    token in the file. A renewal that re-derived the credential its own way
    could drop either, and the loss would surface as an authentication failure
    at the one moment work was riding on it.
    """
    container.run(_secrets("tok-renewed").build_credential_script())

    assert container.resolves(f"{_REPO_PATH}.git") == "tok-renewed"
    assert container.resolves("someoneelse/private-repo") == "<none>"


def test_a_renewal_also_refreshes_the_token_gh_reads(container: _Container) -> None:
    """`gh pr create` reads hosts.yml, and its token expires on the same clock.

    Free here only because the renewal reuses the setup phase's own credential
    lines rather than writing a second spelling of them. Asserted so that a
    later "simplification" down to just ~/.git-credentials has to notice it is
    taking something away.
    """
    assert container.gh_token() == "tok-from-setup"

    container.run(_secrets("tok-renewed").build_credential_script())

    assert container.gh_token() == "tok-renewed"
