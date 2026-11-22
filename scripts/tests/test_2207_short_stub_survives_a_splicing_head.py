"""#2207: the short stub must not put `head` on calls that read nothing.

On the CI runner (ubuntu-26.04, `head (uutils coreutils) 0.10.0`, bash 5.3.9)
`head -c 100 </dev/null | bash -c "cat f"` returns PIPESTATUS `141 0`: `head`,
with nothing to copy, is killed by SIGPIPE once `cat` on the other end has
exited, and says nothing. Alone, `head -c 100 </dev/null >/dev/null` never
failed there, and `cat` always exited 0 on a readable file. Under pipefail
that killed the stage's plain read of the deployed compose with only the `die`
line on stderr. GNU `head` never writes zero bytes, so it cannot hit the closed
pipe, which is why nothing reproduced off the runner. splice(2) into a pipe
checks for a reader before it looks at the length.

`_SPLICING_HEAD` is that `head`, made to lose the race every time: on empty
input it waits until its reader is gone, then splices. With it, the old stub
fails exactly as CI did and the repaired `_SHORT` reaches the transfer.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_spec = importlib.util.spec_from_file_location(
    "_stage_2207", Path(__file__).with_name("test_pit_stop_stage_write.py")
)
assert _spec is not None and _spec.loader is not None
stage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage)

_OLD_SHORT = 'remote() { head -c 100 | bash -c "$*"; }'

_SPLICING_HEAD = """\
import os, select, signal, stat, sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
n = int(sys.argv[2])
st = os.fstat(0)
if not (stat.S_ISREG(st.st_mode) and st.st_size):
    # Nothing to copy: wait for the reader to exit (POLLERR), the losing order.
    p = select.poll()
    p.register(1, 0)
    p.poll()
while n > 0:
    moved = os.splice(0, 1, n)
    if not moved:
        break
    n -= moved
"""


@pytest.mark.parametrize("fixture", ["compose-digest.yaml", "compose-tag.yaml"])
@pytest.mark.parametrize(
    ("stub", "expected"),
    [
        (_OLD_SHORT, "PIT STOP ABORTED: could not read the deployed compose file\n"),
        (stage._SHORT, "did not arrive intact"),
    ],
    ids=["old-stub-dies-at-the-read", "short-stub-reaches-the-transfer"],
)
def test_a_splicing_head_only_cuts_the_transfer(
    stub: str, expected: str, fixture: str, tmp_path: Path
) -> None:
    host, tmp = tmp_path / "host", tmp_path / "tmp"
    host.mkdir()
    tmp.mkdir()
    fake = tmp_path / "splicing_head.py"
    fake.write_text(_SPLICING_HEAD)
    python = shutil.which("python3")
    assert python is not None
    head = f'head() {{ {python} -I {fake} "$@"; }}\n'

    proc = stage._run_stage(fixture, host, tmp, head + stub)

    assert expected in proc.stderr, proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert (host / stage._COMPOSE).read_bytes() == (stage._FIXTURES / fixture).read_bytes()
