"""Release gate: can the previous release read what this tree writes, and back?

ADR-072 D9, #1310 V9. During an overlapping deploy a release's API writes a
start that the previous release's Executor may load. The schema snapshot
fitness function proves a change was *noticed*; this proves it is *survivable*,
against the real previous release rather than a hand-written copy of it.

1. Resolve the previous release: the newest ``vX.Y.Z`` tag not at HEAD (the
   release branch is not an ancestor of main, so history cannot say), or
   ``--tag``.
2. Build that tag's ``syn-domain`` into an isolated venv, with ``syn-shared``,
   ``event-sourcing-python`` and ``agentic-events`` from the same tag and
   submodule pins, plus ``grpcio`` (ESP imports it at package import but only
   declares it in an extra).
3. For each fixture in ``scripts/event_compat/fixtures.json``: the current
   model reads it and writes it; the release's model must read those bytes;
   the current model must read what the release writes back.

A payload the release cannot read passes only when this tree's Event Epoch is
above the release's: then the claim predicate keeps that release's Executors
off the run. A release with no epoch has no predicate, so for it every payload
must be readable. Reading what the release writes is never optional (ADR-007:
no upcasters).

Exit codes: 0 compatible, 1 incompatible, 2 the check itself could not run.

    just check-event-compat [--tag vX.Y.Z]
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, JsonValue, ValidationError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts/event_compat/fixtures.json"
PROBE = ROOT / "scripts/event_compat/probe.py"
_EVENTS = "syn_domain.contexts.orchestration.domain.events"
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

#: What a release's syn-domain is installed from, at that release's pins:
#: (repository root, or the submodule it lives in; path inside it).
_SOURCES = (
    (None, "packages/syn-shared"),
    (None, "packages/syn-domain"),
    ("lib/event-sourcing-platform", "event-sourcing/python"),
    ("lib/agentic-workspace", "lib/python/agentic_events"),
)


class CompatCheckError(Exception):
    """The check could not run; says nothing about compatibility."""


class Fixture(BaseModel, frozen=True, extra="forbid"):
    name: str
    why: str | None = None
    event: str
    payload: dict[str, JsonValue]


class ReleaseRead(BaseModel, frozen=True, extra="forbid"):
    """The release's answer for one payload: what it wrote back, or why it refused."""

    written: dict[str, JsonValue] | None = None
    error: str | None = None


class ReleaseAnswer(BaseModel, frozen=True, extra="forbid"):
    """What ``scripts/event_compat/probe.py`` prints. ``epoch`` is None before ADR-072 D9."""

    epoch: int | None
    results: dict[str, ReleaseRead]


@dataclass(frozen=True)
class Verdict:
    fixture: str
    problem: str | None

    @property
    def ok(self) -> bool:
        return self.problem is None


def _git(*args: str, cwd: Path = ROOT) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        msg = f"git {' '.join(args)} (in {cwd}) failed: {done.stderr.strip()}"
        raise CompatCheckError(msg)
    return done.stdout.strip()


def previous_release(explicit: str | None) -> str:
    if explicit:
        return explicit
    at_head = set(_git("tag", "--points-at", "HEAD").split())
    releases = [
        (tuple(int(n) for n in match.groups()), tag)
        for tag in _git("tag", "--list", "v*").split()
        if (match := _RELEASE_TAG.match(tag)) and tag not in at_head
    ]
    if not releases:
        msg = "no vX.Y.Z release tag found; run `git fetch --tags` or pass --tag"
        raise CompatCheckError(msg)
    return max(releases)[1]


def _submodule_pin(tag: str, submodule: str) -> str:
    entry = _git("ls-tree", tag, submodule).split()
    if len(entry) < 3 or entry[1] != "commit":
        msg = f"{tag} has no submodule at {submodule}"
        raise CompatCheckError(msg)
    return entry[2]


def _export(tag: str, submodule: str | None, path: str, into: Path) -> Path:
    repo = ROOT if submodule is None else ROOT / submodule
    ref = tag if submodule is None else _submodule_pin(tag, submodule)
    if (
        submodule is not None
        and subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
    ):
        _git("fetch", "-q", "origin", ref, cwd=repo)
    archive = into / "src.tar"
    _git("archive", "-o", str(archive), ref, path, cwd=repo)
    with tarfile.open(archive) as tar:
        tar.extractall(into / (submodule or "."), filter="data")
    archive.unlink()
    return into / (submodule or ".") / path


