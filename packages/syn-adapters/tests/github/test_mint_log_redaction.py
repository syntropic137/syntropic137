"""The mint log must print permission levels and nothing else (#1429 pass 2).

Logging LEVELS rather than keys is the point: `pull_requests: read` and
`pull_requests: write` are otherwise indistinguishable in the log, and that
ambiguity cost a multi-hour investigation.

Printing values means the line renders whatever the API returned.
`parse_installation_token` copies `data["permissions"]` verbatim without
enforcing a shape, so an unexpected payload could carry a credential in either
position - and a log line is exactly where that must not surface.
"""

from __future__ import annotations

import pytest

from syn_adapters.github.client_token import _loggable_permissions

pytestmark = pytest.mark.unit


class TestOnlyRealPermissionsArePrinted:
    def test_a_normal_map_survives_intact(self) -> None:
        got = _loggable_permissions({"pull_requests": "read", "contents": "write"})
        assert got == {"contents": "write", "pull_requests": "read"}

    def test_the_level_is_what_distinguishes_them(self) -> None:
        """The whole reason this logs values rather than keys."""
        read = _loggable_permissions({"pull_requests": "read"})
        write = _loggable_permissions({"pull_requests": "write"})
        assert read != write

    @pytest.mark.parametrize(
        "bad_value",
        [
            "ghs_16C7e42F292c6912E7710c838347Ae178B4a",
            "ghp_secretlookingvalue",
            "read write",
            "",
            "READ",
        ],
    )
    def test_a_value_that_is_not_a_level_is_not_printed(self, bad_value: str) -> None:
        got = _loggable_permissions({"contents": bad_value})
        assert bad_value not in got.values()
        assert "contents" not in got
        assert got == {"<unprintable>": "1"}

    @pytest.mark.parametrize(
        "bad_name",
        [
            "ghs_16C7e42F292c6912E7710c838347Ae178B4a",
            "Authorization",
            "token value",
            "x" * 200,
        ],
    )
    def test_a_key_that_is_not_a_permission_name_is_not_printed(self, bad_name: str) -> None:
        got = _loggable_permissions({bad_name: "read"})
        assert bad_name not in got
        assert got == {"<unprintable>": "1"}

    def test_rejections_are_counted_not_silently_dropped(self) -> None:
        """A map that does not look like one is worth knowing about."""
        got = _loggable_permissions(
            {"contents": "write", "Authorization": "Bearer abc", "x": "not-a-level"}
        )
        assert got["contents"] == "write"
        assert got["<unprintable>"] == "2"
        assert "Authorization" not in got
        assert "Bearer abc" not in got.values()

    def test_an_empty_map_prints_empty(self) -> None:
        assert _loggable_permissions({}) == {}
