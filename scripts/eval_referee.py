#!/usr/bin/env python3
"""The deterministic referee for IMPLEMENTER eval runs (#2108 S4, plan section 10 fix 3).

No agent carries the verdict. The scorer's exit code is the verdict, and it is
computed in a throwaway container from the pinned workspace image, with the
network cut before the agent's code runs:

    uv run python scripts/eval_referee.py --case ID --patch FILE
    uv run python scripts/eval_referee.py --case ID --eval EVAL_ID --execution EXEC [...]

Per container, in this order:

1. The repository arrives as a git bundle holding the pin and the fix, and each
   submodule as its own bundle holding every commit the pin and the fix
   reference, cloned at the submodule's path, because the scorer checks a
   submodule out from a local clone at its path. Nothing is cloned from GitHub.
2. The scorer is ``scripts/implementer_scorer.py`` at a recorded commit of this
   repository (``git show <commit>:...``, never the working tree), and that
   commit is part of the recorded ``scorer_version``.
3. Network on: ``implementer_scorer.py prepare`` collects the intended hidden
   tests at the fix and builds the pin's environment. No agent code runs.
4. ``docker network disconnect``, then a check that the container has no
   interface but loopback. If either fails, the patch is not scored: ERROR.
5. Network off: ``implementer_scorer.py score --prepared`` applies the patch and
   runs the hidden tests. It never syncs. Its last line, ``RESULT: <outcome>``,
   must agree with its exit code, or the run is ERROR.

CONTROLS. Before any agent patch of a case is scored, the case's reference fix
must PASS and the empty patch must FAIL through this same path, in the same
invocation. If either does not, no agent patch of that case is scored.

RECORDING. With ``--execution``, the patch is the implement phase's
``implement.patch`` artifact, fetched through the API, and the verdict is
recorded on the eval as ``EvalRunScored`` (scorer ``eval_implementer.py``).
With ``--patch``, nothing is recorded.

Docker runs on the host this is run on; the agent's code runs only inside the
container, which holds no credential and no Docker socket.

Exit status: 0 every agent patch scored PASS, 1 any FAIL or a control failed,
2 any ERROR or a refusal before scoring.
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from eval_implementer import DEFAULT_SUITE, ImplementerCase, fix_patch, load_suite
from eval_suite import ROOT, DefinitionError, _basic_auth, _detail
from implementer_scorer import EXIT_CODES, PATCH_ERRORS, Pin, TestRun, read_patch
from pydantic import BaseModel, ConfigDict, ValidationError

from syn_shared.settings.dev_tooling import get_dev_api_url
from syn_shared.settings.workspace_images import WorkspaceImageProvider, workspace_image_ref

SCORER = "eval_implementer.py"
SCORER_PATH = "scripts/implementer_scorer.py"
PREPARE_TIMEOUT_SECONDS = 3600
SCORE_TIMEOUT_SECONDS = 900
STEP_TIMEOUT_SECONDS = 300
_IN = "/referee/in"
_WORK = "/tmp/referee"
_REF_NAMESPACE = "refs/syn-eval-referee"


class Docker(Protocol):
    """How the referee calls docker. A test passes a double; production uses the CLI."""

    def __call__(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]: ...


def docker_cli(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            ["docker", *args], 124, stdout="", stderr=f"timed out after {exc.timeout}s"
        )


class _RefereeError(Exception):
    """The referee itself could not do its job: ERROR, never the agent's fault."""


# ---------------------------------------------------------------------------
# Bundles: the repository and each submodule, holding only what scoring needs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Submodule:
    path: str
    commits: tuple[str, ...]
    """Every gitlink the pin and the fix record at `path`."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def submodules_of(repo: Path, commits: tuple[str, ...]) -> tuple[Submodule, ...]:
    """The submodules any of `commits` records, with each one's gitlinks across them."""
    found: dict[str, list[str]] = {}
    for commit in commits:
        listed = _git(repo, "config", "--blob", f"{commit}:.gitmodules", "--get-regexp", r"\.path$")
        for line in listed.stdout.splitlines():
            _, path = line.split(maxsplit=1)
            parts = _git(repo, "ls-tree", commit, path).stdout.split()
            if len(parts) >= 3 and parts[1] == "commit" and parts[2] not in found.get(path, []):
                found.setdefault(path, []).append(parts[2])
    return tuple(Submodule(path=p, commits=tuple(c)) for p, c in sorted(found.items()))