def build_release_env(tag: str, workdir: Path) -> Path:
    """A venv holding ``tag``'s syn-domain and nothing of this tree. Returns its python."""
    sources = [str(_export(tag, sub, path, workdir)) for sub, path in _SOURCES]
    venv = workdir / ".venv"
    python = venv / "bin/python"
    for cmd in (
        ["uv", "venv", "-q", "-p", "3.12", str(venv)],
        ["uv", "pip", "install", "-q", "--python", str(python), *sources, "grpcio", "protobuf"],
    ):
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            msg = f"building {tag}'s syn-domain failed: {' '.join(cmd[:3])}: {done.stderr.strip()}"
            raise CompatCheckError(msg)
    return python


def _current_model(name: str) -> type[BaseModel]:
    try:
        return getattr(importlib.import_module(_EVENTS), name)
    except AttributeError as exc:
        msg = f"fixture names {name}, which this tree does not define"
        raise CompatCheckError(msg) from exc


def _ask_release(python: Path, fixtures: list[Fixture], workdir: Path) -> ReleaseAnswer:
    request = workdir / "request.json"
    request.write_text(json.dumps([f.model_dump() for f in fixtures]), "utf-8")
    done = subprocess.run(
        [str(python), "-I", str(PROBE), str(request)], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        msg = f"the release's probe crashed: {done.stderr.strip()}"
        raise CompatCheckError(msg)
    try:
        return ReleaseAnswer.model_validate_json(done.stdout)
    except ValidationError as exc:
        msg = f"the release's probe answered in an unexpected shape: {exc}"
        raise CompatCheckError(msg) from exc


def check(tag: str, python: Path, fixtures: list[Fixture], workdir: Path) -> list[Verdict]:
    from syn_domain.contexts.orchestration._shared.event_epoch import ORCHESTRATION_EVENT_EPOCH

    # What this tree actually appends: its own model's serialization of each fixture.
    written: list[Fixture] = []
    for fixture in fixtures:
        model = _current_model(fixture.event)
        try:
            payload = model.model_validate(fixture.payload).model_dump(mode="json")
        except ValidationError as exc:
            msg = f"fixture {fixture.name} is stale: this tree cannot read it: {exc}"
            raise CompatCheckError(msg) from exc
        written.append(fixture.model_copy(update={"payload": payload}))

    answer = _ask_release(python, written, workdir)
    guarded = answer.epoch is not None and answer.epoch < ORCHESTRATION_EVENT_EPOCH

    verdicts: list[Verdict] = []
    for fixture in written:
        read = answer.results[fixture.name]
        if read.written is None:
            problem = (
                None
                if guarded
                else (
                    f"{tag} cannot read what this tree writes, and the Event Epoch "
                    f"({ORCHESTRATION_EVENT_EPOCH}) is not above {tag}'s ({answer.epoch}): "
                    f"{read.error}"
                )
            )
            verdicts.append(Verdict(fixture.name, problem))
            continue
        try:
            _current_model(fixture.event).model_validate(read.written)
        except ValidationError as exc:
            verdicts.append(
                Verdict(fixture.name, f"this tree cannot read what {tag} writes: {exc}")
            )
            continue
        verdicts.append(Verdict(fixture.name, None))
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--tag", help="release to check against (default: newest vX.Y.Z not at HEAD)"
    )
    args = parser.parse_args()
    try:
        fixtures = [Fixture.model_validate(f) for f in json.loads(FIXTURES.read_text("utf-8"))]
        tag = previous_release(args.tag)
        with tempfile.TemporaryDirectory(prefix=f"event-compat-{tag}-") as tmp:
            workdir = Path(tmp)
            print(f"check-event-compat: building {tag}'s syn-domain in {workdir}")
            python = build_release_env(tag, workdir)
            verdicts = check(tag, python, fixtures, workdir)
    except CompatCheckError as exc:
        print(f"check-event-compat: could not run: {exc}", file=sys.stderr)
        return 2
    for v in verdicts:
        print(
            f"  {'ok  ' if v.ok else 'FAIL'} {v.fixture}"
            + ("" if v.ok else f"\n       {v.problem}")
        )
    failed = [v for v in verdicts if not v.ok]
    print(
        f"check-event-compat: {len(verdicts) - len(failed)}/{len(verdicts)} compatible with {tag}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
