"""Covers only the LOWER bound of clamp, on purpose: one patch dies, one lives."""

from __future__ import annotations

import pytest
from scripts.mutation_probe import clamp

pytestmark = pytest.mark.unit


def test_clamp_raises_values_below_low() -> None:
    assert clamp(-5, 0, 10) == 0
    assert clamp(5, 0, 10) == 5
