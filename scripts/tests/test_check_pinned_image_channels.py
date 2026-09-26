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

from syn_shared.settings.workspace_images import (
    WorkspaceImageProvider,
    workspace_image_name,
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
    """A pin that is correct in every respect EXCEPT what the caller varies.

    `repository` and `expected_repository` agree here on purpose. They are not
    optional: an ImageChannel carrying neither means "the publisher check could
    not run", which now fails closed. A helper that left them empty would make
    every test in this file exercise that path instead of the invariant it
    names.
    """
    # Several tests use synthetic provider names ("A", "B") to exercise the
    # multi-pin invariants, and those are not enum members. Fall back to a
    # derived name so the helper stays usable for them: what matters here is
    # that repository and expected_repository AGREE, not which string they are.
    try:
        repository = workspace_image_name(WorkspaceImageProvider[provider])
    except KeyError:
        repository = f"agentic-workspace-{provider.lower()}"
    return ImageChannel(
        provider,
        f"ghcr.io/agentparadise/{repository}@sha256:deadbeef",
        channel,
        revision,
        repository=repository,
        expected_repository=repository,
    )


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


# ---------------------------------------------------------------------------
# The repository invariant (codex review of the publisher cutover)
# ---------------------------------------------------------------------------
#
# The channel and revision checks say an image was built from the right source
# on the right branch. NEITHER says it came from the right REPOSITORY. During
# the cutover four repositories exist and all resolve:
#
#   agentic-workspace-claude       agentic-workspace-claude-cli
#   agentic-workspace-omni-agent   omni-agent-workspace
#
# A same-commit build in the agentic-primitives pair carries channel=release
# and a matching revision, and passes cosign, because the identity constraint
# deliberately admits both publishers during the cutover. Every other control
# says yes. Only the repository distinguishes them.

_REV = "c5e34284bc28582152af85fdf6bf9f16b3db542c"


def _repo_pin(provider: str, repository: str, expected: str, **kw: object) -> ImageChannel:
    return ImageChannel(
        provider,
        f"ghcr.io/agentparadise/{repository}@sha256:" + "0" * 64,
        kw.get("channel", "release"),  # type: ignore[arg-type]
        kw.get("revision", _REV),  # type: ignore[arg-type]
        repository=repository,
        expected_repository=expected,
    )


@pytest.mark.unit
class TestTheRepositoryInvariant:
    def test_correct_repositories_pass(self) -> None:
        code, _ = evaluate(
            [
                _repo_pin("CLAUDE_CLI", "agentic-workspace-claude", "agentic-workspace-claude"),
                _repo_pin(
                    "OMNI_AGENT",
                    "agentic-workspace-omni-agent",
                    "agentic-workspace-omni-agent",
                ),
            ],
            _REV,
        )
        assert code == 0

    def test_the_other_publishers_repository_is_rejected(self) -> None:
        """Release channel, matching revision, wrong repository. Must fail."""
        code, lines = evaluate(
            [
                _repo_pin("CLAUDE_CLI", "agentic-workspace-claude", "agentic-workspace-claude"),
                _repo_pin(
                    "OMNI_AGENT",
                    "omni-agent-workspace",  # the agentic-primitives name
                    "agentic-workspace-omni-agent",
                ),
            ],
            _REV,
        )
        assert code == 1, (
            "a same-revision, release-channel digest from the OTHER publisher passed; "
            "it would also pass cosign while the cutover admits both identities"
        )
        assert any("omni-agent-workspace" in line for line in lines)
        assert any("expected" in line for line in lines)

    def test_the_old_claude_repository_is_rejected_too(self) -> None:
        code, _ = evaluate(
            [
                _repo_pin(
                    "CLAUDE_CLI",
                    "agentic-workspace-claude-cli",  # the agentic-primitives name
                    "agentic-workspace-claude",
                ),
            ],
            _REV,
        )
        assert code == 1

    def test_it_fires_before_the_channel_check(self) -> None:
        """A wrong repository is reported as such, not as a channel problem.

        Both are failures, but a reader told "not release channel" goes and
        looks at the build, while the actual fault is the pin naming another
        publisher's repository.
        """
        code, lines = evaluate(
            [
                _repo_pin(
                    "OMNI_AGENT",
                    "omni-agent-workspace",
                    "agentic-workspace-omni-agent",
                    channel="edge",
                ),
            ],
            _REV,
        )
        assert code == 1
        assert any("does not push to" in line for line in lines)

    def test_an_unparsed_repository_does_not_silently_pass(self) -> None:
        """Empty `repository` skips the check, so assert the skip is narrow.

        The guard is `if r.repository`, so an unparsed reference cannot fail
        this invariant. That is deliberate - it would otherwise fail every pin
        on a parsing bug - but it means the OTHER invariants must still run.
        """
        code, _ = evaluate(
            [
                ImageChannel(
                    "OMNI_AGENT",
                    "not-a-ref",
                    "edge",
                    _REV,
                    repository="",
                    expected_repository="agentic-workspace-omni-agent",
                )
            ],
            _REV,
        )
        assert code == 1, "channel check must still catch it when repository is unparsed"


@pytest.mark.unit
class TestAnUnreadableRepositoryFailsClosed:
    """An empty repository must not skip the publisher check.

    Found by a codex review. The first version of the invariant guarded on
    `if r.repository`, so an empty string skipped the comparison and a
    release-channel pin with a matching revision passed. `inspect_channel`
    always parses a non-empty string today, so there is no bypass through
    `main()` - but a gate written to catch a silent pass must not contain one.
    """

    def test_empty_repository_is_rejected_even_when_everything_else_is_right(self) -> None:
        code, lines = evaluate(
            [
                ImageChannel(
                    "OMNI_AGENT",
                    "ghcr.io/agentparadise/agentic-workspace-omni-agent@sha256:" + "0" * 64,
                    "release",
                    _REV,
                    repository="",
                    expected_repository="agentic-workspace-omni-agent",
                )
            ],
            _REV,
        )
        assert code == 1, (
            "a release-channel pin at the right revision passed with an unreadable "
            "repository, so the publisher check silently did not run"
        )
        assert any("could not run" in line for line in lines)

    def test_empty_expected_repository_is_rejected_too(self) -> None:
        code, _ = evaluate(
            [
                ImageChannel(
                    "OMNI_AGENT",
                    "ghcr.io/agentparadise/agentic-workspace-omni-agent@sha256:" + "0" * 64,
                    "release",
                    _REV,
                    repository="agentic-workspace-omni-agent",
                    expected_repository="",
                )
            ],
            _REV,
        )
        assert code == 1
