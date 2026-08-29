"""Unit tests for the pinned-image channel gate.

A codex review found the FIRST version of this file tested nothing that
mattered: all 15 cases exercised a helper, so deleting invariant 2 or 3 outright
left every one of them green. A gate against silent passes had a silent pass in
its own suite. These drive `evaluate()` - the actual verdict - and parse a real
captured `docker buildx imagetools inspect` document rather than a hand-written
approximation of one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.check_pinned_image_channels import (
    CHANNEL_LABEL,
    REVISION_LABEL,
    SUBMODULE_PATH,
    ImageChannel,
    MultiPlatformDisagreement,
    agreed_label,
    evaluate,
    platform_labels,
    submodule_gitlink,
)

pytestmark = pytest.mark.unit

#: Captured from the real CLAUDE_CLI pin, so the shape is the registry's and
#: not my recollection of it.
_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "imagetools_claude_cli.json").read_text()
)
GITLINK = "276eec0ac2315d32b83fb86fc4997cbaf1d87a52"


def _pin(
    provider: str = "OMNI_AGENT", channel: str | None = "release", revision: str | None = GITLINK
) -> ImageChannel:
    return ImageChannel(provider, f"ghcr.io/x/{provider}@sha256:deadbeef", channel, revision)


class TestTheRealRegistryDocument:
    def test_it_is_keyed_by_platform(self) -> None:
        """The document is `{platform: {...}}`, which is why a single-value
        lookup could read one arbitrary architecture."""
        assert set(platform_labels(_FIXTURE)) == {"linux/amd64", "linux/arm64"}

    def test_both_platforms_carry_the_labels_the_gate_reads(self) -> None:
        for labels in platform_labels(_FIXTURE).values():
            assert labels[CHANNEL_LABEL] == "release"
            assert labels[REVISION_LABEL] == GITLINK

    def test_agreement_yields_the_single_value(self) -> None:
        assert agreed_label(platform_labels(_FIXTURE), CHANNEL_LABEL) == "release"

    def test_an_unrecognised_document_raises_rather_than_reading_as_unlabelled(self) -> None:
        for bad in ([], "", {}, None):
            with pytest.raises(RuntimeError):
                platform_labels(bad)


class TestMultiArchDisagreement:
    """The High finding: one arch release, the other edge, and the gate passed."""

    def test_a_platform_on_a_different_channel_is_not_silently_ignored(self) -> None:
        mixed = json.loads(json.dumps(_FIXTURE))
        mixed["linux/arm64"]["config"]["Labels"][CHANNEL_LABEL] = "edge"
        with pytest.raises(MultiPlatformDisagreement, match="linux/arm64=edge"):
            agreed_label(platform_labels(mixed), CHANNEL_LABEL)

    def test_a_platform_from_a_different_revision_is_not_silently_ignored(self) -> None:
        mixed = json.loads(json.dumps(_FIXTURE))
        mixed["linux/amd64"]["config"]["Labels"][REVISION_LABEL] = "0" * 40
        with pytest.raises(MultiPlatformDisagreement):
            agreed_label(platform_labels(mixed), REVISION_LABEL)

    def test_a_platform_missing_the_label_entirely_disagrees(self) -> None:
        """Absent on one arch is a disagreement, not a shared value."""
        mixed = json.loads(json.dumps(_FIXTURE))
        del mixed["linux/arm64"]["config"]["Labels"][CHANNEL_LABEL]
        with pytest.raises(MultiPlatformDisagreement):
            agreed_label(platform_labels(mixed), CHANNEL_LABEL)


class TestInvariantOneReleaseChannel:
    def test_release_pins_pass(self) -> None:
        code, _ = evaluate([_pin("A"), _pin("B")], GITLINK)
        assert code == 0

    @pytest.mark.parametrize("channel", ["edge", "main", "", None])
    def test_any_other_channel_fails(self, channel: str | None) -> None:
        """The real incident: OMNI_AGENT was pinned to a channel=edge image."""
        code, lines = evaluate([_pin("A"), _pin("B", channel=channel)], GITLINK)
        assert code == 1
        assert any("release" in line for line in lines)


class TestInvariantTwoOneSourceRevision:
    def test_pins_from_different_revisions_fail(self) -> None:
        """CLAUDE_CLI was channel=release and STALE - this is the only
        invariant that catches it."""
        code, lines = evaluate([_pin("A"), _pin("B", revision="0" * 40)], GITLINK)
        assert code == 1
        assert any("stale" in line for line in lines)


class TestInvariantThreeMatchesTheGitlink:
    def test_pins_that_disagree_with_the_submodule_fail(self) -> None:
        """Invariants 1 and 2 are satisfied by any self-consistent set,
        INCLUDING one that agrees with itself and disagrees with lib/."""
        other = "1" * 40
        code, lines = evaluate([_pin("A", revision=other), _pin("B", revision=other)], GITLINK)
        assert code == 1
        assert any(SUBMODULE_PATH in line for line in lines)

    def test_the_matching_case_passes(self) -> None:
        code, _ = evaluate([_pin("A"), _pin("B")], GITLINK)
        assert code == 0


class TestSubmoduleGitlink:
    def test_the_real_gitlink_is_a_full_sha(self) -> None:
        got = submodule_gitlink()
        assert len(got) == 40, got
        assert all(c in "0123456789abcdef" for c in got), got

    def test_a_regular_file_is_not_a_gitlink(self) -> None:
        """`git ls-tree` returns a blob line happily; parsing it as a commit
        would compare the image revision against a file hash."""
        with pytest.raises(RuntimeError, match="not a submodule gitlink"):
            submodule_gitlink("justfile")

    def test_a_path_that_does_not_exist_raises(self) -> None:
        """Empty stdout must fail closed, not read as 'no mismatch'."""
        with pytest.raises(RuntimeError, match="could not read the gitlink"):
            submodule_gitlink("no/such/path")
