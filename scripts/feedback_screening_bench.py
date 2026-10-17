#!/usr/bin/env python3
"""Check and score the feedback screening suite (ADR-076-feedback-ticketing, plan §2.10).

A suite lives in ``evals/feedback-screening-v1/``: ``suite.yaml`` names the
splits, and ``cases/<split>.jsonl`` holds one case per line. Every case has a
``group``; variants of one injection string or one spam family share it, and
a group lives in exactly one split, so tuning on train can never leak into a
holdout score. ``check`` refuses a suite where it does not.

``score`` runs one screener over one split and reports each rate with its
count and a Wilson 95% interval. ``--screener recorded`` replays the bodies in
``recorded/<model>.jsonl`` through the same parser the live adapter uses: it
proves the scoring arithmetic and the parse-failure handling, NOT a provider's
current safety, latency or cost. ``--screener anthropic`` is a real, paid run,
manual only, and needs ``ANTHROPIC_API_KEY``. No pricing has been checked, so
no cost is reported.

Usage:
    python scripts/feedback_screening_bench.py check
    python scripts/feedback_screening_bench.py score --screener heuristic --split validation
    python scripts/feedback_screening_bench.py score --screener recorded --model claude-haiku-5-5
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from collections import defaultdict
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from syn_adapters.feedback_screening import (
    AnthropicModelId,
    AnthropicScreener,
    HeuristicScreener,
    parse_screening_reply,
)
from syn_domain.contexts.feedback import (
    Priority,
    ScreenedText,
    ScreeningResult,
    ScreeningVerdict,
    TicketType,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.feedback.ports import ScreeningPort

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = REPO_ROOT / "evals" / "feedback-screening-v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_Z95 = 1.959963984540054
_EXIT_INVALID = 1


class Split(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


class Expected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: ScreeningVerdict
    type: TicketType
    priority: Priority


class Case(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    group: str = Field(min_length=1)
    family: Literal["clean", "injection", "spam"]
    text: str = Field(min_length=1)
    expected: Expected


class SuiteManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: int
    goal: str
    splits: tuple[Split, ...]
    sources: tuple[str, ...]


class Suite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: SuiteManifest
    cases: dict[Split, tuple[Case, ...]]


class Recording(BaseModel):
    """One captured Messages API response body for one case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    body: str
    note: str | None = None


class SuiteError(Exception):
    """The suite on disk breaks a rule ``check`` enforces. Carries every problem found."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


def load_suite(root: Path) -> Suite:
    """Parse and check a suite. Raises ``SuiteError`` listing every problem, not the first."""
    manifest = SuiteManifest.model_validate(yaml.safe_load((root / "suite.yaml").read_text()))
    problems: list[str] = []
    cases: dict[Split, tuple[Case, ...]] = {}
    for split in manifest.splits:
        path = root / "cases" / f"{split}.jsonl"
        parsed: list[Case] = []
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed.append(Case.model_validate_json(line))
            except ValidationError as exc:
                problems.append(f"{path.name}:{lineno}: not a case: {exc.errors()[0]['msg']}")
        cases[split] = tuple(parsed)
    problems.extend(split_problems(cases))
    if problems:
        raise SuiteError(problems)
    return Suite(manifest=manifest, cases=cases)


def split_problems(cases: dict[Split, tuple[Case, ...]]) -> list[str]:
    """Duplicate case ids, and groups that straddle splits (variants must not leak)."""
    problems: list[str] = []
    splits_of_group: defaultdict[str, set[Split]] = defaultdict(set)
    seen_ids: set[str] = set()
    for split, split_cases in cases.items():
        for case in split_cases:
            if case.id in seen_ids:
                problems.append(f"case id {case.id!r} appears more than once")
            seen_ids.add(case.id)
            splits_of_group[case.group].add(split)
    for group, splits in sorted(splits_of_group.items()):
        if len(splits) > 1:
            names = ", ".join(sorted(splits))
            problems.append(
                f"group {group!r} straddles splits ({names}); move every variant to one split"
            )
    return problems


class Rate(BaseModel):
    """k of n, with a Wilson 95% interval. n == 0 supports no claim at all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    k: int
    n: int
    rate: float | None
    low: float | None
    high: float | None

    @classmethod
    def of(cls, k: int, n: int) -> Rate:
        if n == 0:
            return cls(k=0, n=0, rate=None, low=None, high=None)
        low, high = wilson_interval(k, n)
        return cls(k=k, n=n, rate=k / n, low=low, high=high)


def wilson_interval(k: int, n: int) -> tuple[float, float]:
    p = k / n
    z2 = _Z95 * _Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = (_Z95 / (1 + z2 / n)) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


class Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    suite: str
    split: Split
    screener: str
    cases: int
    false_quarantine: Rate
    injection_catch: Rate
    spam_precision: Rate
    spam_recall: Rate
    type_accuracy: Rate
    priority_agreement: Rate
    claims: tuple[str, ...]


def score(suite: Suite, split: Split, screener: str, results: dict[str, ScreeningResult]) -> Report:
    cases = suite.cases[split]
    clean = [c for c in cases if c.expected.verdict is ScreeningVerdict.CLEAN]
    injections = [c for c in cases if c.expected.verdict is ScreeningVerdict.QUARANTINE]
    spam_expected = [c for c in cases if c.expected.verdict is ScreeningVerdict.SPAM]
    spam_predicted = [c for c in cases if results[c.id].verdict is ScreeningVerdict.SPAM]
    false_quarantine = Rate.of(
        sum(results[c.id].verdict is not ScreeningVerdict.CLEAN for c in clean), len(clean)
    )
    return Report(
        suite=suite.manifest.id,
        split=split,
        screener=screener,
        cases=len(cases),
        false_quarantine=false_quarantine,
        injection_catch=Rate.of(
            sum(results[c.id].verdict is ScreeningVerdict.QUARANTINE for c in injections),
            len(injections),
        ),
        spam_precision=Rate.of(
            sum(c.expected.verdict is ScreeningVerdict.SPAM for c in spam_predicted),
            len(spam_predicted),
        ),
        spam_recall=Rate.of(
            sum(results[c.id].verdict is ScreeningVerdict.SPAM for c in spam_expected),
            len(spam_expected),
        ),
        type_accuracy=Rate.of(
            sum(results[c.id].type is c.expected.type for c in clean), len(clean)
        ),
        priority_agreement=Rate.of(
            sum(results[c.id].priority is c.expected.priority for c in clean), len(clean)
        ),
        claims=_claims(false_quarantine),
    )


def _claims(false_quarantine: Rate) -> tuple[str, ...]:
    """What the false-quarantine number can and cannot support (rule of three)."""
    if false_quarantine.n == 0:
        return (
            "no clean cases in this split: no false-quarantine claim is possible. "
            "Clean cases arrive with real feedback, which waits on decision D4.",
        )
    bound = false_quarantine.high
    return (f"false quarantine is at most {bound:.1%} at 95% (n={false_quarantine.n})",)


def recorded_results(
    root: Path, model: AnthropicModelId, cases: Sequence[Case]
) -> dict[str, ScreeningResult]:
    path = root / "recorded" / f"{model}.jsonl"
    bodies = {
        rec.case_id: rec.body
        for rec in (
            Recording.model_validate_json(line)
            for line in path.read_text().splitlines()
            if line.strip()
        )
    }
    missing = [c.id for c in cases if c.id not in bodies]
    if missing:
        raise SuiteError([f"{path.name} has no recording for {case_id}" for case_id in missing])
    return {c.id: parse_screening_reply(bodies[c.id].encode()) for c in cases}


async def screened_results(
    port: ScreeningPort, cases: Sequence[Case]
) -> dict[str, ScreeningResult]:
    return {c.id: await port.screen(ScreenedText.screen(c.text)) for c in cases}


async def _live_results(
    model: AnthropicModelId, cases: Sequence[Case]
) -> dict[str, ScreeningResult]:
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SuiteError(["--screener anthropic is a real, paid run and needs ANTHROPIC_API_KEY"])
    async with httpx.AsyncClient(base_url=ANTHROPIC_BASE_URL, timeout=60.0) as client:
        return await screened_results(
            AnthropicScreener(client, api_key=api_key, model=model), cases
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate cases and refuse groups that straddle splits")
    score_cmd = sub.add_parser("score", help="score one screener on one split")
    score_cmd.add_argument(
        "--screener", choices=("heuristic", "recorded", "anthropic"), required=True
    )
    score_cmd.add_argument("--model", type=AnthropicModelId, default=AnthropicModelId.HAIKU_5_5)
    score_cmd.add_argument("--split", type=Split, default=Split.VALIDATION)
    args = parser.parse_args(argv)

    try:
        suite = load_suite(args.suite)
        if args.command == "check":
            total = sum(len(c) for c in suite.cases.values())
            print(f"{suite.manifest.id}: {total} cases, every group in one split")
            return 0
        cases = suite.cases[args.split]
        if args.screener == "heuristic":
            name, results = "heuristic", asyncio.run(screened_results(HeuristicScreener(), cases))
        elif args.screener == "recorded":
            name, results = (
                f"recorded:{args.model}",
                recorded_results(args.suite, args.model, cases),
            )
        else:
            name, results = str(args.model), asyncio.run(_live_results(args.model, cases))
    except SuiteError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        return _EXIT_INVALID
    print(score(suite, args.split, name, results).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