def _bundle(repo: Path, commits: tuple[str, ...], out: Path) -> None:
    """Write a bundle of `commits` and their history. Temporary refs, always removed.

    `git bundle` takes refs, not bare SHAs, so each commit gets a ref under a
    namespace no checkout uses, removed in `finally` whatever happens.
    """
    nonce = secrets.token_hex(6)
    refs = [f"{_REF_NAMESPACE}/{nonce}/{i}" for i in range(len(commits))]
    try:
        for ref, commit in zip(refs, commits, strict=True):
            made = _git(repo, "update-ref", ref, commit)
            if made.returncode != 0:
                raise _RefereeError(f"{commit} is not in {repo}: {made.stderr.strip()}")
        bundled = _git(repo, "bundle", "create", str(out), *refs)
        if bundled.returncode != 0:
            raise _RefereeError(f"git bundle in {repo}: {bundled.stderr.strip()}")
    finally:
        for ref in refs:
            _git(repo, "update-ref", "-d", ref)


def write_inputs(pin: Pin, patch: str, scorer_commit: str, repo: Path, into: Path) -> list[str]:
    """Write everything the container reads into `into`. Returns the submodule paths.

    The subject comes from `repo`; the scorer always from this repository, at `scorer_commit`.
    """
    _bundle(repo, (pin.commit, pin.fix_commit), into / "repo.bundle")
    paths: list[str] = []
    for i, sub in enumerate(submodules_of(repo, (pin.commit, pin.fix_commit))):
        clone = repo / sub.path
        if not (clone / ".git").exists():
            raise _RefereeError(f"submodule {sub.path} has no local clone in {repo}")
        _bundle(clone, sub.commits, into / f"submodule-{i}.bundle")
        paths.append(sub.path)
    scorer = _git(ROOT, "show", f"{scorer_commit}:{SCORER_PATH}")
    if scorer.returncode != 0:
        raise _RefereeError(f"{SCORER_PATH} at {scorer_commit}: {scorer.stderr.strip()}")
    (into / "implementer_scorer.py").write_text(scorer.stdout)
    (into / "pin.json").write_text(pin.to_json())
    (into / "implement.patch").write_text(patch, encoding="utf-8", errors=PATCH_ERRORS)
    # The workspace image runs as an unprivileged user that owns none of this.
    into.chmod(0o755)
    for path in into.iterdir():
        path.chmod(0o644)
    return paths


# ---------------------------------------------------------------------------
# The container
# ---------------------------------------------------------------------------


def referee_score(
    pin: Pin,
    patch: str,
    *,
    repo: Path,
    scorer_commit: str,
    image: str,
    docker: Docker = docker_cli,
) -> TestRun:
    """Score one patch in a fresh container. Every failure of the referee is ERROR."""
    name = f"syn-eval-referee-{secrets.token_hex(6)}"
    with tempfile.TemporaryDirectory(prefix="eval-referee-") as tmp:
        inputs = Path(tmp)
        try:
            submodules = write_inputs(pin, patch, scorer_commit, repo, inputs)
        except _RefereeError as exc:
            return TestRun(outcome="ERROR", detail=f"referee inputs: {exc}")
        try:
            run = _contained(docker, name, inputs, submodules, image)
        finally:
            left = [
                why
                for why in (
                    _remove(docker, ["rm", "--force", name]),
                    _remove(docker, ["network", "rm", name]),
                )
                if why
            ]
        if left:
            listed = "\n".join(left)
            return TestRun(
                outcome="ERROR",
                detail=f"cleanup incomplete, verdict {run.outcome} withheld:\n{listed}\n{run.detail}",
            )
        return run


