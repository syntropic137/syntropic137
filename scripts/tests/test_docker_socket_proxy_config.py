"""The docker-socket-proxy haproxy template is generated, and fails loudly on drift (#1806)."""

from __future__ import annotations

import pytest
from scripts.docker_socket_proxy_config import (
    CAPTURE_VOLUME_ALLOW,
    DEFAULT_BACKEND_ANCHOR,
    FINAL_DENY_ANCHOR,
    FRONTEND_ANCHOR,
    GUARD_BACKEND,
    GUARD_ROUTES,
    HEADER,
    IMAGE_NAMING_DENIES,
    OUTPUT_FILE,
    UPSTREAM_TEMPLATE,
    TemplateAnchorError,
    generate,
    main,
    patch,
)

pytestmark = pytest.mark.unit

_INSERTED = (*IMAGE_NAMING_DENIES, CAPTURE_VOLUME_ALLOW, *GUARD_ROUTES, *GUARD_BACKEND)


def _lines() -> list[str]:
    return generate().splitlines()


def test_every_inserted_rule_appears_exactly_once() -> None:
    lines = _lines()
    for rule in _INSERTED:
        assert lines.count(rule) == 1, rule


def test_upstream_lines_survive_in_order() -> None:
    """The patch only inserts; it never drops or reorders an upstream line."""
    body = generate().removeprefix(HEADER).splitlines()
    assert [line for line in body if line not in _INSERTED] == (
        UPSTREAM_TEMPLATE.read_text().splitlines()
    )


def test_image_naming_denies_precede_every_upstream_allow() -> None:
    lines = _lines()
    frontend = lines.index(FRONTEND_ANCHOR)
    denies = [lines.index(rule) for rule in IMAGE_NAMING_DENIES]
    assert denies == list(range(frontend + 1, frontend + 1 + len(denies)))
    first_allow = next(i for i, line in enumerate(lines) if "http-request allow" in line)
    assert max(denies) < first_allow


def test_capture_allow_sits_directly_before_the_final_deny() -> None:
    lines = _lines()
    assert lines[lines.index(FINAL_DENY_ANCHOR) - 1] == CAPTURE_VOLUME_ALLOW


def test_guard_routes_follow_default_backend_in_the_frontend() -> None:
    lines = _lines()
    backend = lines.index(DEFAULT_BACKEND_ANCHOR)
    assert lines[backend + 1 : backend + 1 + len(GUARD_ROUTES)] == list(GUARD_ROUTES)
    assert lines.index(GUARD_BACKEND[0]) > max(lines.index(r) for r in GUARD_ROUTES)


def test_image_templating_placeholders_are_left_for_the_entrypoint() -> None:
    """The image's entrypoint substitutes ${BIND_CONFIG}; haproxy expands the rest."""
    text = generate()
    assert "    bind ${BIND_CONFIG}" in text
    assert "$SOCKET_PATH" in text


@pytest.mark.parametrize(
    "anchor", [FRONTEND_ANCHOR, FINAL_DENY_ANCHOR, DEFAULT_BACKEND_ANCHOR], ids=str.strip
)
def test_a_missing_anchor_fails_loudly(anchor: str) -> None:
    upstream = UPSTREAM_TEMPLATE.read_text().replace(anchor + "\n", "")
    with pytest.raises(TemplateAnchorError, match="exactly one"):
        patch(upstream)


@pytest.mark.parametrize(
    "anchor", [FRONTEND_ANCHOR, FINAL_DENY_ANCHOR, DEFAULT_BACKEND_ANCHOR], ids=str.strip
)
def test_a_duplicated_anchor_fails_loudly(anchor: str) -> None:
    upstream = UPSTREAM_TEMPLATE.read_text() + anchor + "\n"
    with pytest.raises(TemplateAnchorError, match="exactly one"):
        patch(upstream)


def test_reordered_anchors_fail_loudly() -> None:
    upstream = UPSTREAM_TEMPLATE.read_text()
    swapped = (
        upstream.replace(FINAL_DENY_ANCHOR + "\n", "@@DENY@@\n")
        .replace(DEFAULT_BACKEND_ANCHOR + "\n", FINAL_DENY_ANCHOR + "\n")
        .replace("@@DENY@@\n", DEFAULT_BACKEND_ANCHOR + "\n")
    )
    with pytest.raises(TemplateAnchorError, match="then"):
        patch(swapped)


def test_an_upstream_that_already_has_a_rule_fails_loudly() -> None:
    """Patching our own output (or an upstream that adopted a rule) must not stack rules."""
    with pytest.raises(TemplateAnchorError):
        patch(generate())


def test_committed_file_is_current() -> None:
    assert OUTPUT_FILE.read_text() == generate()
    assert main(["--check"]) == 0
