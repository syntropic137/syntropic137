"""Unit tests for the setup-template currency check (#1863).

Offline: these drive the parse and compare halves with small compose snippets.
The digests are made up (one repeated hex character), not copied from a release.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from scripts import check_setup_template_current as check
from scripts.check_setup_template_current import (
    COMPOSE_ASSET,
    EXIT_ERROR,
    EXIT_OK,
    TARBALL_TEMPLATE,
    FetchError,
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


def test_digest_is_not_silently_truncated() -> None:
    with pytest.raises(TemplateParseError, match="malformed image pin"):
        parse_template(_compose(api="sha256:" + "a" * 65), "setup")


def test_malformed_pin_beside_a_valid_one_is_a_parse_error() -> None:
    bad = "  gateway:\n    image: ghcr.io/syntropic137/syn-gateway@sha256:bad\n"

    with pytest.raises(TemplateParseError, match="syn-gateway@sha256:bad"):
        parse_template(_compose(extra=bad), "setup")


def test_quoted_suffix_after_a_valid_pin_is_a_parse_error() -> None:
    bad = f'  gateway:\n    image: "ghcr.io/syntropic137/syn-gateway@{_C}}}bad"\n'

    with pytest.raises(TemplateParseError, match="malformed image pin"):
        parse_template(_compose(extra=bad), "setup")


def test_pin_in_a_trailing_comment_is_a_parse_error() -> None:
    commented = f"    # ghcr.io/syntropic137/syn-gateway@sha256:{'a' * 65}"
    text = _compose().replace(f"syn-collector@{_B}", f"syn-collector@{_B}{commented}")

    with pytest.raises(TemplateParseError, match="not a whole image value"):
        parse_template(text, "setup")


def test_pin_in_a_flow_mapping_is_read() -> None:
    flow = f"  gateway: {{image: ghcr.io/syntropic137/syn-gateway@{_C}}}\n"

    assert parse_template(_compose(extra=flow), "setup").images["syn-gateway"] == _C


# --- main: the fetch boundary, with only the external commands replaced --------


def _fake_commands(
    monkeypatch: pytest.MonkeyPatch,
    release_text: str | None,
    member: bytes,
    latest: str = "v1.2.3",
) -> None:
    """``gh`` writes ``release_text`` as the asset (none if None); ``npm`` packs ``member``."""

    def run(command: list[str], cwd: Path, env: object = None) -> str:
        if command[:3] == ["gh", "release", "view"]:
            return latest + "\n"
        if command[0] == "gh":
            if release_text is not None:
                dest = Path(command[command.index("--dir") + 1])
                (dest / COMPOSE_ASSET).write_text(release_text, encoding="utf-8")
            return ""
        dest = Path(command[command.index("--pack-destination") + 1])
        with tarfile.open(dest / "setup.tgz", "w:gz") as archive:
            info = tarfile.TarInfo(TARBALL_TEMPLATE)
            info.size = len(member)
            archive.addfile(info, io.BytesIO(member))
        return json.dumps([{"version": "1.0.0", "filename": "setup.tgz"}])

    monkeypatch.setattr(check, "_run", run)


def test_main_matching_templates_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_commands(monkeypatch, _compose(), _compose().encode())

    assert check.main(["--release", "v1.2.3"]) == EXIT_OK


@pytest.mark.parametrize("argv", [["--release", "v9.9.9"], []], ids=["explicit", "latest"])
def test_requested_release_is_validated_against_asset_header(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    # Both artifacts agree on v1.2.3; neither is the release that was asked for.
    _fake_commands(monkeypatch, _compose(), _compose().encode(), latest="v9.9.9")

    assert check.main(argv) == EXIT_ERROR
    assert "header pins v1.2.3, not v9.9.9" in capsys.readouterr().err


def test_bad_template_encoding_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_commands(monkeypatch, _compose(), b"\xff")

    assert check.main(["--release", "v1.2.3"]) == EXIT_ERROR
    assert f"no readable {TARBALL_TEMPLATE}" in capsys.readouterr().err


def test_missing_downloaded_asset_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_commands(monkeypatch, None, _compose().encode())

    assert check.main(["--release", "v1.2.3"]) == EXIT_ERROR
    assert f"no readable {COMPOSE_ASSET}" in capsys.readouterr().err


def test_command_that_cannot_start_is_a_fetch_error(tmp_path: Path) -> None:
    # A directory is not executable: PermissionError, an OSError that is not
    # FileNotFoundError.
    with pytest.raises(FetchError, match="could not run"):
        check._run([str(tmp_path)], tmp_path)


def test_main_rejects_a_quoted_suffix_in_the_setup_template(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = _compose().replace(f'syn-api@{_A}"', f'syn-api@{_A}}}bad"')
    _fake_commands(monkeypatch, _compose(), found.encode())

    assert check.main(["--release", "v1.2.3"]) == EXIT_ERROR
    assert "malformed image pin" in capsys.readouterr().err
