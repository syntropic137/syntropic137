"""Runs INSIDE the previous release's environment: can its models read these payloads?

Reads ``[{"name", "event", "current", "fixture"}]`` from the file named by
argv[1] and prints, as JSON, the release's Event Epoch and, per fixture: whether
the release reads what the current tree writes (``read_error`` when not), and
the release's own serialization of the fixture itself (``written``), or why it
cannot hold it (``write_error``).

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


def _model(name: str) -> type:
    try:
        return getattr(importlib.import_module(_EVENTS), name)
    except AttributeError:
        return getattr(importlib.import_module(f"{_EVENTS}.{name}"), name)


def _serialize(
    name: str, payload: dict[str, object]
) -> tuple[dict[str, object] | None, str | None]:
    try:
        model = _model(name)
    except (ImportError, AttributeError) as exc:
        return None, f"the release has no {name}: {exc}"
    try:
        return model.model_validate(payload).model_dump(mode="json"), None
    except ValueError as exc:  # pydantic.ValidationError is a ValueError
        return None, str(exc)


def _answer(fixture: dict[str, object]) -> dict[str, object]:
    _, read_error = _serialize(fixture["event"], fixture["current"])
    written, write_error = _serialize(fixture["event"], fixture["fixture"])
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
