"""Count a projection's documents by the values of a few fields (#967).

A tally - how many executions each Eval has, by status - is a handful of
numbers, however many documents it counts. Reading every matching document to
add them up in Python moves the whole membership out of the database to
produce those numbers, so a store that can group (:class:`ProjectionGroupCount`)
is handed the question and returns only the groups. A store that cannot (the
in-memory store, the test doubles) is read and counted here, with the same
answer.

A grouped value is the field's TEXT, as Postgres ``->>`` gives it: a string as
itself, ``None`` where the document lacks the field or holds null, and any
other JSON value as its JSON text.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from event_sourcing import ProjectionStore

    from syn_domain.projection_scan import JsonValue

#: One group: each grouped field's text, in the order the fields were given.
type GroupKey = tuple[str | None, ...]


@runtime_checkable
class ProjectionGroupCount(Protocol):
    """A projection store that can count matching documents per group itself."""

    async def count_by(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, str | Sequence[str]] | None = None,
    ) -> list[tuple[GroupKey, int]]:
        """Each group of ``fields``' text values among matching documents, and its size.

        Same filter semantics as the store's ``query``. Only groups with at
        least one document appear, in no particular order.
        """
        ...


async def count_by(
    store: ProjectionStore,
    projection: str,
    fields: Sequence[str],
    *,
    filters: Mapping[str, str | Sequence[str]] | None = None,
) -> dict[GroupKey, int]:
    """How many documents matching ``filters`` hold each combination of ``fields``."""
    if isinstance(store, ProjectionGroupCount):
        return dict(await store.count_by(projection, fields, filters=filters))
    documents = await store.query(projection, filters=dict(filters) if filters else None)
    return dict(Counter(tuple(_text(document.get(f)) for f in fields) for document in documents))


def _text(value: JsonValue) -> str | None:
    """A JSON value as Postgres ``->>`` reads it."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, separators=(", ", ": "))
