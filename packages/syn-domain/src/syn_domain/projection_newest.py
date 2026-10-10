"""The newest document per group, chosen by instant, in one store read.

"What did each phase of this workflow last produce" used to be answered one
phase at a time, each a newest-first scan of whole documents (bodies included)
in windows, ordered by the TEXT of the timestamp. Text order is not time order
once offsets differ: ``10:00+02:00`` sorts after ``09:00+00:00`` although it
happened an hour earlier.

:class:`ProjectionNewestPerGroup` asks the store for the whole answer at once:
per distinct value of ``group_field``, the one matching document whose
``timestamp_field`` names the LATEST INSTANT, ties broken by the lowest key, so
the answer is total and two reads of the same data agree. Only ``fields`` come
back, so a heavy field nobody renders is never read.

:func:`newest_per_group` is the definition in Python. The in-memory store is
built on it, and a store without the capability is answered with it over one
filtered read; the Postgres store writes the same rule as one statement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.pagination import coerce_datetime

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from syn_domain.pagination import ProjectionRecord
    from syn_domain.projection_scan import JsonValue


@runtime_checkable
class ProjectionNewestPerGroup(Protocol):
    """A projection store that can pick the newest document per group itself."""

    async def newest_per_group(
        self,
        projection: str,
        *,
        group_field: str,
        timestamp_field: str,
        fields: Sequence[str],
        filters: Mapping[str, str | Sequence[str]] | None = None,
        flag_field: str | None = None,
    ) -> dict[str, Mapping[str, JsonValue]]:
        """Group value -> the listed ``fields`` of that group's newest document.

        Same filter semantics as the store's ``query``. A document is a
        candidate only when its ``timestamp_field`` names an instant (read as
        :func:`syn_domain.pagination.coerce_datetime` reads it) and, given a
        ``flag_field``, that field does not read false: absent or non-boolean
        reads as true, the rule ``read_primary_flag`` applies. A document with
        no ``group_field`` belongs to no group. Every listed field is present
        in each mapping, ``None`` where the document lacks it.
        """
        ...


def flag_reads_true(value: object) -> bool:
    """A flag field's reading: only a real ``False`` is false."""
    return value if isinstance(value, bool) else True


def newest_per_group[R: ProjectionRecord](
    records: Iterable[tuple[str, R]],
    *,
    group_field: str,
    timestamp_field: str,
    flag_field: str | None = None,
) -> dict[str, tuple[str, R]]:
    """Group value -> ``(key, record)`` of its newest candidate; see the protocol."""
    best: dict[str, tuple[datetime, str, R]] = {}
    for key, record in records:
        group = record.get(group_field)
        if not isinstance(group, str):
            continue
        if flag_field is not None and not flag_reads_true(record.get(flag_field)):
            continue
        instant = coerce_datetime(record.get(timestamp_field))
        if instant is None:
            continue
        held = best.get(group)
        if held is None or instant > held[0] or (instant == held[0] and key < held[1]):
            best[group] = (instant, key, record)
    return {group: (key, record) for group, (_, key, record) in best.items()}
