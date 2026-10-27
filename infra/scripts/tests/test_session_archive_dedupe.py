"""``just session-archive-dedupe`` passes only known flags to the VPS (#2107)."""

from __future__ import annotations

import pytest

from infra.scripts import session_archive_compress, session_archive_dedupe

pytestmark = pytest.mark.unit


def test_the_command_execs_the_dedupe_module() -> None:
    argv = session_archive_dedupe.command("root@host", ["--apply", "--budget-minutes", "5"])
    assert argv == [
        *["ssh", "-o", "ServerAliveInterval=20", "root@host", "docker", "exec", "syn137-api"],
        *["python", "-m", "syn_api.session_archive_dedupe", "--apply", "--budget-minutes", "5"],
    ]


def test_no_flags_is_a_dry_run() -> None:
    assert session_archive_dedupe.command("h", [])[-1] == "syn_api.session_archive_dedupe"


@pytest.mark.parametrize("flags", [["--force"], ["--apply; reboot"], ["--budget-minutes", "0"]])
def test_anything_else_is_refused(flags: list[str]) -> None:
    with pytest.raises(session_archive_compress.UsageError):
        session_archive_dedupe.command("h", flags)


def test_usage_errors_name_this_tool(capsys: pytest.CaptureFixture[str]) -> None:
    assert session_archive_dedupe.main(["--force"]) == 2
    assert capsys.readouterr().err.startswith("session-archive-dedupe: unknown flag")