_GONE = ("no such container", "not found")
"""How docker says a removal had nothing to remove: the outcome cleanup wants."""


def _remove(docker: Docker, args: list[str], attempts: int = 3) -> str | None:
    """Remove a container or network, retried. None once it is gone, else why it is not."""
    why = ""
    for _ in range(attempts):
        ran = docker(args, STEP_TIMEOUT_SECONDS)
        if ran.returncode == 0 or any(gone in ran.stderr.lower() for gone in _GONE):
            return None
        why = _tail(ran)
    return f"docker {' '.join(args)} failed {attempts} times: {why}"


def _contained(
    docker: Docker, name: str, inputs: Path, submodules: list[str], image: str
) -> TestRun:
    """Everything between creating the container's network and the scorer's verdict."""
    try:
        _step(docker, ["network", "create", name], "create the container's network")
        _step(
            docker,
            [
                "run", "--detach", "--name", name, "--network", name,
                "--volume", f"{inputs}:{_IN}:ro",
                "--entrypoint", "sleep", image, "infinity",
            ],
            "start the container",
        )  # fmt: skip
        for argv, what in _setup(submodules):
            _step(docker, ["exec", name, *argv], what, timeout=STEP_TIMEOUT_SECONDS)
        prepared = docker(
            ["exec", name, *_scorer("prepare", "--pin", f"{_IN}/pin.json",
                                    "--repo", f"{_WORK}/repo", "--out", f"{_WORK}/prepared")],
            PREPARE_TIMEOUT_SECONDS,
        )  # fmt: skip
        if prepared.returncode != 0:
            return TestRun(outcome="ERROR", detail=f"prepare: {_tail(prepared)}")
        _step(docker, ["network", "disconnect", name, name], "cut the network")
        _assert_offline(docker, name)
        scored = docker(
            ["exec", name, *_scorer("score", "--prepared", f"{_WORK}/prepared",
                                    "--patch", f"{_IN}/implement.patch")],
            SCORE_TIMEOUT_SECONDS,
        )  # fmt: skip
        return verdict_of(scored)
    except _RefereeError as exc:
        return TestRun(outcome="ERROR", detail=str(exc))


def _scorer(*args: str) -> list[str]:
    return ["python3", f"{_IN}/implementer_scorer.py", *args]


def _setup(submodules: list[str]) -> list[tuple[list[str], str]]:
    """Unpack the repository and each submodule from their bundles. No remote is ever named."""
    targets = [("repo.bundle", f"{_WORK}/repo", "the repository")]
    targets += [
        (f"submodule-{i}.bundle", f"{_WORK}/repo/{path}", f"submodule {path}")
        for i, path in enumerate(submodules)
    ]
    steps: list[tuple[list[str], str]] = []
    for bundle, target, what in targets:
        steps.append((["git", "init", "--quiet", target], f"init {what}"))
        steps.append((unbundle(f"{_IN}/{bundle}", target), f"unbundle {what}"))
    return steps


def unbundle(bundle: str, target: str) -> list[str]:
    """Fetch every ref a bundle holds. `git clone` would map only refs/heads and drop the rest."""
    refs = f"+{_REF_NAMESPACE}/*:{_REF_NAMESPACE}/*"
    return ["git", "-C", target, "fetch", "--quiet", bundle, refs]


#: Lists the container's interfaces through the stdlib, so it names no Linux-only path.
INTERFACE_PROBE = "import socket; print(' '.join(sorted(n for _, n in socket.if_nameindex())))"


def _assert_offline(docker: Docker, name: str) -> None:
    """The container must have no interface but loopback before any agent code runs."""
    listed = docker(["exec", name, "python3", "-c", INTERFACE_PROBE], STEP_TIMEOUT_SECONDS)
    interfaces = listed.stdout.split()
    if listed.returncode != 0 or interfaces != ["lo"]:
        raise _RefereeError(
            f"the network is not cut: interfaces {interfaces or '?'} ({_tail(listed)})"
        )


