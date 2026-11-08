"""TEMPORARY diagnostic for #2207: run the old short stub on the CI runner and
report every pipeline status it returns. Always fails, to put the report in the
CI log. Replaced by a regression test once the mechanism is known."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "_stage_2207", Path(__file__).with_name("test_pit_stop_stage_write.py")
)
assert _spec is not None and _spec.loader is not None
stage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage)

pytestmark = pytest.mark.unit

_OLD = """remote() {
    head -c 100 | bash -c "$*"
    local s=("${PIPESTATUS[@]}")
    [ "${s[*]}" = "0 0" ] || printf 'old stub: PIPESTATUS %s from: %s\\n' "${s[*]}" "$*" >&2
    [ "${s[1]}" = 0 ] && return "${s[0]}"; return "${s[1]}"
}"""

_LOOP = r"""
set -uo pipefail
f="$1"; n="$2"; out="$3"
for i in $(seq 1 "$n"); do
  head -c 100 | bash -c "cat $f" > "$out.$BASHPID"; s=("${PIPESTATUS[@]}")
  [ "${s[*]}" = "0 0" ] || echo "pipe iter $i PIPESTATUS ${s[*]}"
  head -c 100 > /dev/null; r=$?
  [ "$r" = 0 ] || echo "alone iter $i head exit $r"
  head -c 100 | true; s=("${PIPESTATUS[@]}")
  [ "${s[*]}" = "0 0" ] || echo "true iter $i PIPESTATUS ${s[*]}"
done
"""


def _sh(cmd: str) -> str:
    return (
        subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=False).stdout
        + "\n"
    )


def test_report_the_old_short_stub_on_this_runner(tmp_path: Path) -> None:
    report = [
        _sh(
            'uname -a; bash --version | head -1; command -v head; readlink -f "$(command -v head)"; '
            "head --version 2>&1 | head -2; dpkg -l 'coreutils*' 'rust-coreutils*' 2>/dev/null | tail -n +6; "
            "ls -l /usr/bin/gnuhead /usr/lib/cargo/bin/coreutils/head 2>&1; nproc"
        ),
    ]
    f = tmp_path / "compose.yaml"
    f.write_bytes((stage._FIXTURES / "compose-digest.yaml").read_bytes())
    procs = [
        subprocess.Popen(
            ["bash", "-c", _LOOP, "loop", str(f), "1000", str(tmp_path / f"o{k}")],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for k in range(4)
    ]
    stage_fail = []
    for k in range(150):
        for fixture in ("compose-digest.yaml", "compose-tag.yaml"):
            d = tmp_path / f"s{k}{fixture}"
            host, tmp = d / "host", d / "tmp"
            host.mkdir(parents=True)
            tmp.mkdir()
            proc = stage._run_stage(fixture, host, tmp, _OLD)
            if "did not arrive intact" not in proc.stderr:
                stage_fail.append(
                    f"stage {k} {fixture}: rc={proc.returncode} stderr={proc.stderr!r}"
                )
    for p in procs:
        out, _ = p.communicate()
        report.append(f"loop rc={p.returncode}: {out.count(chr(10))} bad lines\n{out[:3000]}")
    report.append(f"stage failures {len(stage_fail)}/300\n" + "\n".join(stage_fail[:40]))
    pytest.fail("#2207 PROBE REPORT\n" + "\n".join(report), pytrace=False)
