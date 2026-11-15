#!/usr/bin/env python3
"""Build the part of the VSA manifest the architecture docs read, without `vsa`.

`scripts/architecture-docs.sh` runs `vsa manifest --include-domain` and feeds
the result to `scripts/generate-architecture-docs.py`. The agent workspace
image has no `vsa`, so an agent cannot regenerate the docs (#1782). This module
reads the same facts straight from the source tree, so it needs only Python.

Contract: the fields `generate-architecture-docs.py` reads, and nothing else.

    bounded_contexts[].name                    the set of context names
    domain.aggregates[].name, .context         README / docs-site aggregate table
    domain.commands[].name                     counts, and the "likely command"
                                               column of the event-flow table
    domain.commands[].context, .file_path      the order the generator meets
                                               commands in: it canonicalises the
                                               manifest (sorting each array by its
                                               JSON), and the first command whose
                                               name prefixes an event wins
    domain.events[]                            counts only
    domain.projections[]                       counts only
    domain.relationships.event_to_projections  event name -> projection names

Every other manifest field (features, slice types, queries, upcasters,
command_to_aggregate, ...) is out of scope and is not produced. The vsa-overview
SVG is drawn by ESP's vsa-visualizer from the full manifest, so it still needs
`vsa`.

Discovery follows `vsa.yaml` and the rules of the VSA tool in
`lib/event-sourcing-platform/vsa/vsa-core/src` (pinned at v0.18.0), which this
module ports rather than reinterprets:

    scanner.rs                   every directory directly under `root` whose
                                 name does not start with `_` is a context
    manifest.rs                  each context with a `domain/` dir is scanned
    aggregate_scanner.rs         `*Aggregate.*` in an `aggregate_*/` folder, or
                                 loose anywhere else under `domain/`
    command_scanner.rs           `*Command.{ts,py,rs}` under `domain/commands/`
    event_scanner.rs             `*Event[.version].{ts,py,rs}` under
                                 `domain/events/`, plus its `_versioned/`
    projection_scanner.rs        `*Projection.*` or `projection.*` anywhere in
                                 the context (not only `domain/`), with the
                                 subscribed events found by its five regexes

`ci/fitness/code_quality/test_architecture_manifest_parity.py` proves the
result equal to `vsa manifest` for this contract, wherever `vsa` exists.

Usage:
    uv run python scripts/architecture_manifest.py --output .topology/syn-manifest.json
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, ConfigDict


class UnsupportedLayoutError(ValueError):
    """The tree or vsa.yaml uses a VSA feature this reader has not ported."""


class _ManifestPart(BaseModel):
    # extra="ignore": the same models read `vsa manifest` output for the parity
    # check, and that manifest carries every field this contract leaves out.
    model_config = ConfigDict(frozen=True, extra="ignore")


class BoundedContext(_ManifestPart):
    name: str


class Aggregate(_ManifestPart):
    name: str
    context: str


class Command(_ManifestPart):
    name: str
    context: str
    file_path: str


class Event(_ManifestPart):
    name: str
    context: str


class Projection(_ManifestPart):
    name: str
    context: str


class Relationships(_ManifestPart):
    event_to_projections: dict[str, tuple[str, ...]] = {}


class Domain(_ManifestPart):
    aggregates: tuple[Aggregate, ...]
    commands: tuple[Command, ...]
    events: tuple[Event, ...]
    projections: tuple[Projection, ...] = ()
    relationships: Relationships


class ArchitectureManifest(_ManifestPart):
    """The consumed subset of a VSA manifest, from either source."""

    bounded_contexts: tuple[BoundedContext, ...]
    domain: Domain

    def canonical(self) -> ArchitectureManifest:
        """The same facts in the order the docs generator would see them.

        Two manifests that are equal here produce the same docs. `file_path`
        loses a leading `./`, which `vsa` keeps from `root:` in vsa.yaml; a
        common prefix never changes the order, so nothing the generator sees
        depends on it.
        """
        domain = self.domain
        return ArchitectureManifest(
            bounded_contexts=tuple(sorted(self.bounded_contexts, key=lambda c: c.name)),
            domain=Domain(
                aggregates=tuple(sorted(domain.aggregates, key=lambda a: (a.context, a.name))),
                commands=tuple(
                    sorted(
                        (
                            c.model_copy(update={"file_path": PurePosixPath(c.file_path).as_posix()})
                            for c in domain.commands
                        ),
                        key=lambda c: (c.context, c.file_path),
                    )
                ),
                events=tuple(sorted(domain.events, key=lambda e: (e.context, e.name))),
                projections=tuple(sorted(domain.projections, key=lambda p: (p.context, p.name))),
                relationships=Relationships(
                    event_to_projections={
                        event: tuple(sorted(projections))
                        for event, projections in sorted(
                            domain.relationships.event_to_projections.items()
                        )
                    }
                ),
            ),
        )


class _Layout(BaseModel):
    """The parts of vsa.yaml that steer discovery, resolved against the repo."""

    model_config = ConfigDict(frozen=True)

    root: Path
    domain: str
    commands: str
    events: str
    versioned: str | None


def read_manifest(repo_root: Path, config: Path) -> ArchitectureManifest:
    """Discover every context, aggregate, command, event and projection."""
    layout = _read_layout(repo_root, config)
    contexts = sorted(
        p.name for p in layout.root.iterdir() if p.is_dir() and not p.name.startswith("_")
    )
    if (layout.root / layout.domain).is_dir():
        raise UnsupportedLayoutError(
            f"{layout.root / layout.domain}: vsa also scans a context-less root domain;"
            " this reader does not"
        )

    aggregates: list[Aggregate] = []
    commands: list[Command] = []
    events: list[Event] = []
    projections: list[tuple[Projection, tuple[str, ...]]] = []
    for context in contexts:
        context_path = layout.root / context
        domain_path = context_path / layout.domain
        if not domain_path.exists():
            continue
        if not domain_path.is_dir():
            raise UnsupportedLayoutError(f"{domain_path}: domain path is not a directory")
        aggregates += [Aggregate(name=n, context=context) for n in _aggregates(domain_path)]
        commands += [
            Command(name=_strip(p.name, _COMMAND_EXTS), context=context, file_path=_rel(p, repo_root))
            for p in _walk(domain_path / layout.commands, skip=lambda d: False)
            if _strip(p.name, _COMMAND_EXTS).endswith("Command")
        ]
        events += [Event(name=n, context=context) for n in _events(domain_path / layout.events, layout)]
        projections += [
            (Projection(name=name, context=context), subscribed)
            for name, subscribed in _projections(context_path)
        ]

    event_to_projections: dict[str, list[str]] = {}
    for projection, subscribed in projections:
        for event in subscribed:
            event_to_projections.setdefault(event, []).append(projection.name)

    return ArchitectureManifest(
        bounded_contexts=tuple(BoundedContext(name=c) for c in contexts),
        domain=Domain(
            aggregates=tuple(aggregates),
            commands=tuple(commands),
            events=tuple(events),
            projections=tuple(p for p, _ in projections),
            relationships=Relationships(
                event_to_projections={e: tuple(p) for e, p in event_to_projections.items()}
            ),
        ),
    ).canonical()


def _read_layout(repo_root: Path, config: Path) -> _Layout:
    raw = yaml.safe_load((repo_root / config).read_text(encoding="utf-8"))
    convention = raw.get("patterns", {}).get("filename_convention", "pascal_case")
    if convention != "pascal_case":
        raise UnsupportedLayoutError(f"patterns.filename_convention: {convention} is not ported")
    domain = raw.get("domain")
    if domain is None:
        raise UnsupportedLayoutError("vsa.yaml has no domain: section; nothing to scan")
    versioning = domain.get("events", {}).get("versioning", {})
    return _Layout(
        root=(repo_root / config).parent / raw["root"],
        domain=domain.get("path", "domain"),
        commands=domain.get("commands", {}).get("path", "commands"),
        events=domain.get("events", {}).get("path", "events"),
        versioned=versioning.get("versioned_path", "_versioned")
        if versioning.get("enabled", True)
        else None,
    )


_COMMAND_EXTS = (".ts", ".py", ".rs")
_PROJECTION_EXTS = (".ts", ".tsx", ".py", ".rs")
_AGGREGATE_EXTS = (".ts", ".tsx", ".py", ".rs", ".js", ".jsx")
_CODE_EXTS = (".ts", ".py", ".rs", ".tsx", ".js")


def _strip(file_name: str, extensions: tuple[str, ...]) -> str:
    """Drop the first listed extension the name ends with, as the Rust or_else chains do."""
    for extension in extensions:
        if file_name.endswith(extension):
            return file_name[: -len(extension)]
    return file_name


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _walk(directory: Path, skip: Callable[[str], bool]) -> Iterator[Path]:
    """Every file under `directory`, never entering hidden or skipped dirs."""
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if entry.is_dir():
            if not entry.name.startswith(".") and not skip(entry.name):
                yield from _walk(entry, skip)
        elif entry.is_file():
            yield entry


def _aggregates(domain_path: Path) -> Iterator[str]:
    """aggregate_scanner.rs: one root per `aggregate_*/` folder, else loose files."""
    for entry in domain_path.iterdir():
        if entry.is_dir():
            if entry.name.startswith("."):
                continue
            if entry.name.startswith("aggregate_"):
                roots = [
                    _strip(f.name, _AGGREGATE_EXTS)
                    for f in entry.iterdir()
                    if f.is_file()
                    and f.name.endswith(_CODE_EXTS)
                    and not _is_test_file(f.name)
                    and _strip(f.name, _AGGREGATE_EXTS).endswith("Aggregate")
                ]
                if len(roots) > 1:
                    # vsa keeps whichever its directory walk met last.
                    raise UnsupportedLayoutError(f"{entry}: more than one aggregate root {roots}")
                yield from roots
            else:
                yield from _aggregates(entry)
        elif entry.is_file() and _strip(entry.name, _AGGREGATE_EXTS).endswith("Aggregate"):
            yield _strip(entry.name, _AGGREGATE_EXTS)


def _is_test_file(file_name: str) -> bool:
    return (
        ".test." in file_name
        or "_test." in file_name
        or file_name.startswith("test_")
        or ".spec." in file_name
    )


def _events(events_path: Path, layout: _Layout) -> Iterator[str]:
    """event_scanner.rs: the main tree, then the versioned tree if enabled."""
    skipped = {"_upcasters", layout.versioned}
    roots = [events_path]
    if layout.versioned is not None and (events_path / layout.versioned).exists():
        roots.append(events_path / layout.versioned)
    for root in roots:
        for path in _walk(root, skip=lambda name: name in skipped):
            stem = _strip(path.name, _COMMAND_EXTS)
            base = stem[: stem.rfind(".")] if "." in stem else stem
            if base.endswith("Event"):
                yield _event_name(stem)


def _event_name(stem: str) -> str:
    """`parse_name_and_version`: `XEvent.v2` and `XEvent.2.1.0` are `XEvent`."""
    parts = stem.split(".")
    if len(parts) == 4 and all(_is_u32(p) for p in parts[1:]):
        return parts[0]
    if len(parts) == 2 and parts[1].startswith("v"):
        return parts[0]
    return stem


def _is_u32(text: str) -> bool:
    """Rust's `str::parse::<u32>`: ASCII digits, an optional leading `+`."""
    digits = text.removeprefix("+")
    return digits.isascii() and digits.isdigit() and int(digits) < 2**32


