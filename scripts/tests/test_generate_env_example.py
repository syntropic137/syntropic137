"""The .env serializer must round-trip every value, not the ones we thought of.

`just` loads .env through dotenvy. One value dotenvy rejects takes down EVERY
just recipe, including the pre-push hook - which then stops gating without
saying so. That shipped twice: an unquoted regex default, then a fix that
covered three of six emit sites.

Both failures came from the same design, "quote only when the value looks
dangerous", so this pins the replacement: ONE serializer, single-quoting
unconditionally, asserted by round-trip rather than by comparing to a
hand-written expected string. A round-trip cannot be satisfied by a serializer
that merely agrees with the test author's idea of what quoting looks like.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generate_env_example import serialize_dotenv_value

pytestmark = pytest.mark.unit

#: (id, raw semantic value). Every entry is a value the previous
#: "needs quoting?" character set got wrong, plus the ordinary cases.
_VALUES: list[tuple[str, str]] = [
    ("empty", ""),
    ("plain", "plain-value"),
    ("whitespace", "0 3 * * *"),
    ("dollar", "$HOME"),
    ("dollar_braced", "${HOME}/bin"),
    ("backslash", "back\\slash\\n"),
    ("apostrophe", "don't"),
    ("apostrophe_plus_specials", "it's $HOME (a|b) & `x` ; <>"),
    ("leading_single_quote", "'unterminated"),
    ("leading_double_quote", '"unterminated'),
    ("embedded_double_quotes", 'say "hi" now'),
    ("embedded_newline", "line1\nline2"),
    ("regex_default", "^https://github\\.com/(org|other)/.+$"),
]

_IDS = [name for name, _ in _VALUES]
_RAW = [value for _, value in _VALUES]


@pytest.mark.parametrize("value", _RAW, ids=_IDS)
def test_round_trips_under_posix_shell_lexing(value: str) -> None:
    """The serialized form must lex back to the ORIGINAL semantic value.

    shlex is the POSIX shell lexer, which is what `set -a; . ./.env` uses.
    """
    serialized = serialize_dotenv_value(value)
    assert shlex.split(serialized, posix=True) == ([] if value == "" else [value])


@pytest.mark.parametrize("value", _RAW, ids=_IDS)
def test_no_substitution_leaks_into_the_serialized_form(value: str) -> None:
    """A value is never emitted in a form a parser would expand.

    dotenvy substitutes variables inside DOUBLE quotes, so a literal `$HOME`
    would silently become the caller's home directory. Only single quotes
    suppress that, so nothing may be emitted double-quoted.
    """
    serialized = serialize_dotenv_value(value)
    if value == "":
        assert serialized == ""
    else:
        assert serialized.startswith("'")
        assert serialized.endswith("'")


def test_empty_value_stays_empty() -> None:
    """Secrets and unset optionals are emitted as `KEY=`, not `KEY=''`."""
    assert serialize_dotenv_value("") == ""


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_round_trips_through_the_real_dotenv_loader(tmp_path: Path) -> None:
    """The parser that actually breaks the build is dotenvy, via `just`.

    shlex proves POSIX-shell semantics; only `just` itself proves that `just`
    can still load the file. Both matter, because the failure mode being
    guarded is "every recipe stopped working".
    """
    env_lines = [f"V{i}={serialize_dotenv_value(value)}" for i, (_, value) in enumerate(_VALUES)]
    (tmp_path / ".env").write_text("\n".join(env_lines) + "\n")

    # Record/unit separators, so a value containing newlines, quotes or shell
    # metacharacters cannot forge the framing of the output being asserted on.
    recipe = ["set dotenv-load := true", "", "show:"]
    recipe += [f'    @printf "%s\\x1e%s\\x1f" "V{i}" "$V{i}"' for i in range(len(_VALUES))]
    (tmp_path / "justfile").write_text("\n".join(recipe) + "\n")

    result = subprocess.run(
        ["just", "show"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    loaded: dict[str, str] = {}
    for record in result.stdout.split("\x1f"):
        if record:
            key, _, loaded_value = record.partition("\x1e")
            loaded[key] = loaded_value

    for i, (name, value) in enumerate(_VALUES):
        assert loaded[f"V{i}"] == value, f"{name} did not round-trip through dotenvy"
