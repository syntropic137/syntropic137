"""The schema snapshot of every orchestration event, keyed by Event Epoch.

ADR-072 D9: an Executor claims only runs whose ``writer_epoch`` is no higher
than its own ``ORCHESTRATION_EVENT_EPOCH``. That guard is only as good as the
epoch: a schema change shipped under the old number lets an older Executor
claim a run whose events it cannot read. The snapshot is what makes "the
schema changed" a fact a test can see.

One file per epoch, ``snapshots/orchestration_events.epoch-<N>.json``. The file
for an epoch is written once, when that epoch is introduced, and never
rewritten: ``write_snapshot`` refuses an epoch that already has one. So a
schema change leaves exactly one way to green, which is to bump the epoch and
snapshot the new one.

What is compared is what a reader accepts (the validation schema), with titles,
descriptions and examples removed: a docstring edit changes no payload.

Regenerate after bumping the epoch::

    uv run python -m ci.fitness.event_sourcing._orchestration_event_schemas
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING

from ci.fitness._event_discovery import discover_event_classes
from ci.fitness.conftest import repo_root

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import BaseModel, JsonValue

#: JSON Schema keywords that annotate without constraining what a reader accepts.
_ANNOTATIONS = frozenset({"title", "description", "examples"})

#: Schema keywords whose value is a map keyed by a NAME, not by a keyword.
#: Their keys are kept as written: a field may well be called ``description``.
_NAMED_MAPS = frozenset({"properties", "$defs", "patternProperties"})

_ORCHESTRATION_EVENTS = "src/syn_domain/contexts/orchestration/domain/events/"


def snapshot_path(epoch: int) -> Path:
    """Where the snapshot for ``epoch`` lives."""
    return (
        repo_root()
        / "ci/fitness/event_sourcing/snapshots"
        / f"orchestration_events.epoch-{epoch}.json"
    )


def _event_models() -> dict[str, type[BaseModel]]:
    """Every ``@event`` class under the orchestration context, by class name."""
    models: dict[str, type[BaseModel]] = {}
    for name, path in discover_event_classes().items():
        posix = path.as_posix()
        if _ORCHESTRATION_EVENTS not in posix:
            continue
        module = posix.split("src/")[1].removesuffix(".py").replace("/", ".")
        models[name] = getattr(importlib.import_module(module), name)
    return dict(sorted(models.items()))


def _without_annotations(schema: JsonValue, *, named: bool = False) -> JsonValue:
    if isinstance(schema, list):
        return [_without_annotations(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if named:
        return {key: _without_annotations(value) for key, value in schema.items()}
    return {
        key: _without_annotations(value, named=key in _NAMED_MAPS)
        for key, value in schema.items()
        if key not in _ANNOTATIONS
    }


def current_schemas() -> dict[str, JsonValue]:
    """The schema each orchestration event accepts today, by class name."""
    return {
        name: _without_annotations(model.model_json_schema(mode="validation"))
        for name, model in _event_models().items()
    }


def load_snapshot(epoch: int) -> dict[str, JsonValue] | None:
    """The snapshot recorded for ``epoch``, or None when there is none."""
    path = snapshot_path(epoch)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_snapshot(epoch: int) -> Path:
    """Record today's schemas as ``epoch``'s snapshot. Refuses to overwrite one."""
    path = snapshot_path(epoch)
    if path.exists():
        msg = (
            f"{path.name} already exists. An epoch's snapshot is never rewritten: "
            f"bump ORCHESTRATION_EVENT_EPOCH and snapshot the new epoch instead."
        )
        raise FileExistsError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current_schemas(), indent=2, sort_keys=True) + "\n", "utf-8")
    return path


if __name__ == "__main__":
    from syn_domain.contexts.orchestration._shared.event_epoch import ORCHESTRATION_EVENT_EPOCH

    print(f"wrote {write_snapshot(ORCHESTRATION_EVENT_EPOCH)}")
