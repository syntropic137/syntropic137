"""The public docs name only commands, flags and routes the software accepts.

Fitness function, not a test of one code path: it reads every page under
``apps/syn-docs/content`` plus the root README, and measures the whole set
against the artifacts the software is built from (the CLI command manifest,
the OpenAPI spec, the setup CLI's flag list). See ``scripts/check_docs_drift.py``
for what is extracted and how it is matched.

Why it exists: on v1.0.0 every command in "Run Your First Workflow" was wrong
(#1946), and the workflows guide said ``allowed_tools`` restricts nothing when
it has been enforced since v0.28.0. Prose drifts silently; a parser does not.

Budget: ``[docs_drift.budget]`` in ``fitness_exceptions.toml`` grandfathers a
file's existing false claims against an open issue. The ratchet runs both ways:
more findings than the budget fails, and FEWER fails too, so the budget comes
down in the same PR as the fix. ``[[docs_drift.allow]]`` waives one quoted
snippet that is illustrative on purpose; an entry that matches nothing fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_docs_drift import Policy, doc_files, scan  # noqa: E402


@pytest.mark.architecture
def test_docs_commands_and_routes_exist() -> None:
    report = scan(doc_files(ROOT), root=ROOT)
    policy = Policy.load()
    budgets = {b.file: b for b in policy.budgets}
    actual = report.per_file()

    problems: list[str] = []
    for file, count in sorted(actual.items()):
        budget = budgets.get(file)
        allowed = budget.max if budget else 0
        if count > allowed:
            problems.append(f"{file}: {count} false command/route claims, budget {allowed}:")
            problems.extend(f"  {f.render()}" for f in report.findings if f.snippet.file == file)
    for file, budget in sorted(budgets.items()):
        if actual.get(file, 0) < budget.max:
            problems.append(
                f"{file}: budget {budget.max} ({budget.issue}) but only {actual.get(file, 0)} found."
                " Lower [docs_drift.budget] to match: the ratchet only moves down."
            )
    problems.extend(
        f"{a.file}: [[docs_drift.allow]] matches nothing, remove it: {a.text!r}"
        for a in report.stale_allows
    )
    assert not problems, (
        "Docs name commands, flags or API routes the software rejects.\n"
        "Fix the page, or if a snippet is illustrative on purpose add a"
        " [[docs_drift.allow]] entry with a reason in ci/fitness/fitness_exceptions.toml.\n"
        + "\n".join(problems)
    )


@pytest.mark.architecture
@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (
            "Run `syn workflow run my-wf --no-such-flag`.",
            "syn workflow run has no flag --no-such-flag",
        ),
        ("```bash\nsyn workflow installed\n```", "syn workflow has no subcommand 'installed'"),
        (
            "```bash\ncurl -X POST $SYN_API_URL/api/v1/no-such-route\n```",
            "no such path in the OpenAPI spec",
        ),
        (
            "`npx @syntropic137/setup init --no-such-flag`",
            "setup init does not use flag --no-such-flag",
        ),
    ],
)
def test_gate_fails_on_a_planted_false_claim(tmp_path: Path, page: str, expected: str) -> None:
    """The real manifests reject a planted bad command: the gate is not vacuous."""
    doc = tmp_path / "planted.mdx"
    doc.write_text(page)
    report = scan([doc], root=tmp_path, policy=Policy())
    assert [f.problem for f in report.findings if expected in f.problem], (
        f"planted claim was not caught; findings: {[f.render() for f in report.findings]}"
    )
