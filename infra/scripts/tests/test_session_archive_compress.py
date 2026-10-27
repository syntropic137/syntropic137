"""``just session-archive-compress`` passes only known flags to the VPS (#2107)."""

from __future__ import annotations

import pytest

from infra.scripts import session_archive_compress

pytestmark = pytest.mark.unit


def test_the_command_execs_the_module_as_the_api_user() -> None:
    argv = session_archive_compress.command("root@host", ["--apply", "--budget-minutes", "5"])
    assert argv == [
        "ssh",
        "-o",
        "ServerAliveInterval=20",
        "root@host",
        "docker",
        "exec",
        "syn137-api",
        "python",
        "-m",
        "syn_api.session_archive_compress",
        "--apply",
        "--budget-minutes",
        "5",
    ]


def test_no_flags_is_a_dry_run() -> None:
    assert session_archive_compress.command("h", [])[-1] == "syn_api.session_archive_compress"


@pytest.mark.parametrize(
    "flags",
    [
        ["--force"],
        ["--apply; reboot"],
        ["--budget-minutes"],
        ["--budget-minutes", "0"],
        ["--budget-minutes", "$(reboot)"],
    ],
)
def test_anything_else_is_refused(flags: list[str]) -> None:
    with pytest.raises(session_archive_compress.UsageError):
        session_archive_compress.command("h", flags)
