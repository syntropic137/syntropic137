"""Tags on workflows and executions (#967).

A tag is an ordinary, user-chosen label. It carries no domain meaning: an
execution's eval membership comes from a typed ``eval_id`` (a later slice),
never from a tag, so nothing may branch on a tag's spelling.

``TagSet`` is the ONE place the rules live. Every path that accepts tags --
workflow YAML, the create/update commands, the add/remove commands, the
execute request and the ``?tag=`` filter -- validates through it, so two
entry points cannot disagree about what a tag is.

The rules:

- each tag is trimmed and lowercased, then the set is deduped and sorted, so
  ``[" Nightly", "nightly"]`` and ``["nightly"]`` are the same set;
- at most ``MAX_TAGS`` tags per record and ``MAX_TAG_LENGTH`` characters per
  tag, from ``[a-z0-9-_./]``;
- an invalid tag is REJECTED with an error naming it, never dropped. Dropping
  would turn a typo into a run that silently lacks the label it was filtered
  by later.

Events store the normalised tags as a plain ``list[str]``.
``TagSet.recorded`` rebuilds a set from one without validating again, so
tightening a rule later cannot make an already-recorded event fail to replay.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic_core import core_schema

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from pydantic import GetCoreSchemaHandler

MAX_TAGS = 32
MAX_TAG_LENGTH = 64
TAG_PATTERN = re.compile(r"^[a-z0-9._/-]+$")


class InvalidTagsError(ValueError):
    """One or more tags break the rules. The message names every one."""


def _normalise(raw: str) -> str:
    return raw.strip().lower()


def _problem(tag: str) -> str | None:
    if not tag:
        return "empty tag"
    if len(tag) > MAX_TAG_LENGTH:
        return f"{tag!r} is longer than {MAX_TAG_LENGTH} characters"
    if not TAG_PATTERN.fullmatch(tag):
        return f"{tag!r} contains characters outside [a-z0-9-_./]"
    return None


class TagSet:
    """An immutable, normalised, validated set of tags.

    Raises ``InvalidTagsError`` on construction if any tag is invalid or the
    set exceeds ``MAX_TAGS``. Accepted by Pydantic models as a list of
    strings and serialised back to one.
    """

    __slots__ = ("_values",)

    def __init__(self, raw: Iterable[str] = ()) -> None:
        if isinstance(raw, str):
            # A bare string is iterable, and would become one tag per letter.
            msg = "tags must be a list of strings, not a single string"
            raise InvalidTagsError(msg)
        normalised = {_normalise(t) for t in raw}
        problems = sorted(p for p in map(_problem, normalised) if p is not None)
        if problems:
            raise InvalidTagsError("invalid tag(s): " + "; ".join(problems))
        self._values: tuple[str, ...] = _within_limit(normalised)

    @classmethod
    def recorded(cls, values: Iterable[str]) -> TagSet:
        """Rebuild a set an event already recorded, without re-validating."""
        instance = cls.__new__(cls)
        instance._values = tuple(sorted(set(values)))
        return instance

    @property
    def values(self) -> tuple[str, ...]:
        return self._values

    def union(self, other: Iterable[str]) -> TagSet:
        """Both sets together. Raises if the result exceeds ``MAX_TAGS``."""
        return TagSet.recorded(_within_limit(set(self._values) | set(_coerce(other))))

    def difference(self, other: Iterable[str]) -> TagSet:
        """This set without ``other``'s tags."""
        drop = set(_coerce(other))
        return TagSet.recorded(t for t in self._values if t not in drop)

    def intersection(self, other: Iterable[str]) -> TagSet:
        """The tags in both sets."""
        keep = set(_coerce(other))
        return TagSet.recorded(t for t in self._values if t in keep)

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __bool__(self) -> bool:
        return bool(self._values)

    def __contains__(self, tag: object) -> bool:
        return tag in self._values

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TagSet) and self._values == other._values

    def __hash__(self) -> int:
        return hash(self._values)

    def __repr__(self) -> str:
        return f"TagSet({list(self._values)!r})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source: Any,  # noqa: ANN401 - Pydantic hook signature
        _handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        from_list = core_schema.no_info_after_validator_function(
            cls, core_schema.list_schema(core_schema.str_schema())
        )
        return core_schema.json_or_python_schema(
            json_schema=from_list,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(cls), from_list]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda tags: list(tags.values),
                return_schema=core_schema.list_schema(core_schema.str_schema()),
            ),
        )


def _within_limit(tags: set[str]) -> tuple[str, ...]:
    if len(tags) > MAX_TAGS:
        msg = f"at most {MAX_TAGS} tags are allowed, got {len(tags)}"
        raise InvalidTagsError(msg)
    return tuple(sorted(tags))


def _coerce(tags: Iterable[str]) -> TagSet:
    """An operand for a set operation, validated unless it already is a TagSet."""
    return tags if isinstance(tags, TagSet) else TagSet(tags)


def replay_tag_edit(stored: Iterable[str], edit: Iterable[str], *, added: bool) -> list[str]:
    """Apply a recorded add or remove to a read model's stored tags.

    For projections. Never re-validates or enforces the limit: the aggregate
    already did when the event was written, and replay must not fail.
    """
    current = TagSet.recorded(stored)
    if added:
        return list(TagSet.recorded([*current, *edit]))
    return list(current.difference(TagSet.recorded(edit)))
