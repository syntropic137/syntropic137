"""S2 spike (#1735): the workspace image's real git and gh, through the broker.

Plan ``docs/plans/20261014_credential-broker.md`` D4/D9, section 4 "S2".
Every case provisions the sandbox ONLY from ``present_github`` (the module
under test), runs the image's own binary, and asserts on what the fake GitHub
received: the right REAL token, which the sandbox never held.

Run (needs Docker and the pinned workspace image)::

    uv run pytest -m integration \
        packages/syn-adapters/tests/integration/github_broker -v

``SYN_S2_WORKSPACE_IMAGE`` overrides the image; it defaults to the pinned
default provider. Every token is synthetic.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from syn_adapters.workspace_backends.service.github_presentation import (
    GitHubBroker,
    GitHubPresentation,
    present_github,
)
from syn_shared.settings.workspace_images import DEFAULT_WORKSPACE_PROVIDER, workspace_image_ref

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="needs Docker"),
]

HERE = Path(__file__).parent
HOME = "/home/agent"
GIT_AUTHORITY = "http://github-git.broker:8081"

# Synthetic. Capabilities are what the sandbox holds; real tokens only the broker.
GIT_CAP = "syncap_git_S2_0f3c9a"
GH_CAP = "syncap_gh_S2_7b21de"
REAL_GIT = {
    "o/r": "ghs_S2REAL_repo_r_111",
    "o/sub-a": "ghs_S2REAL_sub_a_222",
    "o/sub-b": "ghs_S2REAL_sub_b_333",
}
REAL_GH = "ghs_S2REAL_gh_444"
REAL_TOKENS = (*REAL_GIT.values(), REAL_GH)


class Harness:
    """The compose project, and the fake GitHub's request log."""

    def __init__(self, env: dict[str, str], out: Path, presentation: GitHubPresentation) -> None:
        self._env = env
        self._log = out / "requests.jsonl"
        self._setup = _setup_script(presentation)

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "-f", str(HERE / "compose.yaml"), *args],
            env=self._env,
            capture_output=True,
            text=True,
            check=check,
            timeout=300,
        )

    def run(
        self, command: str
    ) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str | None]]]:
        """Run ``command`` in a freshly provisioned sandbox; return what GitHub saw."""
        seen = len(self._log.read_text().splitlines())
        result = self.compose(
            "run", "--rm", "-T", "sandbox", f"{self._setup}\n{command}", check=False
        )
        requests = [json.loads(line) for line in self._log.read_text().splitlines()[seen:]]
        return result, requests


def _setup_script(presentation: GitHubPresentation) -> str:
    """Write exactly what ``present_github`` returned into the sandbox."""
    lines = ["set -e", "cd ~"]
    for file in presentation.files:
        dest = f"{HOME}/{file.path}"
        encoded = base64.b64encode(file.contents.encode()).decode()
        lines += [
            f"mkdir -p {shlex.quote(str(Path(dest).parent))}",
            f"echo {encoded} | base64 -d > {shlex.quote(dest)}",
            f"chmod {file.mode:o} {shlex.quote(dest)}",
        ]
    lines += [
        f"git config --global --add {shlex.quote(s.key)} {shlex.quote(s.value)}"
        for s in presentation.git_config
    ]
    lines += [f"export {k}={shlex.quote(v)}" for k, v in presentation.env.items()]
    lines += [
        "git config --global user.name s2 && git config --global user.email s2@example.invalid",
        "set +e",
    ]
    return "\n".join(lines)


def _certs(directory: Path) -> str:
    """A broker CA, and a leaf for github.com/api.github.com signed by it."""

    def openssl(*args: str) -> None:
        subprocess.run(["openssl", *args], cwd=directory, check=True, capture_output=True)

    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=syn-s2-broker-ca",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
    )
    openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=github.com",
        "-keyout",
        "broker.key",
        "-out",
        "broker.csr",
    )
    (directory / "san.ext").write_text("subjectAltName=DNS:github.com,DNS:api.github.com\n")
    openssl(
        "x509",
        "-req",
        "-in",
        "broker.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-days",
        "1",
        "-extfile",
        "san.ext",
        "-out",
        "broker.pem",
    )
    for name in ("broker.key", "broker.pem"):
        (directory / name).chmod(0o644)  # read by envoy inside its container
    return (directory / "ca.pem").read_text()


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Harness]:
    certs = tmp_path_factory.mktemp("certs")
    out = tmp_path_factory.mktemp("out")
    out.chmod(0o777)
    presentation = present_github(
        GitHubBroker(git_base_url=GIT_AUTHORITY, ca_pem=_certs(certs)),
        home=HOME,
        repositories=tuple(REAL_GIT),
        git_capability=SecretStr(GIT_CAP),
        gh_capability=SecretStr(GH_CAP),
        gh_repo="o/r",
    )
    env = {
        **os.environ,
        "SYN_S2_WORKSPACE_IMAGE": os.environ.get(
            "SYN_S2_WORKSPACE_IMAGE", workspace_image_ref(DEFAULT_WORKSPACE_PROVIDER)
        ),
        "SYN_S2_CERTS": str(certs),
        "SYN_S2_OUT": str(out),
        "S2_GRANTS": json.dumps(
            {
                "git_capability": GIT_CAP,
                "git_tokens": REAL_GIT,
                "gh_capability": GH_CAP,
                "gh_token": REAL_GH,
            }
        ),
    }
    h = Harness(env, out, presentation)
    h.compose("up", "-d", "--wait", "envoy", "authorizer", "fake-github")
    try:
        _wait_for_seed(out)
        yield h
    finally:
        h.compose("down", "-v", "--remove-orphans", check=False)


