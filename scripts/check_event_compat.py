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
3. For each fixture in ``scripts/event_compat/fixtures.json``, two independent
   directions. Forward: the current model reads it and writes it, and the
   release's model must read those bytes. Backward: the release's model reads
   the fixture itself and writes it, filling in its own defaults, and the
   current model must read that. The backward payload never passes through
   the current model, so a default the old writer supplies (``None`` where
   this tree now wants a string) is seen.

Both directions read the way the event store does: by the stored
``event_type`` and ``schema_version`` (ESP ADR-027), never by class name, and
the ``@event`` version string must agree. A renamed type or a bumped version is
unreadable to the other side even when no field changed.

A payload the release cannot read passes only when this tree's Event Epoch is
above the release's: then the claim predicate keeps that release's Executors
off the run. A release with no epoch has no predicate, so for it every payload
must be readable. Reading what the release writes is never optional (ADR-007:
no upcasters), and an excused forward direction does not skip it.

The fixture suite must be a non-empty list and must hold a start with non-empty
``tags`` (#1310 V9's negative fixture); otherwise the check cannot run.

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

from event_sourcing.decorators.events import get_event_metadata, resolve_event_class
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


class UnregisteredEventError(Exception):
    """This tree has no class for an identity the release stores events under."""


class Fixture(BaseModel, frozen=True, extra="forbid"):
    name: str
    why: str | None = None
    event: str
    payload: dict[str, JsonValue]


class EventIdentity(BaseModel, frozen=True, extra="forbid"):
    """What an event is stored under and decoded by, and the version ``@event`` declares."""

    event_type: str
    version: str
    schema_version: int

    @classmethod
    def of(cls, model: type[BaseModel]) -> EventIdentity:
        metadata = get_event_metadata(model)
        if metadata is None:
            msg = f"{model.__name__} carries no @event metadata"
            raise CompatCheckError(msg)
        return cls(
            event_type=metadata.event_type,
            version=metadata.version,
            schema_version=getattr(model, "schema_version", 1),
        )


class ProbeRequest(BaseModel, frozen=True, extra="forbid"):
    """One fixture as sent to the release: what this tree writes, and the fixture itself."""

    name: str
    event: str
    identity: EventIdentity
    current: dict[str, JsonValue]
    fixture: dict[str, JsonValue]


class ReleaseWrite(BaseModel, frozen=True, extra="forbid"):
    """An event as the release stores it: its identity and its payload."""

    identity: EventIdentity
    payload: dict[str, JsonValue]


class ReleaseRead(BaseModel, frozen=True, extra="forbid"):
    """The release's answer for one fixture, in both directions.

    ``read_error`` is None when the release read what this tree writes.
    ``written`` is the release's own serialization of the fixture, or
    ``write_error`` says why the release cannot hold that fixture at all.
    """

    read_error: str | None = None
    written: ReleaseWrite | None = None
    write_error: str | None = None


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


def _is_tagged_start(fixture: Fixture) -> bool:
    tags = fixture.payload.get("tags")
    return (
        fixture.event == "WorkflowExecutionStartedEvent" and isinstance(tags, list) and bool(tags)
    )


def load_fixtures(path: Path) -> list[Fixture]:
    """The fixture suite, or CompatCheckError: a suite that tests nothing must not pass."""
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot read fixture file {path}: {exc}"
        raise CompatCheckError(msg) from exc
    if not isinstance(raw, list):
        msg = f"fixture file {path} holds a JSON {type(raw).__name__}, not a list of fixtures"
        raise CompatCheckError(msg)
    if not raw:
        msg = f"fixture file {path} is empty; there is nothing to check"
        raise CompatCheckError(msg)
    try:
        fixtures = [Fixture.model_validate(f) for f in raw]
    except ValidationError as exc:
        msg = f"fixture file {path} holds a malformed fixture: {exc}"
        raise CompatCheckError(msg) from exc
    names = [f.name for f in fixtures]
    if len(set(names)) != len(names):
        msg = f"fixture file {path} repeats a fixture name: {sorted(names)}"
        raise CompatCheckError(msg)
    if not any(_is_tagged_start(f) for f in fixtures):
        msg = (
            f"fixture file {path} has no WorkflowExecutionStartedEvent with non-empty tags; "
            "#1310 V9 requires that negative fixture"
        )
        raise CompatCheckError(msg)
    return fixtures


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


def _current_decoder(identity: EventIdentity) -> type[BaseModel]:
    """The class this tree decodes ``identity`` with, as its event store would."""
    model = resolve_event_class(identity.event_type, identity.schema_version)
    if model is None:
        msg = f"no {identity.event_type} schema_version {identity.schema_version} is registered"
        raise UnregisteredEventError(msg)
    declared = EventIdentity.of(model).version
    if declared != identity.version:
        msg = (
            f"{identity.event_type} is declared @event version {declared!r} here, "
            f"{identity.version!r} there"
        )
        raise UnregisteredEventError(msg)
    return model


def _ask_release(python: Path, requests: list[ProbeRequest], workdir: Path) -> ReleaseAnswer:
    request = workdir / "request.json"
    request.write_text(json.dumps([r.model_dump() for r in requests]), "utf-8")
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

    # Forward sends what this tree actually appends: its own model's serialization.
    # Backward sends the fixture untouched, so the release writes it independently.
    requests: list[ProbeRequest] = []
    for fixture in fixtures:
        model = _current_model(fixture.event)
        try:
            current = model.model_validate(fixture.payload).model_dump(mode="json")
        except ValidationError as exc:
            msg = f"fixture {fixture.name} is stale: this tree cannot read it: {exc}"
            raise CompatCheckError(msg) from exc
        requests.append(
            ProbeRequest(
                name=fixture.name,
                event=fixture.event,
                identity=EventIdentity.of(model),
                current=current,
                fixture=fixture.payload,
            )
        )

    answer = _ask_release(python, requests, workdir)
    guarded = answer.epoch is not None and answer.epoch < ORCHESTRATION_EVENT_EPOCH

    verdicts: list[Verdict] = []
    backward_samples = 0
    for request in requests:
        read = answer.results.get(request.name)
        if read is None:
            msg = f"the release's probe did not answer for fixture {request.name}"
            raise CompatCheckError(msg)
        problems: list[str] = []
        if read.read_error is not None and not guarded:
            problems.append(
                f"{tag} cannot read what this tree writes, and the Event Epoch "
                f"({ORCHESTRATION_EVENT_EPOCH}) is not above {tag}'s ({answer.epoch}): "
                f"{read.read_error}"
            )
        if read.written is not None:
            backward_samples += 1
            try:
                _current_decoder(read.written.identity).model_validate(read.written.payload)
            except (UnregisteredEventError, ValidationError) as exc:
                problems.append(f"this tree cannot read what {tag} writes: {exc}")
        elif read.write_error is None:
            msg = f"the release's probe gave neither a payload nor a reason for {request.name}"
            raise CompatCheckError(msg)
        verdicts.append(Verdict(request.name, "\n       ".join(problems) or None))
    if not backward_samples:
        msg = f"{tag} could write none of the fixtures, so the backward direction went untested"
        raise CompatCheckError(msg)
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--tag", help="release to check against (default: newest vX.Y.Z not at HEAD)"
    )
    args = parser.parse_args()
    try:
        fixtures = load_fixtures(FIXTURES)
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
