"""What git and gh are handed when GitHub credentials are brokered (#1735).

The one owner of git/gh presentation under the credential broker (plan
``docs/plans/20261014_credential-broker.md`` D4, D9; settled by spike S2).
git and gh speak GitHub's protocol, not a model harness's, so this stays in
syntropic137 rather than agentic-workspace (H10's default).

The sandbox receives capabilities only: opaque broker bearers that the broker
exchanges for the real installation token on the way out. Nothing here ever
sees a real token, which is the property the spike's exit test checks on the
files this module writes.

How each tool reaches the broker, and why (S2):

- **git** goes to a dedicated plaintext git authority through ``insteadOf``.
  git only offers a credential after a ``401`` carrying ``WWW-Authenticate:
  Basic``, and the broker answers a capability-less request with exactly that.
  ``useHttpPath`` keeps the store scoped per repository, so a submodule the
  workspace was not granted is offered nothing.
- **gh** stays on ``github.com``. gh's enterprise-host mode was the plan's
  primary and is rejected: an explicit ``https://github.com/...`` argument
  ignores ``GH_HOST`` and goes straight to ``api.github.com`` with no
  credential, and gh drops the port when it looks up ``hosts.yml``. Instead,
  ``github.com`` and ``api.github.com`` resolve to the broker, which terminates
  TLS with a certificate from the broker CA, and gh is told to trust that CA.
  So ``GH_REPO`` keeps today's ``owner/repo`` form and needs no host.
- The CA reaches Go through ``SSL_CERT_DIR``, which ADDS directories to the
  system roots. ``SSL_CERT_FILE`` would replace the system bundle instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import SecretStr

#: Every spelling of a github.com remote a workspace meets: the canonical
#: clone URL and the two SSH forms submodules are often declared with. Each is
#: rewritten straight to the broker, because git applies one insteadOf and does
#: not chain an SSH rewrite through the HTTPS one (D9).
GITHUB_REMOTE_PREFIXES: Final[tuple[str, ...]] = (
    "https://github.com/",
    "git@github.com:",
    "ssh://git@github.com/",
)

#: Where the broker CA lands, relative to the sandbox's HOME.
BROKER_CA_DIR: Final[str] = ".config/syn/broker-ca"

#: The system's own certificate directory, kept first in ``SSL_CERT_DIR`` so
#: that adding the broker CA never removes a public root.
SYSTEM_CERT_DIR: Final[str] = "/etc/ssl/certs"


@dataclass(frozen=True, slots=True)
class GitHubBroker:
    """Where the sandbox reaches GitHub, as the host's grant set records it.

    ``git_base_url`` is the git authority, e.g. ``http://github-git.broker:8081``.
    ``ca_pem`` is the broker CA's certificate: public, not a secret.
    """

    git_base_url: str
    ca_pem: str

    def __post_init__(self) -> None:
        parts = urlsplit(self.git_base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            msg = f"git_base_url must be an http(s) authority, got {self.git_base_url!r}"
            raise ValueError(msg)
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            msg = f"git_base_url must be a bare authority with no path, got {self.git_base_url!r}"
            raise ValueError(msg)
        if "BEGIN CERTIFICATE" not in self.ca_pem:
            msg = "ca_pem must be a PEM certificate"
            raise ValueError(msg)

    @property
    def git_prefix(self) -> str:
        """The git authority with exactly one trailing slash, as insteadOf wants it."""
        return self.git_base_url.rstrip("/") + "/"


@dataclass(frozen=True, slots=True)
class GitConfigSetting:
    """One ``git config --global --add <key> <value>``. insteadOf is multi-valued."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class PresentedFile:
    """A file written into the sandbox, at a path relative to its HOME."""

    path: str
    contents: str
    mode: int = 0o600


@dataclass(frozen=True, slots=True)
class GitHubPresentation:
    """Everything git and gh in the sandbox are given. Capabilities only."""

    git_config: tuple[GitConfigSetting, ...]
    files: tuple[PresentedFile, ...]
    env: Mapping[str, str]


def provisioned_remote_settings(broker: GitHubBroker) -> tuple[GitConfigSetting, ...]:
    """The git settings that route every github.com remote through the broker.

    The same tuple a hardened, HOME-less git command needs restored (D9), so
    the setup script and that command cannot disagree about where GitHub is.
    """
    prefix = broker.git_prefix
    return (
        GitConfigSetting(f"credential.{prefix}.useHttpPath", "true"),
        *(GitConfigSetting(f"url.{prefix}.insteadOf", remote) for remote in GITHUB_REMOTE_PREFIXES),
    )


def present_github(
    broker: GitHubBroker,
    *,
    home: str,
    repositories: Sequence[str],
    git_capability: SecretStr | None,
    gh_capability: SecretStr | None,
    gh_repo: str | None,
) -> GitHubPresentation:
    """Present one workspace's GitHub capabilities to git and gh.

    ``repositories`` are ``owner/repo`` names the git capability is granted
    for; each is stored with and without ``.git``, because credential matching
    is exact and submodule URLs often carry the suffix. ``gh_repo`` is the
    ``owner/repo`` gh defaults to when there is no git tree to infer it from.
    """
    git_config: list[GitConfigSetting] = []
    files: list[PresentedFile] = [
        PresentedFile(f"{BROKER_CA_DIR}/broker-ca.pem", broker.ca_pem, 0o644)
    ]
    env: dict[str, str] = {"SSL_CERT_DIR": f"{SYSTEM_CERT_DIR}:{home.rstrip('/')}/{BROKER_CA_DIR}"}

    if git_capability is not None and repositories:
        git_config.append(GitConfigSetting("credential.helper", "store"))
        git_config.extend(provisioned_remote_settings(broker))
        cap = git_capability.get_secret_value()
        files.append(
            PresentedFile(
                ".git-credentials",
                "".join(
                    f"{broker.git_prefix.replace('://', f'://x-access-token:{cap}@', 1)}{path}\n"
                    for name in repositories
                    for path in (name, f"{name}.git")
                ),
            )
        )

    if gh_capability is not None:
        files.append(
            PresentedFile(
                ".config/gh/hosts.yml",
                "github.com:\n"
                f"    oauth_token: {gh_capability.get_secret_value()}\n"
                "    user: syn-bot\n"
                "    git_protocol: https\n",
            )
        )
        if gh_repo is not None:
            env["GH_REPO"] = gh_repo

    return GitHubPresentation(
        git_config=tuple(git_config),
        files=tuple(files),
        env=MappingProxyType(env),
    )
