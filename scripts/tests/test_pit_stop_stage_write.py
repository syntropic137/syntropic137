"""The stage step must never install a partial compose file on the host.

Staging writes the repointed compose to a side file beside the deployed one,
and the swap moves it over the deployed one (#1511). Before #1511 staging wrote
over the deployed file, so a routine `compose up` started an unstaged build. `cat` exits 0
when its input ends early, so a transfer cut short used to be renamed over the
deployed file before anything compared it, and the script then aborted with
half a compose in place (verification of #1538).

These run the stage block exactly as it is written in pit_stop.sh, against a
local directory standing in for the host and a `remote` stub that runs each
command with bash instead of ssh. One stub hands the write its whole input,
the other only the first 100 bytes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "pit_stop.sh"
_FIXTURES = Path(__file__).parent / "fixtures" / "pit_stop"
_COMPOSE = "docker-compose.syntropic137.yaml"
_STAGED = f"{_COMPOSE}.pit-stop-staged"
_TAG = "v0.33.2-beta.1"

_START = (
    'step "stage: repoint $REPOINTS into $STAGED (the live compose is untouched until the swap)"'
)
_END = 'if [ "$MODE" = "stage" ]; then'

_FULL = 'remote() { bash -c "$*"; }'
_SHORT = 'remote() { head -c 100 | bash -c "$*"; }'


def _stage_block() -> str:
    lines = _SCRIPT.read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if _START in line]
    ends = [i for i, line in enumerate(lines) if line.strip() == _END]
    assert len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0], (
        f"could not find the stage block in {_SCRIPT.name} between {_START!r} and {_END!r}; "
        f"if it moved, this test is no longer running it"
    )
    return "\n".join(lines[starts[0] : ends[0]])


def _apply_staged() -> str:
    """`apply_staged` as the script defines it."""
    text = _SCRIPT.read_text()
    start = text.index("apply_staged() {")
    return text[start : text.index("\n}\n", start) + 3]


def _refuse_drift() -> str:
    """`refuse_drift` as the script defines it."""
    text = _SCRIPT.read_text()
    start = text.index("refuse_drift() {")
    return text[start : text.index("\n}\n", start) + 3]


def _function(name: str) -> str:
    """The top-level shell function `name` as the script defines it."""
    text = _SCRIPT.read_text()
    start = text.index(f"\n{name}() {{") + 1
    return text[start : text.index("\n}\n", start) + 3]


def _counters() -> str:
    """`pins_on_tag` and `images_on_tag` as the script defines them."""
    text = _SCRIPT.read_text()
    start = text.index("pins_on_tag() {")
    end = text.index("\n}\n", text.index("images_on_tag() {", start)) + 3
    return text[start:end]


def _run_stage(
    fixture: str,
    host: Path,
    tmp: Path,
    stub: str,
    service: str = "all",
    compose: str | None = None,
    apply: bool = False,
    published: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the stage block, or with `apply` the swap's `apply_staged`, against
    `host`. `fixture`/`compose` is written as the live compose unless both are
    empty, which leaves the host exactly as a previous call left it.

    `published` is the fixture the precheck read as $REF's compose; by default
    the live compose itself, so the stage sees no drift."""
    if not fixture and compose is None:
        pass
    elif compose is None:
        shutil.copy(_FIXTURES / fixture, host / _COMPOSE)
    else:
        (host / _COMPOSE).write_text(compose)
    if published is not None:
        shutil.copy(_FIXTURES / published, tmp / "compose.published")
    elif fixture or compose is not None:
        shutil.copy(host / _COMPOSE, tmp / "compose.published")
    n, swapped = {"all": (2, "api gateway"), "gateway": (1, "gateway")}[service]
    preamble = f"""
set -euo pipefail
TAG={_TAG}; REF=origin/main; MODE=stage; DRY=0; HOST=fake-host; SERVICE={service}; REPOINTS=pins; ALREADY="pins already on the tag"; N={n}; SWAPPED="{swapped}"
COMPOSE_DIR={host}; COMPOSE={_COMPOSE}; STAGED={_COMPOSE}.pit-stop-staged; TMP={tmp}; API=http://fake-host; REPOINT_PY={_SCRIPT.parent / "pit_stop_repoint.py"}
step() {{ printf '==> %s\\n' "$*"; }}
die() {{ printf 'PIT STOP ABORTED: %s\\n' "$*" >&2; exit 1; }}
run() {{ "$@"; }}
{stub}
{_refuse_drift()}
{_function("apply_null_keys")}
{_counters()}
{_apply_staged()}
"""
    body = "apply_staged" if apply else _stage_block()
    return subprocess.run(
        ["bash", "-c", preamble + body, str(_SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    host, tmp = tmp_path / "host", tmp_path / "tmp"
    host.mkdir()
    tmp.mkdir()
    return host, tmp


@pytest.mark.parametrize(
    ("fixture", "backup"),
    [
        ("compose-digest.yaml", "sha256-bf783882d031"),
        ("compose-tag.yaml", None),
    ],
)
def test_a_whole_transfer_stages_beside_the_live_compose_and_the_swap_applies_it(
    fixture: str, backup: str | None, dirs: tuple[Path, Path]
) -> None:
    host, tmp = dirs
    original = (_FIXTURES / fixture).read_text()
    proc = _run_stage(fixture, host, tmp, _FULL)
    assert proc.returncode == 0, proc.stderr

    # #1511: a `compose up` now would still start what ran before the stage.
    assert (host / _COMPOSE).read_text() == original
    assert not list(host.glob(f"{_COMPOSE}.bak-*"))
    staged = (host / _STAGED).read_text()
    assert staged.count(f"syn-api:{_TAG}") == 1
    assert staged.count(f"syn-gateway:{_TAG}") == 1
    assert not (host / f"{_COMPOSE}.pit-stop").exists()

    proc = _run_stage("", host, tmp, _FULL, apply=True)
    assert proc.returncode == 0, proc.stderr
    assert (host / _COMPOSE).read_text() == staged
    assert not (host / _STAGED).exists()
    backups = list(host.glob(f"{_COMPOSE}.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    if backup is not None:
        assert backups[0].name == f"{_COMPOSE}.bak-{backup}"


def test_the_swap_refuses_a_stage_the_live_compose_has_moved_past(dirs: tuple[Path, Path]) -> None:
    """An edit to the live compose after the stage (a new env var) must not be
    silently reverted by moving the older staged file over it."""
    host, tmp = dirs
    assert _run_stage("compose-digest.yaml", host, tmp, _FULL).returncode == 0
    edited = (host / _COMPOSE).read_text() + "    environment:\n      ADDED_AFTER_STAGE: '1'\n"
    (host / _COMPOSE).write_text(edited)

    proc = _run_stage("", host, tmp, _FULL, apply=True)
    assert proc.returncode != 0
    assert "changed after" in proc.stderr
    assert (host / _COMPOSE).read_text() == edited
    assert not list(host.glob(f"{_COMPOSE}.bak-*"))


def test_the_stage_refuses_a_compose_edited_on_the_host_since_the_precheck(
    dirs: tuple[Path, Path],
) -> None:
    """#1511 verification: the precheck passed a compose that carried the
    archive setting $REF publishes; during the build it was edited away. The
    stage reads the file again, and it is those bytes that must be checked."""
    host, tmp = dirs
    proc = _run_stage("compose-tag.yaml", host, tmp, _FULL, published="compose-drifted.yaml")

    assert proc.returncode != 0
    assert "+      SYN_SESSION_INVENTORY_ARCHIVE_DIR: /app/data/session-inventory" in proc.stdout
    assert "is not the compose origin/main publishes" in proc.stderr
    assert (host / _COMPOSE).read_bytes() == (_FIXTURES / "compose-tag.yaml").read_bytes()
    assert not (host / _STAGED).exists()
    assert not (host / f"{_COMPOSE}.pit-stop").exists()

    # And nothing the swap could apply: with no stage, it refuses.
    proc = _run_stage("", host, tmp, _FULL, apply=True)
    assert proc.returncode != 0
    assert (host / _COMPOSE).read_bytes() == (_FIXTURES / "compose-tag.yaml").read_bytes()


@pytest.mark.parametrize("fixture", ["compose-digest.yaml", "compose-tag.yaml"])
def test_a_short_transfer_leaves_the_deployed_compose_untouched(
    fixture: str, dirs: tuple[Path, Path]
) -> None:
    host, tmp = dirs
    original = (_FIXTURES / fixture).read_bytes()
    proc = _run_stage(fixture, host, tmp, _SHORT)

    assert (host / _COMPOSE).read_bytes() == original
    assert proc.returncode != 0
    assert "did not arrive intact" in proc.stderr
    assert not (host / f"{_COMPOSE}.pit-stop").exists()
    assert not (host / _STAGED).exists()
    assert not list(host.glob(f"{_COMPOSE}.bak-*"))


def test_a_gateway_only_stage_repoints_one_pin_and_passes_its_own_count(
    dirs: tuple[Path, Path],
) -> None:
    """#1310: the stage passes `--service gateway` to the repoint and then
    requires the gateway pin, alone, on the tag. syn-api keeps its digest."""
    host, tmp = dirs
    proc = _run_stage("compose-digest.yaml", host, tmp, _FULL, service="gateway")
    assert proc.returncode == 0, proc.stderr

    staged = (host / _STAGED).read_text()
    assert staged.count(f"syn-gateway:{_TAG}") == 1
    assert f"syn-api:{_TAG}" not in staged
    assert "syn-api@sha256:bf783882d031" in staged
    assert _run_stage("", host, tmp, _FULL, service="gateway", apply=True).returncode == 0
    (backup,) = host.glob(f"{_COMPOSE}.bak-*")
    assert backup.name == f"{_COMPOSE}.bak-sha256-6b416d4a25dd"


def test_a_gateway_only_stage_passes_when_the_api_is_already_on_the_tag(
    dirs: tuple[Path, Path],
) -> None:
    """#1310 verification: a total over both services counted 2 here, aborted
    with 2/1, and left the new compose deployed. Only the gateway is counted."""
    host, tmp = dirs
    compose = (
        (_FIXTURES / "compose-tag.yaml")
        .read_text()
        .replace("syn-api:v0.33.1-beta.2", f"syn-api:{_TAG}")
    )
    proc = _run_stage("", host, tmp, _FULL, service="gateway", compose=compose)
    assert proc.returncode == 0, proc.stderr

    staged = (host / _STAGED).read_text()
    assert staged.count(f"syn-api:{_TAG}") == 1
    assert staged.count(f"syn-gateway:{_TAG}") == 1


@pytest.mark.parametrize("failure", ["post_read", "write_ack", "stale_stage"])
def test_admission_stays_paused_once_the_live_compose_may_have_been_written(
    failure: str, tmp_path: Path
) -> None:
    """#1511 verification: gated and drained, the swap moves the stage over the
    live compose and the ssh then fails, after the write (`post_read`) or by
    losing its reply (`write_ack`). The live file names the new images while
    the old ones still run, so the real exit trap must keep admission PAUSED
    and print how to finish or undo. A refusal before the write
    (`stale_stage`) changed nothing, and must still re-open it."""
    host, tmp = tmp_path / "host", tmp_path / "tmp"
    host.mkdir()
    tmp.mkdir()
    original = (_FIXTURES / "compose-digest.yaml").read_text()
    assert _run_stage("compose-digest.yaml", host, tmp, _FULL).returncode == 0
    wanted = (host / _STAGED).read_text()
    if failure == "stale_stage":
        (host / _COMPOSE).write_text(original + "    environment:\n      ADDED_AFTER_STAGE: '1'\n")

    admission, moved = tmp_path / "admission", tmp_path / "moved"
    stub = f"""
GATED=1; SWAPPING=0; LOCKED=0; RECOVERY=""; RECOVERY_SHOWN=0
maintenance() {{ echo "maintenance $1" >> {admission}; }}
{_function("die")}
{_function("release_on_exit")}
trap release_on_exit EXIT
remote() {{
    if [ "{failure}" = post_read ] && [ -e {moved} ] && [ "$*" = "cat {host}/{_COMPOSE}" ]; then
        echo "ssh: connection lost" >&2; return 255
    fi
    bash -c "$*" || return $?
    case "$*" in *"&& mv "*) touch {moved}; [ "{failure}" != write_ack ] || return 255 ;; esac
}}
"""
    proc = _run_stage("", host, tmp, stub, apply=True)
    assert proc.returncode != 0

    if failure == "stale_stage":
        assert "changed after" in proc.stderr
        assert admission.read_text() == "maintenance false\n"
        assert "RECOVERY" not in proc.stderr
        return
    assert (host / _COMPOSE).read_text() == wanted != original
    assert not admission.exists(), admission.read_text()
    assert "still PAUSED" in proc.stderr
    assert "up -d api gateway" in proc.stderr
    assert f"cp {_COMPOSE}.bak-sha256-bf783882d031 {_COMPOSE}" in proc.stderr


def test_the_stage_adds_null_env_keys_to_the_live_compose_with_a_backup(
    dirs: tuple[Path, Path],
) -> None:
    """#2154: a `KEY: null` passthrough the ref adds is written into the live
    compose (backed up, mode kept), and the stage then proceeds."""
    host, tmp = dirs
    live = (
        (_FIXTURES / "compose-tag.yaml")
        .read_text()
        .replace(
            "    image: ghcr.io/syntropic137/syn-api:v0.33.1-beta.2\n",
            "    image: ghcr.io/syntropic137/syn-api:v0.33.1-beta.2\n    environment:\n      SYN_A: null\n",
        )
    )
    published = live.replace("      SYN_A: null\n", "      SYN_A: null\n      SYN_NEW: null\n")
    (host / _COMPOSE).write_text(live)
    (host / _COMPOSE).chmod(0o640)
    (tmp / "compose.published").write_text(published)
    proc = _run_stage("", host, tmp, _FULL)

    assert proc.returncode == 0, proc.stderr
    assert "adding 1 KEY: null env passthrough line(s)" in proc.stdout
    assert (host / _COMPOSE).read_text() == published
    assert (host / _COMPOSE).stat().st_mode & 0o777 == 0o640
    backups = list(host.glob(f"{_COMPOSE}.bak-*-pitstop-keys"))
    assert len(backups) == 1 and backups[0].read_text() == live
    assert not (host / f"{_COMPOSE}.pit-stop-keys").exists()
    assert (host / _STAGED).exists()
