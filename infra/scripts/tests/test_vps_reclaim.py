"""``just vps-reclaim`` passes only known flags into a root shell on the VPS (#1983)."""

from __future__ import annotations

import pytest

from infra.scripts import vps_reclaim

pytestmark = pytest.mark.unit


def test_the_command_execs_the_module_as_root_in_the_api_container() -> None:
    argv = vps_reclaim.command("root@host", ["--apply", "--budget-minutes", "5"])
    assert argv[:5] == ["ssh", "-o", "ServerAliveInterval=20", "root@host", "docker"]
    assert argv[5:] == [
        "exec",
        "-u",
        "0",
        "syn137-api",
        "python",
        "-m",
        "syn_api.vps_reclaim",
        "--apply",
        "--budget-minutes",
        "5",
    ]


def test_no_flags_is_a_dry_run() -> None:
    assert vps_reclaim.command("h", [])[-3:] == ["python", "-m", "syn_api.vps_reclaim"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--force"],
        ["--apply; rm -rf /"],
        ["--budget-minutes"],
        ["--budget-minutes", "0"],
        ["--budget-minutes", "$(reboot)"],
        ["--lift-maintenance"],
    ],
)
def test_anything_else_is_refused(flags: list[str]) -> None:
    with pytest.raises(vps_reclaim.UsageError):
        vps_reclaim.command("h", flags)


def test_main_refuses_without_running_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(vps_reclaim.subprocess, "run", lambda argv, **_kw: ran.append(argv))
    assert vps_reclaim.main(["--nope"]) == 2
    assert ran == []
    assert "unknown flag" in capsys.readouterr().err