def _step(docker: Docker, args: list[str], what: str, timeout: int = STEP_TIMEOUT_SECONDS) -> None:
    ran = docker(args, timeout)
    if ran.returncode != 0:
        raise _RefereeError(f"{what}: exit {ran.returncode}: {_tail(ran)}")


def _tail(ran: subprocess.CompletedProcess[str]) -> str:
    return "\n".join((ran.stderr + ran.stdout).strip().splitlines()[-15:])


def verdict_of(scored: subprocess.CompletedProcess[str]) -> TestRun:
    """The scorer's verdict, only when its last line and its exit code agree.

    A crash exits 1 with a traceback and no RESULT line: that is the referee
    failing, not the patch, so it must never read as FAIL.
    """
    lines = scored.stdout.strip().splitlines()
    said = (
        lines[-1].removeprefix("RESULT: ") if lines and lines[-1].startswith("RESULT: ") else None
    )
    detail = "\n".join(lines[:-1]) if said is not None else _tail(scored)
    if said not in EXIT_CODES:
        return TestRun(
            outcome="ERROR",
            detail=f"the scorer gave no verdict (exit {scored.returncode}):\n{detail}",
        )
    outcome = next(o for o in EXIT_CODES if o == said)
    if EXIT_CODES[outcome] != scored.returncode:
        return TestRun(
            outcome="ERROR",
            detail=f"the scorer said {outcome} but exited {scored.returncode}:\n{detail}",
        )
    return TestRun(outcome=outcome, detail=detail)


# ---------------------------------------------------------------------------
# Controls, then agent patches
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scored:
    label: str
    run: TestRun


def score_case(
    case: ImplementerCase,
    patches: list[tuple[str, str]],
    *,
    repo: Path,
    scorer_commit: str,
    image: str,
    docker: Docker = docker_cli,
) -> tuple[list[Scored], list[Scored]]:
    """(controls, agent patches). No agent patch is scored unless both controls held."""
    pin = case.pin()

    def run(patch: str) -> TestRun:
        return referee_score(
            pin, patch, repo=repo, scorer_commit=scorer_commit, image=image, docker=docker
        )

    controls = [
        Scored("reference fix (must PASS)", run(fix_patch(case, repo))),
        Scored("empty patch (must FAIL)", run("")),
    ]
    if [c.run.outcome for c in controls] != ["PASS", "FAIL"]:
        return controls, []
    return controls, [Scored(label, run(patch)) for label, patch in patches]


def scorer_commit_of(repo: Path) -> str:
    """This repository's HEAD, refused when the scorer differs from it in the working tree."""
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if _git(repo, "diff", "--quiet", "HEAD", "--", SCORER_PATH).returncode != 0:
        raise _RefereeError(
            f"{SCORER_PATH} has uncommitted changes: the referee runs it at a recorded commit,"
            " so commit it first"
        )
    return head


def scorer_version(suite_version: int, scorer_commit: str) -> str:
    """Tag-safe: the suite version and the scorer's commit."""
    return f"{suite_version}-{scorer_commit[:12]}"


# ---------------------------------------------------------------------------
# API: the implement run's patch in, the verdict out
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Artifact(_Frozen):
    id: str
    phase_id: str | None = None
    title: str | None = None


class _ArtifactList(_Frozen):
    artifacts: list[_Artifact]
    total: int


_PAGE_SIZE = 200
"""The API's largest page. Any page size is correct: every page is read."""


def _implement_artifacts(client: httpx.Client, execution_id: str) -> list[_Artifact]:
    """Every artifact of the run's implement phase, across every page of the listing."""
    found: list[_Artifact] = []
    page = 1
    while True:
        listed = client.get(
            "/artifacts",
            params={
                "execution_id": execution_id,
                "phase_id": "implement",
                "page": page,
                "page_size": _PAGE_SIZE,
            },
        )
        if listed.is_error:
            raise _RefereeError(
                f"listing {execution_id}'s artifacts: {listed.status_code} {_detail(listed)}"
            )
        try:
            listing = _ArtifactList.model_validate(listed.json())
        except (ValueError, ValidationError) as exc:
            raise _RefereeError(f"listing {execution_id}'s artifacts: {exc}") from exc
        found += listing.artifacts
        if len(found) >= listing.total:
            return found
        if not listing.artifacts:
            raise _RefereeError(
                f"listing {execution_id}'s artifacts: page {page} is empty with"
                f" {len(found)} of {listing.total} read"
            )
        page += 1