def _wait_for_seed(out: Path) -> None:
    import time

    deadline = time.monotonic() + 60
    while not (out / "requests.jsonl").exists():
        if time.monotonic() > deadline:
            pytest.fail("fake GitHub never finished seeding")
        time.sleep(0.5)


def _git_auth(repo: str) -> str:
    return "Basic " + base64.b64encode(f"x-access-token:{REAL_GIT[repo]}".encode()).decode()


def _for(requests: list[dict[str, str | None]], prefix: str) -> list[dict[str, str | None]]:
    return [r for r in requests if (r["path"] or "").startswith(prefix)]


def _assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


# --- git ----------------------------------------------------------------------


def test_clone_fetch_push_via_insteadof_carry_the_repos_real_token(harness: Harness) -> None:
    result, requests = harness.run(
        "git clone -q https://github.com/o/r r && cd r && git fetch -q origin"
        " && git commit -q --allow-empty -m s2 && git push -q origin HEAD:refs/heads/s2-push"
    )
    _assert_ok(result)
    ours = _for(requests, "/o/r")
    assert {r["authorization"] for r in ours} == {_git_auth("o/r")}
    assert any(r["path"].endswith("/git-receive-pack") for r in ours)  # the push arrived
    assert all(r["authority"] == "github-git.broker:8081" for r in ours)


def test_unauthenticated_git_request_gets_the_basic_challenge(harness: Harness) -> None:
    result, requests = harness.run(
        "/opt/venv/bin/python3 -I -c 'import urllib.request as u, urllib.error as e\n"
        'try: u.urlopen("http://github-git.broker:8081/o/r/info/refs?service=git-upload-pack")\n'
        'except e.HTTPError as x: print(x.code, x.headers.get("www-authenticate"))\''
    )
    assert result.stdout.split()[:2] == ["401", "Basic"], result.stdout + result.stderr
    assert requests == []  # the challenge is the broker's; GitHub never saw it


def test_submodules_with_and_without_dot_git_get_their_own_tokens(harness: Harness) -> None:
    result, requests = harness.run(
        "git clone -q https://github.com/o/r r && cd r && git submodule update -q --init"
    )
    _assert_ok(result)
    sub_a, sub_b = _for(requests, "/o/sub-a"), _for(requests, "/o/sub-b.git")
    assert sub_a and {r["authorization"] for r in sub_a} == {_git_auth("o/sub-a")}
    assert sub_b and {r["authorization"] for r in sub_b} == {_git_auth("o/sub-b")}


def test_an_ungranted_repository_is_offered_nothing(harness: Harness) -> None:
    result, requests = harness.run("git ls-remote https://github.com/o/unlisted")
    assert result.returncode != 0
    assert _for(requests, "/o/unlisted") == []


# --- gh -----------------------------------------------------------------------

GH_CASES = {
    "pr_create_no_git_tree": "cd /tmp && gh pr create --head s2 --base main --title t --body b",
    "repo_less_issue_list": "cd /tmp && unset GH_REPO && gh issue list -R o/r",
    "explicit_github_url": "cd /tmp && gh pr view https://github.com/o/r/pull/1",
    "api_graphql": "gh api graphql -f query='{viewer{login}}'",
    "api_rest": "gh api repos/o/r",
}


@pytest.mark.parametrize("command", GH_CASES.values(), ids=GH_CASES.keys())
def test_gh_reaches_github_with_the_real_gh_token(harness: Harness, command: str) -> None:
    result, requests = harness.run(command)
    api = [r for r in requests if (r["authority"] or "").startswith("api.github.com")]
    assert api, f"no request reached GitHub's API\n{result.stdout}{result.stderr}"
    assert {r["authorization"] for r in api} == {f"token {REAL_GH}"}


# --- the sandbox holds capabilities only --------------------------------------


def test_sandbox_files_and_env_hold_capabilities_never_real_tokens(harness: Harness) -> None:
    patterns = " ".join(f"-e {t}" for t in REAL_TOKENS)
    result, _ = harness.run(
        "git clone -q https://github.com/o/r r && (cd r && git submodule update -q --init);"
        " gh api repos/o/r >/dev/null;"
        f" grep -rlF {patterns} {HOME} /tmp 2>/dev/null; env | grep -F {patterns};"
        f" echo CAPS; grep -rlF -e {GIT_CAP} -e {GH_CAP} {HOME}"
    )
    leaked, _, caps = result.stdout.partition("CAPS")
    assert leaked.strip() == ""
    assert ".git-credentials" in caps and "hosts.yml" in caps
