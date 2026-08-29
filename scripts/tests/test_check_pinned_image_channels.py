"""Unit tests for the pinned-image channel gate.

The registry-touching parts need a network; the label parsing and the verdict
logic do not, and those are where a silent pass would hide. Extracted as pure
functions for exactly that reason -- an inline heredoc in the justfile could not
be tested, which is the documented lesson from the marker gate.
"""

from __future__ import annotations

import pytest

from scripts.check_pinned_image_channels import (
    CHANNEL_LABEL,
    REVISION_LABEL,
    ImageChannel,
    find_label,
)

pytestmark = pytest.mark.unit


def _config(**labels: str) -> dict[str, object]:
    """An image config with labels nested the way buildx reports them."""
    return {"config": {"Labels": dict(labels)}}


class TestFindLabel:
    def test_finds_a_label_nested_under_config(self) -> None:
        cfg = _config(**{CHANNEL_LABEL: "release"})
        assert find_label(cfg, CHANNEL_LABEL) == "release"

    def test_finds_a_label_nested_arbitrarily_deep(self) -> None:
        """Buildx nests differently across manifest shapes, so it walks."""
        cfg = {"manifests": [{"platform": {}, "image": _config(**{CHANNEL_LABEL: "edge"})}]}
        assert find_label(cfg, CHANNEL_LABEL) == "edge"

    def test_missing_label_returns_none_not_a_crash(self) -> None:
        """A KeyError here would read as 'no label' and pass the gate."""
        assert find_label(_config(other="x"), CHANNEL_LABEL) is None

    def test_revision_and_channel_are_read_independently(self) -> None:
        cfg = _config(**{CHANNEL_LABEL: "release", REVISION_LABEL: "276eec0"})
        assert find_label(cfg, CHANNEL_LABEL) == "release"
        assert find_label(cfg, REVISION_LABEL) == "276eec0"

    def test_a_non_string_label_is_ignored(self) -> None:
        assert find_label(_config(), CHANNEL_LABEL) is None
        assert find_label({"config": {"Labels": {CHANNEL_LABEL: 7}}}, CHANNEL_LABEL) is None


class TestVerdict:
    def test_release_is_ok(self) -> None:
        assert ImageChannel("OMNI", "ref", "release", "276eec0").ok

    @pytest.mark.parametrize("channel", ["edge", "main", "", None])
    def test_anything_else_is_not_ok(self, channel: str | None) -> None:
        """The real incident pinned an image whose own label said 'edge'."""
        assert not ImageChannel("OMNI", "ref", channel, "673397e").ok

    def test_a_missing_channel_does_not_pass(self) -> None:
        """An unlabelled image must not be treated as approved."""
        assert not ImageChannel("OMNI", "ref", None, None).ok