def fetch_patch(client: httpx.Client, execution_id: str) -> str:
    """The implement phase's `implement.patch`, byte for byte. Refuses rather than guesses."""
    artifacts = _implement_artifacts(client, execution_id)
    patches = [a for a in artifacts if (a.title or "").endswith("implement.patch")]
    if len(patches) != 1:
        raise _RefereeError(
            f"{execution_id}'s implement phase has {len(patches)} implement.patch artifact(s)"
            f" among {[a.title for a in artifacts]}: not scored"
        )
    raw = client.get(f"/artifacts/{patches[0].id}/raw")
    if raw.is_error:
        raise _RefereeError(f"artifact {patches[0].id}: {raw.status_code} {_detail(raw)}")
    return raw.content.decode("utf-8", errors=PATCH_ERRORS)


def record(
    client: httpx.Client, eval_id: str, execution_id: str, run: TestRun, version: str
) -> None:
    response = client.post(
        f"/evals/{eval_id}/runs/{execution_id}/score",
        json={
            "verdict": run.outcome,
            "score": None if run.outcome == "ERROR" else float(run.outcome == "PASS"),
            "evidence": run.detail[-4000:],
            "scorer": SCORER,
            "scorer_version": version,
        },
    )
    if response.is_error:
        raise _RefereeError(
            f"recording {execution_id} on {eval_id}: {response.status_code} {_detail(response)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--case", required=True)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--repo", type=Path, default=ROOT, help="git repository holding the pins")
    parser.add_argument("--patch", type=Path, action="append", default=[], help="score a file")
    parser.add_argument("--execution", action="append", default=[], help="score and record a run")
    parser.add_argument("--eval", dest="eval_id", help="the eval the --execution runs belong to")
    parser.add_argument("--image", default=workspace_image_ref(WorkspaceImageProvider.CLAUDE_CLI))
    parser.add_argument("--api-url")
    args = parser.parse_args(argv)
    if args.execution and not args.eval_id:
        parser.error("--execution needs --eval")
    if not args.patch and not args.execution:
        parser.error("give --patch FILE or --execution ID (repeatable)")
    if shutil.which("docker") is None:
        print("❌ the referee needs docker on this host", file=sys.stderr)
        return 2

    try:
        loaded = load_suite(args.suite)
        case = loaded.case(args.case)
        commit = scorer_commit_of(ROOT)
        version = scorer_version(loaded.suite.version, commit)
        with httpx.Client(
            base_url=args.api_url or get_dev_api_url(), timeout=60, auth=_basic_auth()
        ) as client:
            patches = [(str(p), read_patch(p)) for p in args.patch]
            patches += [(e, fetch_patch(client, e)) for e in args.execution]
            controls, scored = score_case(
                case, patches, repo=args.repo, scorer_commit=commit, image=args.image
            )
            for control in controls:
                print(f"control {control.label}: {control.run.outcome}")
            if len(scored) != len(patches):
                for control in controls:
                    print(control.run.detail, file=sys.stderr)
                print("❌ a control did not hold: no agent patch was scored", file=sys.stderr)
                return 1
            for item in scored:
                print(f"{item.label}: {item.run.outcome}\n{item.run.detail}")
                if item.label in args.execution:
                    record(client, args.eval_id, item.label, item.run, version)
                    print(f"recorded on {args.eval_id} as {SCORER} {version}")
    except (DefinitionError, _RefereeError, OSError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    return max(EXIT_CODES[item.run.outcome] for item in scored)


if __name__ == "__main__":
    sys.exit(main())
