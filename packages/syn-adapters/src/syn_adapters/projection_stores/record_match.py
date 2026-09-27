"""What "the store still holds this record" means, for every store's `save_if`.

One definition, because the stores must agree with each other and with the
caller: the caller decided over a stored row it read as a model, so the store
compares the row it is about to overwrite the same way. Comparing serialised
JSON instead would make a row that round-trips with any difference - a default
filled in, a timestamp spelled another way - never match, and a caller that
decides again after losing would never stop losing.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError


def holds(stored: object, expected: BaseModel) -> bool:
    """Whether ``stored``, read as ``type(expected)``, is ``expected``.

    A row that cannot be read as that model holds nothing the caller expected.
    """
    try:
        return type(expected).model_validate(stored) == expected
    except ValidationError:
        return False