_PROJECTION_DIRS_SKIPPED = frozenset({"node_modules", "__pycache__", "target"})


def _projections(context_path: Path) -> Iterator[tuple[str, tuple[str, ...]]]:
    """projection_scanner.rs: every projection file in the context and its events."""
    for path in _walk(context_path, skip=lambda name: name in _PROJECTION_DIRS_SKIPPED):
        stem = _strip(path.name, _PROJECTION_EXTS)
        if not (stem.endswith("Projection") or stem == "projection"):
            continue
        content = path.read_text(encoding="utf-8")
        yield _projection_name(stem, content), subscribed_events(content)


_CLASS_PROJECTION = re.compile(r"(?:class|export\s+class)\s+(\w+Projection)")


def _projection_name(stem: str, content: str) -> str:
    if stem != "projection":
        return stem
    match = _CLASS_PROJECTION.search(content)
    return match.group(1) if match else "Projection"


_METHOD_VERB_PREFIXES = frozenset({"get", "set", "load", "save", "create", "update", "delete"})
_NON_EVENT_METHODS = frozenset(
    {
        "init", "error", "complete", "start", "end", "id", "ms", "type", "data", "time",
        "name", "value", "projection", "event", "message", "result", "status", "create",
        "update", "delete", "get", "set", "load", "save",
    }
)  # fmt: skip
_ON = re.compile(r"(?:async\s+)?def\s+on_(\w+)|\bon_(\w+)\s*[:\(]")
_HANDLE = re.compile(r"def\s+handle_(\w+)")
_DECORATOR = re.compile(r"@(?:Handles|Subscribe|EventHandler)\s*\(\s*(\w+Event)\s*\)")
_TYPED_HANDLE = re.compile(r"handle\s*\(\s*\w+:\s*(\w+Event)\s*\)")
_SUBSCRIBED_LIST = re.compile(r"subscribed_events\s*=\s*\[([^\]]+)\]")
_QUOTED = re.compile(r"[\"'](\w+)[\"']")


