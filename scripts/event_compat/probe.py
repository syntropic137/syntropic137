"""Runs INSIDE the previous release's environment: can its models read these payloads?

Reads ``[{"name", "event", "identity", "current", "fixture"}]`` from the file
named by argv[1] and prints, as JSON, the release's Event Epoch and, per
fixture: whether the release reads what the current tree writes (``read_error``
when not), and the release's own serialization of the fixture itself with the
identity it is stored under (``written``), or why it cannot hold it
(``write_error``).

The release reads the way its event store does: by the stored ``event_type``
and ``schema_version`` (ESP ADR-027), not by class name. So a renamed type or a
bumped version is unreadable here even when no field changed, as it is to an
old Executor (``UnknownEventVersionError``). The ``@event`` version string must
match too: it declares the version, and declaring a new one is a declared
contract change.

Stdlib and the release's own packages only: this file is executed by an
interpreter that has never seen the current tree.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_EVENTS = "syn_domain.contexts.orchestration.domain.events"
_EPOCH = "syn_domain.contexts.orchestration._shared.event_epoch"
_DECORATORS = "event_sourcing.decorators.events"


def _model(name: str) -> type:
    try:
        return getattr(importlib.import_module(_EVENTS), name)
    except AttributeError:
        return getattr(importlib.import_module(f"{_EVENTS}.{name}"), name)


def _identity(model: type) -> dict[str, object]:
    metadata = importlib.import_module(_DECORATORS).get_event_metadata(model)
    return {
        "event_type": metadata.event_type,
        "version": metadata.version,
        "schema_version": getattr(model, "schema_version", 1),
    }


def _decoder(identity: dict[str, object]) -> tuple[type | None, str | None]:
    """The class this release decodes ``identity`` with, or why it has none."""
    decorators = importlib.import_module(_DECORATORS)
    event_type, schema_version = identity["event_type"], identity["schema_version"]
    if hasattr(decorators, "resolve_event_class"):
        model = decorators.resolve_event_class(event_type, schema_version)
    else:  # before ESP ADR-027 a reader decoded by type alone
        model = decorators.resolve_event_type(event_type)
    if model is None:
        return None, f"the release cannot decode {event_type} schema_version {schema_version}"
    declared = _identity(model)["version"]
    if declared != identity["version"]:
        return None, (
            f"the release declares {event_type} as @event version {declared!r}, "
            f"this tree as {identity['version']!r}"
        )
    return model, None


def _validate(
    model: type, payload: dict[str, object]
) -> tuple[dict[str, object] | None, str | None]:
    try:
        return model.model_validate(payload).model_dump(mode="json"), None
    except ValueError as exc:  # pydantic.ValidationError is a ValueError
        return None, str(exc)


def _read(identity: dict[str, object], payload: dict[str, object]) -> str | None:
    model, error = _decoder(identity)
    if model is None:
        return error
    return _validate(model, payload)[1]


def _write(name: str, payload: dict[str, object]) -> tuple[dict[str, object] | None, str | None]:
    try:
        model = _model(name)
    except (ImportError, AttributeError) as exc:
        return None, f"the release has no {name}: {exc}"
    written, error = _validate(model, payload)
    if written is None:
        return None, error
    return {"identity": _identity(model), "payload": written}, None


def _answer(fixture: dict[str, object]) -> dict[str, object]:
    # Writing first imports the fixture's module, which registers its class for reading.
    written, write_error = _write(fixture["event"], fixture["fixture"])
    read_error = _read(fixture["identity"], fixture["current"])
    return {"read_error": read_error, "written": written, "write_error": write_error}


def main() -> None:
    fixtures = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        epoch = importlib.import_module(_EPOCH).ORCHESTRATION_EVENT_EPOCH
    except ImportError:
        epoch = None
    results = {f["name"]: _answer(f) for f in fixtures}
    json.dump({"epoch": epoch, "results": results}, sys.stdout)


if __name__ == "__main__":
    main()
