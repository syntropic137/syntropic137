"""Regression test for #1042: /tmp is noexec in the workspace sandbox, so
`just` cannot execute shebang recipes unless its own tempdir is redirected
somewhere exec-capable.

A `set tempdir := "..."` line sitting in the justfile proves nothing by
itself - it could point anywhere, or `just` could ignore it (an earlier
justfile-`export`/dotenv attempt looked identical to a working fix and did
nothing, because `just` decides the shebang temp location before either is
applied). This drives the real `just` binary against the real justfile and
inspects where it actually wrote the recipe script (`$0` inside the running
shebang), so it fails if the setting is missing OR if `just` doesn't honour
it OR if it resolves outside the repo checkout.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JUSTFILE = REPO_ROOT / "justfile"

_TEMPDIR_SETTING = re.compile(r'^\s*set\s+tempdir\s*:=\s*"([^"]+)"\s*$', re.MULTILINE)


def _configured_tempdir() -> str:
    match = _TEMPDIR_SETTING.search(JUSTFILE.read_text())
    assert match is not None, (
        'justfile has no `set tempdir := "..."` - without it, `just` writes '
        "shebang recipes to the OS temp dir, which the workspace sandbox "
        "mounts noexec (#1042)"
    )
    return match.group(1)


def test_configured_tempdir_is_inside_the_repo_not_the_system_tmp() -> None:
    value = _configured_tempdir()
    resolved = (REPO_ROOT / value).resolve()
    assert resolved.is_relative_to(REPO_ROOT), (
        f"tempdir {value!r} resolves outside the repo checkout ({resolved}) - "
        "it needs to sit somewhere the sandbox leaves exec-capable"
    )
    assert not value.startswith("/tmp"), (
        "tempdir points back at /tmp, the exact directory #1042 says is noexec"
    )


def test_configured_tempdir_directory_exists_after_a_fresh_clone() -> None:
    """`set tempdir` does not create the directory - `just` errors with
    `IO error ... No such file or directory` if it's missing, so a committed
    placeholder (e.g. `.gitkeep`) has to ship in the repo."""
    value = _configured_tempdir()
    assert (REPO_ROOT / value).is_dir()


def test_just_actually_writes_shebang_recipes_under_the_configured_tempdir() -> None:
    """Calls the real `just` binary against the real justfile's setting,
    rather than trusting that the text means what it says.

    A shebang recipe's own `$0` is the temp file `just` executed it from, so
    printing it reveals where `just` really put the script - the one thing a
    text-only check of the justfile can't see.
    """
    value = _configured_tempdir()
    expected_dir = (REPO_ROOT / value).resolve()

    # `set tempdir` resolves relative to the *justfile's own directory*,
    # regardless of invocation cwd or `-f` - confirmed empirically, since it's
    # undocumented - so the fixture justfile has to live next to the real one
    # (repo root) to resolve the same way the real justfile does.
    probe = 'probe:\n    #!/usr/bin/env bash\n    echo "$0"\n'
    fixture_justfile = REPO_ROOT / "test_justfile_tempdir_probe.just"
    fixture_justfile.write_text(f'set tempdir := "{value}"\n\n{probe}')
    try:
        result = subprocess.run(
            ["just", "-f", str(fixture_justfile), "probe"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"`just` failed to run a shebang recipe with tempdir={value!r} "
            f"configured: {result.stderr}"
        )
        script_path = Path(result.stdout.strip()).resolve()
        assert script_path.is_relative_to(expected_dir), (
            f"`just` wrote the shebang script to {script_path}, not under "
            f"the configured tempdir {expected_dir} - the setting isn't "
            "actually being honoured for recipe execution"
        )
    finally:
        fixture_justfile.unlink(missing_ok=True)
