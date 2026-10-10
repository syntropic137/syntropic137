"""Value objects owned by the Eval aggregate (evals plan, #967).

Both wrap a string and serialise as that string, so an event stores a plain
``str``. They exist so a signature can say WHICH string it wants: an
``EvalId`` cannot be passed where a ``Goal`` is expected, and each one is
validated once, where it is built, rather than at every use.

``recorded()`` rebuilds one from an event without validating again, for the
same reason as ``TagSet.recorded``: tightening a rule later must not stop an
already-written stream from replaying.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Self
from uuid import uuid4

from pydantic import ConfigDict, RootModel, StringConstraints, field_validator

#: Same alphabet as stream ids elsewhere: safe in a URL path and a stream name.
_EVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

#: A goal is a paragraph or two stating what the experiment measures.
MAX_GOAL_LENGTH = 4000


class EvalId(RootModel[str]):
    """The identity of one eval, and the id of its stream."""

    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not _EVAL_ID.fullmatch(value):
            msg = f"eval id {value!r} must be 1-128 characters from [A-Za-z0-9._:-]"
            raise ValueError(msg)
        return value

    @classmethod
    def new(cls) -> Self:
        """A fresh id, for a caller that has none to supply."""
        return cls(f"eval-{uuid4().hex}")

    @classmethod
    def recorded(cls, value: str) -> Self:
        return cls.model_construct(value)

    def __str__(self) -> str:
        return self.root


class Goal(RootModel[str]):
    """What an eval sets out to measure. Trimmed; never empty.

    Frozen with the baseline once a run is admitted: a different goal is a
    different experiment, so it is a new eval, not an edit to this one.
    """

    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def _valid(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            msg = "goal must not be empty"
            raise ValueError(msg)
        if len(trimmed) > MAX_GOAL_LENGTH:
            msg = f"goal is longer than {MAX_GOAL_LENGTH} characters"
            raise ValueError(msg)
        return trimmed

    @classmethod
    def recorded(cls, value: str) -> Self:
        return cls.model_construct(value)

    def __str__(self) -> str:
        return self.root


#: The display name. Trimmed, never empty; editable for the eval's whole life.
EvalName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Verdict(StrEnum):
    """What a scorer concluded about one run of an eval.

    ``ERROR`` is the scorer's own failure to reach a conclusion (the run left
    nothing to judge, or the scorer broke), never a judgement that the run
    failed. It counts as scored, and not as passed.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