def subscribed_events(content: str) -> tuple[str, ...]:
    """`extract_subscribed_events`: the event names a projection file handles."""
    events: set[str] = set()
    for match in _ON.finditer(content):
        name = match.group(1) or match.group(2)
        if "_" in name and _is_snake_case_event(name):
            events.add(name)
        elif _is_pascal_case_event(name):
            events.add(f"{name}Event")
    for match in _HANDLE.finditer(content):
        name = match.group(1)
        if name.endswith("Event"):
            events.add(name)
        elif "_" in name and _is_snake_case_event(name):
            events.add(name)
        elif _is_pascal_case_event(name):
            events.add(f"{name}Event")
    events.update(m.group(1) for m in _DECORATOR.finditer(content))
    events.update(m.group(1) for m in _TYPED_HANDLE.finditer(content))
    listed = _SUBSCRIBED_LIST.search(content)
    if listed:
        for match in _QUOTED.finditer(listed.group(1)):
            name = match.group(1)
            if name.endswith("Event") or ("_" in name and _is_snake_case_event(name)):
                events.add(name)
    return tuple(sorted(events))


def _is_snake_case_event(name: str) -> bool:
    parts = [part for part in name.split("_") if part]
    return (
        len(parts) >= 2
        and all(len(part.encode()) >= 2 for part in parts)
        and parts[0] not in _METHOD_VERB_PREFIXES
    )


def _is_pascal_case_event(name: str) -> bool:
    return (
        name[:1].isupper()
        and len(name.encode()) > 3
        and name.lower() not in _NON_EVENT_METHODS
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("vsa.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = read_manifest(Path.cwd(), args.config)
    except UnsupportedLayoutError as error:
        raise SystemExit(f"❌ {error}") from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
