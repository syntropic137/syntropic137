"""check_docs_drift extracts every command a reader would run, and rejects the false ones.

Each test plants a page and asserts what the checker finds, against small
manifests written here so a test reads on its own. The fitness test
``ci/fitness/code_quality/test_docs_drift.py`` runs the same code against the
real manifests and the real docs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_docs_drift import (
    Allow,
    ApiRoute,
    CliManifest,
    Command,
    Group,
    Kind,
    Option,
    Policy,
    SetupCommand,
    SetupManifest,
    SetupSource,
    extract,
    scan,
)

CLI = CliManifest(
    global_options=(Option(name="help", short="h", takes_value=False),),
    top_level_flags=frozenset({"--help", "-h", "--version"}),
    root_commands=(Command(name="health", args=(), options=()),),
    groups=(
        Group(
            name="workflow",
            commands=(
                Command(
                    name="run",
                    args=("workflow-id",),
                    options=(
                        Option(name="dry-run", short="n", takes_value=False),
                        Option(name="input", short="i", takes_value=True),
                        Option(name="quiet", short="q", takes_value=False),
                    ),
                ),
                Command(name="list", args=(), options=()),
            ),
        ),
    ),
)
SETUP = SetupManifest(
    source=SetupSource(
        repo="r", commit="c", version="v", tracking="t", files=(), why_vendored="test"
    ),
    global_flags=frozenset({"--help", "-h"}),
    menu_flags=frozenset({"--dir"}),
    value_flags=frozenset({"--dir", "--org"}),
    commands=(
        SetupCommand(name="init", flags=frozenset({"--dir", "--org", "--skip-docker"})),
        SetupCommand(
            name="credentials", flags=frozenset({"--dir"}), actions=frozenset({"show", "rotate"})
        ),
    ),
)
ROUTES = [
    ApiRoute(segments=("executions",), methods=frozenset({"GET"})),
    ApiRoute(segments=("executions", "{execution_id}"), methods=frozenset({"GET"})),
    ApiRoute(segments=("executions", "{execution_id}", "cancel"), methods=frozenset({"POST"})),
    ApiRoute(segments=("workflows", "validate"), methods=frozenset({"POST"})),
]


def problems(tmp_path: Path, page: str, policy: Policy | None = None) -> list[str]:
    doc = tmp_path / "page.mdx"
    doc.write_text(page)
    report = scan(
        [doc], root=tmp_path, cli=CLI, setup=SETUP, routes=ROUTES, policy=policy or Policy()
    )
    return [f.problem for f in report.findings]


@pytest.mark.unit
class TestExtraction:
    def test_code_block_inline_and_prose_paths(self) -> None:
        page = "\n".join(
            [
                "Run `syn workflow list` first.",
                "```bash",
                "$ syn workflow run wf \\",
                "    --input a=b",
                "FOO=1 syn health && echo ok | syn workflow list",
                "npx @syntropic137/setup@latest init --skip-docker",
                "```",
                "POST /api/v1/executions/abc/cancel stops it.",
            ]
        )
        got = [(s.kind, s.text, s.line) for s in extract("p.mdx", page)]
        assert (Kind.SYN, "syn workflow list", 1) in got
        assert (Kind.SYN, "syn workflow run wf --input a=b", 3) in got
        assert (Kind.SYN, "FOO=1 syn health", 5) in got
        assert (Kind.SYN, "syn workflow list", 5) in got
        assert (Kind.SETUP, "npx @syntropic137/setup@latest init --skip-docker", 6) in got
        assert (Kind.API, "/api/v1/executions/abc/cancel", 8) in got

    def test_a_word_that_merely_starts_with_syn_is_not_a_command(self) -> None:
        assert extract("p.mdx", "`syn-api` and `synthesis --x` and `npx other-pkg`") == []

    def test_shell_comment_is_not_part_of_the_command(self) -> None:
        [s] = extract("p.mdx", "```\nsyn workflow list  # --bogus in a comment\n```")
        assert s.text == "syn workflow list"


@pytest.mark.unit
class TestSynCommands:
    @pytest.mark.parametrize(
        "cmd",
        [
            "syn",
            "syn --version",
            "syn workflow",
            "syn workflow --help",
            "syn workflow run wf -n",
            "syn workflow run wf --input=a=b --quiet",
            "syn workflow run wf -i a=b -nq",
            "syn workflow run wf --help",
            "syn workflow run <id> [--input K=V]...",
            "syn workflow run wf -n/--dry-run",
            "syn workflow run wf -ix=1",
            "syn workflow run wf -qi a=b",
            "npx @syntropic137/cli workflow list",
        ],
    )
    def test_accepted(self, tmp_path: Path, cmd: str) -> None:
        assert problems(tmp_path, f"`{cmd}`") == []

    @pytest.mark.parametrize(
        ("cmd", "expected"),
        [
            ("syn flows list", "no command or group named 'flows'"),
            ("syn workflow installed", "syn workflow has no subcommand 'installed'"),
            ("syn workflow run wf --path x", "syn workflow run has no flag --path"),
            ("syn workflow run wf -x", "syn workflow run has no flag -x"),
            ("syn workflow run wf -nz", "syn workflow run has no flag -z"),
            ("syn workflow run wf --quiet=yes", "flag --quiet takes no value"),
            ("syn workflow run wf -z/--zed", "syn workflow run has no flag -z"),
            ("syn <group> list", "placeholder <group> where a command belongs"),
            ("syn health --verbose", "syn health has no flag --verbose"),
        ],
    )
    def test_rejected(self, tmp_path: Path, cmd: str, expected: str) -> None:
        assert any(expected in p for p in problems(tmp_path, f"`{cmd}`")), problems(
            tmp_path, f"`{cmd}`"
        )

    def test_a_quoted_separator_does_not_hide_the_rest_of_the_command(self, tmp_path: Path) -> None:
        page = '`syn workflow run wf --input "a; b" --no-such-flag`'
        assert any("--no-such-flag" in p for p in problems(tmp_path, page))

    def test_an_escaped_separator_does_not_hide_the_rest_of_the_command(
        self, tmp_path: Path
    ) -> None:
        page = "```\nsyn workflow run wf --input a\\;b --no-such-flag\n```"
        assert any("--no-such-flag" in p for p in problems(tmp_path, page))

    @pytest.mark.parametrize("position", [0, 1, 2])
    def test_every_usage_flag_is_checked_after_an_alternative(
        self, tmp_path: Path, position: int
    ) -> None:
        # The shape of guide/evals.mdx: a | inside [...] is an alternative, not a pipe.
        flags = ["[--quiet]", "[--dry-run]", "[--input K=V]..."]
        flags[position] = "[--no-such-flag]"
        page = f"```\nsyn workflow run <id> [--input a|b] {' '.join(flags)}\n```"
        assert any("--no-such-flag" in p for p in problems(tmp_path, page))

    def test_a_usage_alternative_is_one_command(self) -> None:
        page = "```\nsyn workflow run <id> [--input a|b] [--quiet] | syn workflow list\n```"
        got = [s.text for s in extract("p.mdx", page)]
        assert got == ["syn workflow run <id> [--input a|b] [--quiet]", "syn workflow list"]

    @pytest.mark.parametrize(
        "cmd",
        [
            "syn workflow run wf --input",
            "syn workflow run wf --input --no-such-flag",
            "syn workflow run wf -qi",
        ],
    )
    def test_a_value_flag_needs_a_value(self, tmp_path: Path, cmd: str) -> None:
        # Node's strict parseArgs refuses a missing or flag-like value.
        assert any("needs a value" in p for p in problems(tmp_path, f"`{cmd}`"))


@pytest.mark.unit
class TestApiRoutes:
    @pytest.mark.parametrize(
        "page",
        [
            "GET /api/v1/executions/{id}",
            "`GET /executions/<execution-id>`",
            '```\ncurl -X POST "$SYN_API_URL/api/v1/executions/$EXEC/cancel"\n```',
            '```\nAPI="$SYN_API_URL/api/v1"\ncurl "$API/executions/x?limit=5"\n```',
            "/api/v1/workflows/validate",
            "All routes live under `/api/v1`.",
        ],
    )
    def test_accepted(self, tmp_path: Path, page: str) -> None:
        assert problems(tmp_path, page) == []

    @pytest.mark.parametrize(
        ("page", "expected"),
        [
            ("GET /api/v1/executions/x/status", "no such path"),
            ("`DELETE /executions/{id}`", "DELETE not served (spec has GET)"),
            ("```\ncurl -X POST $SYN_API_URL/api/v1/executions\n```", "POST not served"),
            ('```\nAPI="$U/api/v1"\ncurl "$API/nope"\n```', "no such path"),
            # A placeholder never matches a literal segment.
            ("POST /api/v1/workflows/{id}", "no such path"),
            ("```\ncurl -XDELETE $SYN_API_URL/api/v1/executions/x\n```", "DELETE not served"),
            ("```\ncurl -X TRACE $SYN_API_URL/api/v1/executions/x\n```", "TRACE not served"),
            (
                "```\ncurl -X GET $SYN_API_URL/api/v1/executions/a; "
                "curl -X DELETE $SYN_API_URL/api/v1/executions/b\n```",
                "DELETE not served",
            ),
            (
                "```\ncurl --request=DELETE $SYN_API_URL/api/v1/executions/x\n```",
                "DELETE not served",
            ),
        ],
    )
    def test_rejected(self, tmp_path: Path, page: str, expected: str) -> None:
        assert any(expected in p for p in problems(tmp_path, page)), problems(tmp_path, page)


@pytest.mark.unit
class TestSetupCommands:
    @pytest.mark.parametrize(
        "cmd",
        [
            "npx @syntropic137/setup",
            "npx @syntropic137/setup --dir /x",
            "npx -y @syntropic137/setup@1.0.2 init --org acme --skip-docker",
            "npx @syntropic137/setup init --dir=/x",
            "npx @syntropic137/setup credentials rotate",
            "npx @syntropic137/setup init [options]",
        ],
    )
    def test_accepted(self, tmp_path: Path, cmd: str) -> None:
        assert problems(tmp_path, f"`{cmd}`") == []

    @pytest.mark.parametrize(
        ("cmd", "expected"),
        [
            ("npx @syntropic137/setup deploy", "setup has no command 'deploy'"),
            # Accepted by the parser, read by nothing: the lie this exists for.
            (
                "npx @syntropic137/setup credentials --org acme",
                "setup credentials does not use flag --org",
            ),
            (
                "npx @syntropic137/setup credentials purge",
                "setup credentials has no action 'purge'",
            ),
            (
                "npx @syntropic137/setup --skip-docker",
                "setup (no command) does not use flag --skip-docker",
            ),
            ("npx @syntropic137/setup init --org", "setup flag --org needs a value"),
        ],
    )
    def test_rejected(self, tmp_path: Path, cmd: str, expected: str) -> None:
        assert any(expected in p for p in problems(tmp_path, f"`{cmd}`"))


@pytest.mark.unit
class TestPolicy:
    def test_an_allow_entry_waives_exactly_the_quoted_snippet(self, tmp_path: Path) -> None:
        policy = Policy(
            allows=(Allow(file="page.mdx", text="syn <group> list", reason="usage shape"),)
        )
        doc = tmp_path / "page.mdx"
        doc.write_text("`syn <group> list` and `syn <group> show`")
        report = scan([doc], root=tmp_path, cli=CLI, setup=SETUP, routes=ROUTES, policy=policy)
        assert [f.snippet.text for f in report.allowed] == ["syn <group> list"]
        assert [f.snippet.text for f in report.findings] == ["syn <group> show"]
        assert report.stale_allows == []

    def test_an_allow_entry_that_matches_nothing_is_reported(self, tmp_path: Path) -> None:
        policy = Policy(allows=(Allow(file="page.mdx", text="syn gone", reason="was fixed"),))
        doc = tmp_path / "page.mdx"
        doc.write_text("`syn workflow list`")
        report = scan([doc], root=tmp_path, cli=CLI, setup=SETUP, routes=ROUTES, policy=policy)
        assert [a.text for a in report.stale_allows] == ["syn gone"]
