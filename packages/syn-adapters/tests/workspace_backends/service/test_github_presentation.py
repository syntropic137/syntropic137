"""github_presentation, read back by the consumer that matters: real git (#1735 S2).

Each test writes the presentation into a scratch HOME exactly as a sandbox
would hold it and asks git itself what it will do with it, so a setting that is
spelled wrong, or a credential line git will not match, fails here rather than
in the Docker harness (tests/integration/github_broker).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from syn_adapters.workspace_backends.service.github_presentation import (
    GitHubBroker,
    GitHubPresentation,
    present_github,
    provisioned_remote_settings,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(shutil.which("git") is None, reason="needs git"),
]

AUTHORITY = "http://github-git.broker:8081"
CA = "-----BEGIN CERTIFICATE-----\nMIIBsynthetic\n-----END CERTIFICATE-----\n"
GIT_CAP = "syncap_git_unit_9e1"
GH_CAP = "syncap_gh_unit_4c2"


def _present(
    home: Path,
    *,
    git_capability: SecretStr | None = SecretStr(GIT_CAP),
    gh_capability: SecretStr | None = SecretStr(GH_CAP),
) -> GitHubPresentation:
    return present_github(
        GitHubBroker(git_base_url=AUTHORITY, ca_pem=CA),
        home=str(home),
        repositories=("o/r", "o/sub"),
        git_capability=git_capability,
        gh_capability=gh_capability,
        gh_repo="o/r",
    )


def _install(home: Path, presentation: GitHubPresentation) -> dict[str, str]:
    for file in presentation.files:
        dest = home / file.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(file.contents)
    env = {"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}
    for setting in presentation.git_config:
        subprocess.run(
            ["git", "config", "--global", "--add", setting.key, setting.value], env=env, check=True
        )
    return env


def _git(env: dict[str, str], *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], env=env, input=stdin, capture_output=True, text=True, check=True
    ).stdout


def _fill(env: dict[str, str], path: str) -> str:
    """The password git would send to the broker for ``path``, or "" for none."""
    out = subprocess.run(
        ["git", "credential", "fill"],
        env={**env, "GIT_TERMINAL_PROMPT": "0"},
        input=f"protocol=http\nhost=github-git.broker:8081\npath={path}\n\n",
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return next(
        (
            line.removeprefix("password=")
            for line in out.splitlines()
            if line.startswith("password=")
        ),
        "",
    )


@pytest.mark.parametrize(
    "remote",
    ["https://github.com/o/r", "git@github.com:o/r", "ssh://git@github.com/o/r"],
)
def test_every_github_remote_spelling_resolves_to_the_broker(tmp_path: Path, remote: str) -> None:
    env = _install(tmp_path, _present(tmp_path))
    assert _git(env, "ls-remote", "--get-url", remote).strip() == f"{AUTHORITY}/o/r"


@pytest.mark.parametrize("path", ["o/r", "o/r.git", "o/sub", "o/sub.git"])
def test_git_offers_the_capability_for_granted_repos_in_both_spellings(
    tmp_path: Path, path: str
) -> None:
    env = _install(tmp_path, _present(tmp_path))
    assert _fill(env, path) == GIT_CAP


def test_git_offers_nothing_for_a_repo_outside_the_grant(tmp_path: Path) -> None:
    env = _install(tmp_path, _present(tmp_path))
    assert _fill(env, "o/unlisted") == ""


def test_gh_is_given_the_capability_on_github_com_and_no_host_override(tmp_path: Path) -> None:
    presentation = _present(tmp_path)
    hosts = next(f for f in presentation.files if f.path == ".config/gh/hosts.yml")
    assert hosts.contents.startswith("github.com:\n")
    assert f"oauth_token: {GH_CAP}\n" in hosts.contents
    # gh stays on github.com, so an explicit https://github.com/... argument
    # reaches the broker too: GH_HOST would be ignored by it (S2).
    assert dict(presentation.env) == {
        "SSL_CERT_DIR": f"/etc/ssl/certs:{tmp_path}/.config/syn/broker-ca",
        "GH_REPO": "o/r",
    }


def test_the_broker_ca_lands_in_the_directory_ssl_cert_dir_names(tmp_path: Path) -> None:
    presentation = _present(tmp_path)
    _install(tmp_path, presentation)
    ca_dir = presentation.env["SSL_CERT_DIR"].split(":")[1]
    assert [p.read_text() for p in (tmp_path / ca_dir).iterdir()] == [CA]


def test_without_capabilities_git_and_gh_are_given_nothing(tmp_path: Path) -> None:
    presentation = _present(tmp_path, git_capability=None, gh_capability=None)
    assert presentation.git_config == ()
    assert [f.path for f in presentation.files] == [".config/syn/broker-ca/broker-ca.pem"]
    assert "GH_REPO" not in presentation.env


def test_hardened_git_settings_are_the_ones_the_setup_writes(tmp_path: Path) -> None:
    presentation = _present(tmp_path)
    settings = provisioned_remote_settings(GitHubBroker(git_base_url=AUTHORITY, ca_pem=CA))
    assert set(settings) <= set(presentation.git_config)
    assert len(settings) == 4


@pytest.mark.parametrize(
    "url", ["github-git.broker:8081", "ftp://broker", "http://broker/prefix", "http://broker?x=1"]
)
def test_a_git_authority_that_is_not_a_bare_http_authority_is_refused(url: str) -> None:
    with pytest.raises(ValueError, match="git_base_url"):
        GitHubBroker(git_base_url=url, ca_pem=CA)


def test_a_ca_that_is_not_pem_is_refused() -> None:
    with pytest.raises(ValueError, match="ca_pem"):
        GitHubBroker(git_base_url=AUTHORITY, ca_pem="not a certificate")
