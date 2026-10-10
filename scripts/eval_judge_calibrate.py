#!/usr/bin/env python3
"""Calibrate the LLM judge against the keyword judge on runs already launched.

Reads the launch ledger for every line whose suite tag starts with ``--suite-tag``
(default ``verifier-seed-v1:v6:``), fetches each run's report from the API
(``GET /executions/{id}`` and its phase artifacts, as ``eval_suite.py score``
does), and prints one markdown row per BLOCKED defect run: the keyword verdict,
the LLM verdict, the finding the LLM quoted, and an empty column for a human's
own reading. It records nothing on the eval: it only reads.

    uv run python scripts/eval_judge_calibrate.py \\
        [--suite DIR] [--launches FILE] [--suite-tag PREFIX] [--version N] [--api-url URL] [--sample N]

All keyword-missed blocked runs are listed, and a deterministic sample of
``--sample`` keyword-matched ones (default 10), so the table can show whether
the LLM judge credits vague findings (precision) as well as paraphrases (recall).

The judge's key is the platform's ``ANTHROPIC_API_KEY`` setting (environment or
``.env``). Every defect case must carry ``expected.defect``.

The ledger must hold the runs: the checked-in ``launches.jsonl`` has no v6 lines
unless they were committed from the workspace that launched them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from eval_suite import (
    DEFAULT_SUITE,
    AnthropicMessages,
    DefectCase,
    JudgeError,
    KeywordJudge,
    LlmJudge,
    _basic_auth,
    _Execution,
    _get,
    _report_of,
    blocking_findings,
    judge_problems,
    launches_path,
    load_suite,
    read_launches,
)

from syn_shared.settings.dev_tooling import get_dev_api_url


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")[:160]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--launches", type=Path, default=None)
    parser.add_argument("--suite-tag", default="verifier-seed-v1:v6:")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--version", type=int, default=6, help="suite version the runs ran")
    parser.add_argument("--sample", type=int, default=10)
    args = parser.parse_args(argv)

    launches = [
        x
        for x in read_launches(args.launches or launches_path(args.suite))
        if x.suite.startswith(args.suite_tag)
    ]
    if not launches:
        print(f"❌ no ledger line has a suite tag starting {args.suite_tag!r}", file=sys.stderr)
        return 1
    # The case set of the version the runs were launched under, never another's.
    loaded = load_suite(args.suite, version=args.version)
    if problems := judge_problems(loaded):
        print("❌ the LLM judge cannot score:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    cases = {c.id: c for c in loaded.cases}
    try:
        llm = LlmJudge(AnthropicMessages.from_settings())
    except JudgeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    keyword = KeywordJudge()

    missed: list[str] = []
    matched: list[str] = []
    with httpx.Client(
        base_url=args.api_url or get_dev_api_url(), timeout=60, auth=_basic_auth()
    ) as client:
        for launch in launches:
            case = cases.get(launch.case)
            if not isinstance(case, DefectCase):
                continue
            run = _get(client, _Execution, f"/executions/{launch.run_id}")
            if run.review_verdict != "blocked":
                continue
            findings = blocking_findings(_report_of(client, run))
            kw = keyword.judge(case.expected, findings)
            ai = llm.judge(case.expected, findings)
            row = (
                f"| {case.id} | {launch.run_id} | {kw.verdict} | {ai.verdict} | "
                f"{_cell(ai.quote) or '-'} | {_cell(ai.reason)} |  |"
            )
            (matched if kw.verdict == "match" else missed).append(row)

    head = (
        "| case | run | keyword | LLM | LLM quoted | LLM reason | own reading |\n"
        "|---|---|---|---|---|---|---|"
    )
    print(f"judge: {llm.identity}\n")
    print(f"## Keyword-missed blocked runs ({len(missed)})\n\n{head}")
    print("\n".join(missed))
    sample = sorted(matched)[: args.sample]
    print(f"\n## Keyword-matched blocked runs (sample {len(sample)} of {len(matched)})\n\n{head}")
    print("\n".join(sample))
    return 0


if __name__ == "__main__":
    sys.exit(main())
