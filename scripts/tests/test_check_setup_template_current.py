"""Unit tests for the setup-template currency check (#1863).

Offline: these drive the parse and compare halves with small compose snippets.
The digests are made up (one repeated hex character), not copied from a release.
"""

from __future__ import annotations

import pytest
from scripts.check_setup_template_current import (
    Mismatch,
    TemplateParseError,
    compare,
    format_mismatches,
    parse_template,
)

pytestmark = pytest.mark.unit

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64
_M = "sha256:" + "d" * 64


def _compose(
    release: str = "v1.2.3",
    api: str | None = _A,
    collector: str | None = _B,
    extra: str = "",
) -> str:
    services = [
        f"# Pinned to release {release} — image digests verified by cosign",
        "# Syntropic137 self-host compose",
        "services:",
        "  minio:",
        f"    image: ghcr.io/syntropic137/minio:RELEASE.2025-04-22T22-12-26Z@{_M}",
        "  db:",
        "    image: timescale/timescaledb:2.17.2-pg16",
    ]
    if api is not None:
        services += [
            "  api:",
            f"    image: ghcr.io/syntropic137/syn-api@{api}",
            "  executor:",
            f'    image: "ghcr.io/syntropic137/syn-api@{api}"',
        ]
    if collector is not None:
        services += ["  collector:", f"    image: ghcr.io/syntropic137/syn-collector@{collector}"]
    return "\n".join(services) + "\n" + extra


def _diff(expected: str, found: str) -> list[Mismatch]:
    return compare(parse_template(expected, "release"), parse_template(found, "setup"))


def test_equal_templates_match() -> None:
    assert _diff(_compose(), _compose()) == []


def test_parse_reads_header_and_every_pinned_image() -> None:
    template = parse_template(_compose(), "release")

    assert template.release == "v1.2.3"
    assert dict(template.images) == {
        "minio": f"RELEASE.2025-04-22T22-12-26Z@{_M}",
        "syn-api": _A,
        "syn-collector": _B,
    }


def test_release_header_difference_is_a_mismatch() -> None:
    assert _diff(_compose(), _compose(release="v1.2.2")) == [
        Mismatch("release header", "v1.2.3", "v1.2.2")
    ]


def test_one_digest_difference_names_that_image() -> None:
    assert _diff(_compose(), _compose(collector=_C)) == [Mismatch("syn-collector", _B, _C)]


def test_tag_on_a_pinned_ref_is_compared() -> None:
    found = _compose().replace("RELEASE.2025-04-22T22-12-26Z@", "RELEASE.2024-01-01T00-00-00Z@")

    assert _diff(_compose(), found) == [
        Mismatch(
            "minio", f"RELEASE.2025-04-22T22-12-26Z@{_M}", f"RELEASE.2024-01-01T00-00-00Z@{_M}"
        )
    ]


def test_image_missing_from_the_setup_template_is_a_mismatch() -> None:
    assert _diff(_compose(), _compose(collector=None)) == [Mismatch("syn-collector", _B, None)]


def test_image_only_in_the_setup_template_is_a_mismatch() -> None:
    assert _diff(_compose(collector=None), _compose()) == [Mismatch("syn-collector", None, _B)]


def test_non_syntropic137_images_are_ignored() -> None:
    other = "  redis:\n    image: docker.io/library/redis@" + _C + "\n"

    assert _diff(_compose(), _compose(extra=other)) == []
    assert "redis" not in parse_template(_compose(extra=other), "setup").images


def test_refs_in_comments_are_not_pins() -> None:
    comment = f"# was ghcr.io/syntropic137/syn-gateway@{_C}\n"

    assert "syn-gateway" not in parse_template(_compose(extra=comment), "setup").images


@pytest.mark.parametrize(
    "header",
    [
        "# Pinned to release 1.2.3",
        "# Pinned to release v1.2",
        "# Pinned to release",
        "# Pinned to release vX.Y.Z",
    ],
)
def test_malformed_header_is_a_parse_error(header: str) -> None:
    text = _compose().replace(
        "# Pinned to release v1.2.3 — image digests verified by cosign", header
    )

    with pytest.raises(TemplateParseError, match="malformed release header"):
        parse_template(text, "setup")


def test_missing_header_is_a_parse_error() -> None:
    with pytest.raises(TemplateParseError, match="found 0"):
        parse_template(_compose().split("\n", 1)[1], "setup")


def test_two_digests_for_one_image_is_a_parse_error() -> None:
    clash = f"  docker-create-guard:\n    image: ghcr.io/syntropic137/syn-api@{_C}\n"

    with pytest.raises(TemplateParseError, match="pinned twice"):
        parse_template(_compose(extra=clash), "setup")


def test_template_with_no_pins_is_a_parse_error() -> None:
    unpinned = "# Pinned to release v1.2.3\nservices:\n  api:\n    image: ghcr.io/syntropic137/syn-api:v1.2.3\n"

    with pytest.raises(TemplateParseError, match=r"no ghcr\.io/syntropic137"):
        parse_template(unpinned, "setup")


def test_table_shows_expected_and_found_per_image() -> None:
    table = format_mismatches([Mismatch("syn-api", _A, _B), Mismatch("syn-collector", _B, None)])

    assert "EXPECTED (release)" in table
    assert f"syn-api        {_A}  {_B}" in table
    assert "syn-collector" in table and "(missing)" in table
