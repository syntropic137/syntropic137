"""Tests for scripts/eval_suite.py and the suites it reads (#967 step 8).

The checked-in suite is validated for real: its files must parse, agree with
the workflow they name, and (on a full clone) pin commits that exist and that
the recorded fix descends from. The scorer and the launcher are driven through
an HTTP transport that answers with the API's own response shapes, so a field
the script reads under the wrong name fails here rather than on the owner's
first scored run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eval_suite
import yaml
from eval_suite import (
    DEFAULT_SUITE,
    ROOT,
    CleanCase,
    DefectCase,
    DefinitionError,
    Expected,
    Launch,
    LoadedSuite,
    Score,
    ScoredRun,
    check_commits,
    install_provenance,
    launch_suite,
    load_suite,
    main,
    rates,
    read_launches,
    render,
    score_case,
    score_report,
    score_suite,
    versions_run,
)

from syn_domain.contexts.orchestration import (
    ArchiveWorkflowTemplateCommand,
    CreateWorkflowTemplateHandler,
    WorkflowTemplateAggregate,
    WorkflowTemplateConflictError,
    build_command_from_definition,
)
from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_shared.agents import (
    CODEX_MODEL_IDS,
    ModelId,
    PhaseModelDefaults,
    resolve_codex_model_alias,
    resolve_model_alias,
)
from syn_shared.pricing import resolve_model_pricing


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _copy_suite(tmp_path: Path) -> Path:
    target = tmp_path / "suite"
    shutil.copytree(DEFAULT_SUITE, target)
    return target


# ---------------------------------------------------------------------------
# The checked-in suite
# ---------------------------------------------------------------------------


_CODEX_WF = "eval-verify-pinned-codex-v1"
_SONNET_WF = "eval-verify-pinned-sonnet-v1"
# The four clean controls v6 added (#1774), by source PR.
_V6_CLEAN_PRS = {839, 974, 1104, 1210}
# Codex verifiers pinned to an explicit slug, never an alias: the model
# measured is the one written, whatever `gpt-sol` targets later.
_PINNED_CODEX_WFS = {
    "eval-verify-pinned-codex-gpt-6-luna-v1": "gpt-6-luna",
    "eval-verify-pinned-codex-gpt-5-6-luna-v1": "gpt-5.6-luna",
    "eval-verify-pinned-codex-gpt-5-6-terra-v1": "gpt-5.6-terra",
}


@pytest.mark.unit
def test_the_seed_suite_loads_and_records_its_workflow_and_models() -> None:
    loaded = load_suite(DEFAULT_SUITE)

    assert loaded.tag == "verifier-seed-v1:v6:eval-verify-pinned-v1"
    assert loaded.workflow.id == "eval-verify-pinned-v1"
    assert loaded.workflow.models == {"verify": "opus"}
    by_polarity = {
        polarity: {c.source_pr for c in loaded.cases if c.polarity == polarity}
        for polarity in ("defect", "clean")
    }
    assert by_polarity["defect"] >= {1574, 1649, 1652, 1654, 1679, 1680}
    assert by_polarity["clean"] == {917, 1010} | _V6_CLEAN_PRS
    assert sum(c.polarity == "defect" for c in loaded.cases) == 31
    assert sum(c.polarity == "clean" for c in loaded.cases) == 6


@pytest.mark.unit
def test_the_same_cases_load_under_the_codex_verifier_with_their_own_tag() -> None:
    opus = load_suite(DEFAULT_SUITE)
    codex = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)

    assert codex.workflow.id == _CODEX_WF
    assert codex.workflow.models == {"verify": "gpt-sol"}
    assert codex.tag == f"verifier-seed-v1:v6:{_CODEX_WF}"
    assert codex.tag != opus.tag
    assert codex.cases == opus.cases


@pytest.mark.unit
def test_the_same_cases_load_under_the_sonnet_verifier_with_their_own_tag() -> None:
    opus = load_suite(DEFAULT_SUITE)
    sonnet = load_suite(DEFAULT_SUITE, workflow=_SONNET_WF)

    assert sonnet.workflow.id == _SONNET_WF
    assert sonnet.workflow.models == {"verify": "sonnet"}
    assert sonnet.tag == f"verifier-seed-v1:v6:{_SONNET_WF}"
    assert sonnet.cases == opus.cases


@pytest.mark.unit
@pytest.mark.parametrize(("variant", "slug"), sorted(_PINNED_CODEX_WFS.items()))
def test_the_same_cases_load_under_each_pinned_codex_verifier(variant: str, slug: str) -> None:
    opus = load_suite(DEFAULT_SUITE)
    pinned = load_suite(DEFAULT_SUITE, workflow=variant)

    assert pinned.workflow.models == {"verify": slug}
    assert pinned.tag == f"verifier-seed-v1:v6:{variant}"
    assert pinned.cases == opus.cases


@pytest.mark.unit
@pytest.mark.parametrize("slug", sorted(_PINNED_CODEX_WFS.values()))
def test_each_pinned_codex_slug_is_a_priced_codex_model_and_not_an_alias(slug: str) -> None:
    """What the variant passes to `codex exec --model` is the slug itself, and
    it prices as itself: a run is never costed at the gpt-sol target's rate."""
    assert resolve_model_alias(slug) is None
    assert resolve_codex_model_alias(slug) == slug
    assert ModelId(slug) in CODEX_MODEL_IDS
    pricing = resolve_model_pricing(slug)
    assert pricing is not None
    assert pricing.model_id == slug


@pytest.mark.unit
def test_a_workflow_the_suite_does_not_list_is_refused() -> None:
    with pytest.raises(DefinitionError, match="not one of the suite's"):
        load_suite(DEFAULT_SUITE, workflow="sdlc-reverify-pr-v1")


def _workflow_yaml(relative: str) -> dict[str, object]:
    loaded = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.unit
@pytest.mark.parametrize(
    ("variant", "agent_fields"),
    [
        (_CODEX_WF, ("codex", "gpt-sol", "workspace-write")),
        (_SONNET_WF, ("claude", "sonnet", None)),
        *((wf, ("codex", slug, "workspace-write")) for wf, slug in _PINNED_CODEX_WFS.items()),
    ],
)
def test_each_verify_variant_differs_from_opus_only_in_the_agent(
    variant: str, agent_fields: tuple[str, str, str | None]
) -> None:
    """Same cases, different verifier: a score difference must be the verifier alone."""
    refs = {r.id: r for r in load_suite(DEFAULT_SUITE).suite.workflows}
    assert set(refs) == {"eval-verify-pinned-v1", _CODEX_WF, _SONNET_WF, *_PINNED_CODEX_WFS}
    opus_path, variant_path = refs["eval-verify-pinned-v1"].path, refs[variant].path

    # The prompt files, byte for byte, and the prompt each definition resolves.
    opus_prompt = (ROOT / opus_path).parent / "phases" / "verify.md"
    variant_prompt = (ROOT / variant_path).parent / "phases" / "verify.md"
    assert opus_prompt.read_bytes() == variant_prompt.read_bytes()
    opus_def = WorkflowDefinition.from_file(ROOT / opus_path)
    variant_def = WorkflowDefinition.from_file(ROOT / variant_path)
    assert [p.prompt_template for p in opus_def.phases] == [
        p.prompt_template for p in variant_def.phases
    ]

    # Everything else but identity and the agent block is the same document.
    def comparable(doc: dict[str, object]) -> dict[str, object]:
        rest = {k: v for k, v in doc.items() if k not in ("id", "name", "description")}
        phases = rest["phases"]
        assert isinstance(phases, list)
        rest["phases"] = [
            {k: v for k, v in p.items() if k not in ("agent", "allowed_tools")} for p in phases
        ]
        return rest

    assert comparable(_workflow_yaml(opus_path)) == comparable(_workflow_yaml(variant_path))
    agent = variant_def.phases[0].agent
    assert agent is not None
    assert (agent.provider, agent.model, agent.sandbox) == agent_fields


def _is_shallow() -> bool:
    return _git(ROOT, "rev-parse", "--is-shallow-repository") == "true"


@pytest.mark.skipif(_is_shallow(), reason="a shallow clone does not hold the pinned commits")
@pytest.mark.unit
def test_every_seed_pins_a_real_commit_before_its_fix() -> None:
    assert check_commits(load_suite(DEFAULT_SUITE), ROOT) == []


# ---------------------------------------------------------------------------
# Definition validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_model_change_without_the_suite_record_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    suite_yaml = suite_dir / "suite.yaml"
    suite_yaml.write_text(suite_yaml.read_text().replace("verify: opus", "verify: sonnet"))

    with pytest.raises(DefinitionError, match="the workflow declares"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_a_model_change_in_an_unselected_workflow_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    suite_yaml = suite_dir / "suite.yaml"
    suite_yaml.write_text(suite_yaml.read_text().replace("verify: gpt-sol", "verify: gpt-other"))

    with pytest.raises(DefinitionError, match=f"for {_CODEX_WF}, the workflow declares"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_a_task_that_names_the_source_pr_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "codex-cost-limit.yaml"
    case.write_text(case.read_text().replace("The change under review", "PR #1654"))

    with pytest.raises(DefinitionError, match="names #1654"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_an_abbreviated_sha_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "codex-cost-limit.yaml"
    case.write_text(
        case.read_text().replace("123b25204fce5052f1b0ab494d2c59fa607624ad", "123b25204")
    )

    with pytest.raises(DefinitionError, match="full 40-character"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_a_case_file_must_be_named_for_its_case(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    cases = suite_dir / "cases"
    (cases / "codex-cost-limit.yaml").rename(cases / "renamed.yaml")

    with pytest.raises(DefinitionError, match="file name must be the case id"):
        load_suite(suite_dir)


# ---------------------------------------------------------------------------
# check_commits against a repository built for the purpose
# ---------------------------------------------------------------------------


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A repo with bug -> fix (touching bug.py) -> unrelated (touching other.py)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "bug.py").write_text("broken\n")
    (repo / "other.py").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "bug")
    bug = _git(repo, "rev-parse", "HEAD")
    (repo / "bug.py").write_text("fixed\n")
    _git(repo, "commit", "-qam", "fix")
    fix = _git(repo, "rev-parse", "HEAD")
    (repo / "other.py").write_text("y\n")
    _git(repo, "commit", "-qam", "unrelated")
    unrelated = _git(repo, "rev-parse", "HEAD")
    return repo, bug, fix, unrelated


def _one_case_suite(
    tmp_path: Path, commit: str, fix: str, file: str, first_fix: str | None = None
) -> Path:
    suite_dir = _copy_suite(tmp_path)
    suite_file = suite_dir / "suite.yaml"
    suite = yaml.safe_load(suite_file.read_text())
    suite.pop("history", None)  # it names the real cases, which this suite drops
    suite_file.write_text(yaml.safe_dump(suite))
    cases = suite_dir / "cases"
    for p in cases.glob("*.yaml"):
        p.unlink()
    case: dict[str, object] = {
        "id": "seed",
        "polarity": "defect",
        "source_pr": 1,
        "commit": commit,
        "fix_commit": fix,
        "task": "Review it.",
        "expected": {"files": [file], "keywords": [["broken"]]},
        "split": "train",
    }
    if first_fix is not None:
        case["first_fix_commit"] = first_fix
    (cases / "seed.yaml").write_text(json.dumps(case))
    return suite_dir


@pytest.mark.unit
def test_check_passes_a_pin_its_fix_descends_from(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, _ = history
    assert check_commits(load_suite(_one_case_suite(tmp_path, bug, fix, "bug.py")), repo) == []


@pytest.mark.unit
def test_check_refuses_a_pin_after_its_fix(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, _ = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, fix, bug, "bug.py")), repo)
    assert any("first parent" in p for p in problems)


@pytest.mark.unit
def test_check_refuses_a_pin_that_is_an_older_ancestor_of_the_fix(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    # An ancestor is not enough: the pin must be the tree just before the fix,
    # or the run reviews code the fix never saw (PR #1700 review).
    repo, bug, fix, unrelated = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, bug, unrelated, "bug.py")), repo)
    assert problems == [
        f"seed: pins {bug[:12]}, but the fix {unrelated[:12]}'s first parent is {fix[:12]}; "
        "pin the tree just before the fix"
    ]


@pytest.mark.unit
def test_check_passes_a_pin_before_the_first_commit_of_a_fix_series(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, unrelated = history
    suite = _one_case_suite(tmp_path, bug, unrelated, "bug.py", first_fix=fix)
    assert check_commits(load_suite(suite), repo) == []


@pytest.mark.skipif(_is_shallow(), reason="a shallow clone does not hold the pinned commits")
@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    [c for c in load_suite(DEFAULT_SUITE).cases if isinstance(c, DefectCase)],
    ids=lambda c: c.id,
)
def test_every_committed_defect_pins_its_fixs_first_parent(case: DefectCase) -> None:
    if case.reclassified_from:
        # A reclassified control keeps the pin both verifiers reviewed, before the fix.
        assert eval_suite._git_ok(ROOT, "merge-base", "--is-ancestor", case.commit, case.fix_start)
        assert case.commit != case.fix_start
    else:
        assert _git(ROOT, "rev-parse", f"{case.fix_start}^1") == case.commit


@pytest.mark.unit
def test_check_refuses_a_fix_that_does_not_touch_the_expected_file(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, _, fix, unrelated = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, fix, unrelated, "bug.py")), repo)
    assert problems == ["seed: the fix changes none of ['bug.py']"]


@pytest.mark.unit
def test_check_refuses_a_sha_the_repo_does_not_hold(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, _, _ = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, bug, "f" * 40, "bug.py")), repo)
    assert problems == [f"seed: no such commit {'f' * 40} (try `git fetch origin`)"]


@pytest.mark.unit
def test_check_refuses_a_file_absent_at_the_pin(
    tmp_path: Path, history: tuple[Path, str, str, str]
) -> None:
    repo, bug, fix, _ = history
    problems = check_commits(load_suite(_one_case_suite(tmp_path, bug, fix, "missing.py")), repo)
    assert "seed: missing.py does not exist at " + bug[:12] in problems


# ---------------------------------------------------------------------------
# score_report
# ---------------------------------------------------------------------------

_EXPECTED = Expected(
    files=("packages/syn-adapters/src/syn_adapters/storage/artifact_storage/minio.py",),
    keywords=(("key",), ("404", "not found")),
)


def _report(*blocking: tuple[str, str], non_blocking: str = "None.") -> str:
    """A report in the shape the verify prompt asks for: one block per (file, defect)."""
    blocks = "\n\n".join(
        f"### Finding {n}\n- File: `{file}`\n- Defect: {defect}\n- Why blocking: it ships broken."
        for n, (file, defect) in enumerate(blocking, start=1)
    )
    return (
        f"VERDICT: BLOCKED\n\n## BLOCKING\n\n{blocks or 'None.'}\n\n"
        f"## NON-BLOCKING\n\n{non_blocking}\n"
    )


_FINDING = _report(
    ("minio.py:212", "download() builds the id-only key; upload keys by execution, so reads 404.")
)


@pytest.mark.unit
def test_a_blocked_report_naming_file_and_defect_passes() -> None:
    assert score_report(_EXPECTED, "blocked", _FINDING).passed


@pytest.mark.unit
def test_a_certified_run_fails_even_when_the_report_names_the_defect() -> None:
    score = score_report(_EXPECTED, "certified", _FINDING)
    assert score.matched and not score.passed


@pytest.mark.unit
def test_a_report_that_misses_the_file_does_not_match() -> None:
    report = _report(("storage.py:10", "the object key does not match, so reads 404"))
    score = score_report(_EXPECTED, "blocked", report)
    assert score.named_file is None and not score.passed


@pytest.mark.unit
def test_a_report_missing_a_keyword_group_says_which() -> None:
    score = score_report(_EXPECTED, "blocked", _report(("minio.py", "uses the wrong key")))
    assert score.missing_keywords == (("404", "not found"),) and not score.passed


@pytest.mark.unit
def test_a_benign_mention_beside_an_unrelated_blocker_fails() -> None:
    """The false pass verification found at b80c4a68: the seed's file is named
    only to clear it, and an unrelated blocking defect supplies the verdict."""
    seed = _case("binary-artifact-minio-key").expected
    report = _report(
        ("other.py:40", "the retry loop never backs off, so a 404 from the API is hammered."),
        non_blocking="- minio.py: upload/download key handling looks fine; no mismatch found.",
    )
    score = score_report(seed, "blocked", report)
    assert score.findings == 1 and score.named_file is None and not score.passed


@pytest.mark.unit
def test_the_file_and_the_defect_must_be_in_the_same_blocking_finding() -> None:
    seed = _case("binary-artifact-minio-key").expected
    report = _report(
        ("minio.py:12", "the bucket name is read from an unvalidated setting."),
        ("other.py:40", "the object key does not match the uploaded one, so the read is a 404."),
    )
    score = score_report(seed, "blocked", report)
    assert score.findings == 2 and not score.passed


@pytest.mark.unit
def test_the_seed_file_named_inside_the_defect_counts() -> None:
    """verifier-seed-v1 first run (exec-707cefadabf8): the verifier filed the entry
    point (direct_start.py) and named the root-cause modules in its Defect. That is
    the correct finding and must pass."""
    seed = _case("shared-esp-stream").expected
    report = (
        "VERDICT: BLOCKED\n\n## BLOCKING\n\n### Finding 1\n"
        "- File: `apps/syn-api/src/syn_api/routes/executions/direct_start.py:48`\n"
        "- Defect: The ExecutionRequest is written under aggregate id = the execution id "
        "(`RequestExecutionCommand.aggregate_id` returns `execution_id`, "
        "`RequestExecutionCommand.py:35-37`). The WorkflowExecution uses the same aggregate id. "
        "The production store keys a stream by aggregate id alone, so `ExecutionRequest-exec-X` and "
        "`WorkflowExecution-exec-X` are one stream; the start's NO_STREAM append conflicts, "
        "it is treated as a duplicate and every direct start silently never runs.\n"
        "- Why blocking: breaks POST /execute.\n"
    )
    score = score_report(seed, "blocked", report)
    assert score.named_file is not None, score
    assert score.passed, score


@pytest.mark.unit
def test_a_seed_file_named_only_in_why_blocking_does_not_count() -> None:
    """Codex review at 70fbbb14: the seed file appears only in another finding's
    'Why blocking' text. File and defect must come from the File and Defect fields."""
    seed = _case("binary-artifact-minio-key").expected
    report = (
        "VERDICT: BLOCKED\n\n## BLOCKING\n\n### Retry loop\n\n"
        "- File: `other.py:40`\n"
        "- Defect: retry loop hammers the API on 404.\n"
        "- Why blocking: outage risk. minio.py key handling looks fine; no mismatch found.\n"
    )
    score = score_report(seed, "blocked", report)
    assert score.findings == 1 and score.named_file is None and not score.passed


@pytest.mark.unit
def test_a_non_blocking_subsection_nested_under_blocking_is_not_a_finding() -> None:
    """Codex review at 70fbbb14: '### NON-BLOCKING' under '## BLOCKING' was read as
    another blocking finding, so a benign mention there passed."""
    seed = _case("binary-artifact-minio-key").expected
    report = (
        "VERDICT: BLOCKED\n\n## BLOCKING\n\n### Retry loop\n\n"
        "- File: `other.py:40`\n- Defect: retry loop hammers the API.\n- Why blocking: outage.\n\n"
        "### NON-BLOCKING\n\n"
        "- File: `minio.py:212`\n- Defect: object key does not match the uploaded key, so reads 404 not found.\n"
        "- Why blocking: n/a, looks fine.\n"
    )
    score = score_report(seed, "blocked", report)
    assert score.findings == 1 and score.named_file is None and not score.passed


@pytest.mark.unit
def test_prose_under_blocking_outside_a_finding_block_is_not_a_finding() -> None:
    report = (
        "VERDICT: BLOCKED\n\n## BLOCKING\n\n"
        "minio.py:212 download() builds the id-only key, so reads 404.\n"
    )
    score = score_report(_EXPECTED, "blocked", report)
    assert score.findings == 0 and not score.passed


@pytest.mark.unit
def test_a_hash_line_in_a_code_fence_does_not_end_the_finding() -> None:
    report = _report(
        (
            "minio.py:212",
            "download() builds the id-only key:\n\n```python\n# id only\n```\n\nso reads 404.",
        )
    )
    assert score_report(_EXPECTED, "blocked", report).passed


@pytest.mark.unit
def test_a_longer_file_name_ending_in_the_seed_file_does_not_name_it() -> None:
    report = _report(("test_minio.py:5", "the fixture key does not match, so reads 404."))
    assert score_report(_EXPECTED, "blocked", report).named_file is None


def _case(case_id: str) -> DefectCase:
    return next(
        c for c in load_suite(DEFAULT_SUITE).cases if isinstance(c, DefectCase) and c.id == case_id
    )


# Natural, correct descriptions of each seed's defect, worded independently of
# the keyword tables - including the three per seed the verification probe at
# ca52f38c wrote, of which the scorer then passed 1 in 12. Each must pass.
_PARAPHRASES: dict[str, tuple[tuple[str, str], ...]] = {
    "binary-artifact-minio-key": (
        (
            "minio.py:212",
            "upload() stores the blob under an execution-scoped object name, but download() asks "
            "for the bare artifact ID, so the binary content is never read back.",
        ),
        (
            "artifact_storage/minio.py",
            "the reader asks MinIO for a different object than the writer created, so production "
            "returns NoSuchKey for every binary artifact.",
        ),
        (
            "minio.py:198-230",
            "the read path discards the execution prefix the write path added, and cannot "
            "retrieve the blob it just stored.",
        ),
        (
            "minio.py",
            "the key computed on upload and the key computed on download disagree, so the "
            "content endpoint answers 404 for binary artifacts.",
        ),
    ),
    "codex-cost-limit": (
        (
            "CodexStreamProcessor.py",
            "Codex supplies token usage only when execution finishes; max_cost_usd is checked "
            "after all spending has occurred.",
        ),
        (
            "CodexStreamProcessor.py:88",
            "token totals are emitted at completion, so the cap cannot interrupt a Codex phase "
            "that is running over budget.",
        ),
        (
            "syn_shared/agents.py:41",
            "for codex the consumption is revealed at shutdown, after the budget is already "
            "exceeded; the limit is declared but never enforced.",
        ),
        (
            "CodexStreamProcessor.py:120",
            "the Codex CLI reports usage once, in turn.completed, so a running cost never exists "
            "to compare against the limit.",
        ),
    ),
    "execution-id-as-eval-id": (
        (
            "eval_admission.py:52",
            "an execution ID loaded as an Eval reads the execution's stream, so an existing "
            "execution makes an absent eval seem present.",
        ),
        (
            "EvalAggregate.py",
            "a workflow run ID used as an eval ID loads that run's events, and those unrelated "
            "events satisfy the existence check.",
        ),
        (
            "eval_edit.py:30",
            "the store hands back execution events, which are replayed as an eval that never had "
            "an EvalCreated event, and the attach is accepted.",
        ),
    ),
    "live-commits-unvalidated-sha": (
        (
            "useEventFeed.ts:62",
            "toGitCommit accepts any non-empty string as the sha, so a payload whose sha is "
            "'???????' is rendered as-is - the very placeholder the change set out to remove.",
        ),
        (
            "hooks/useEventFeed.ts",
            "the commit hash is never checked to be hex, so garbage such as '???????' or "
            "whitespace still shows up on the Live Commits card.",
        ),
        (
            "useEventFeed.ts",
            "text() treats any truthy string as a commit id; a malformed sha is displayed "
            "instead of the event being dropped.",
        ),
    ),
    "repo-privacy-ignores-app": (
        (
            "useRepoList.ts:68",
            "isPrivate comes from the stored is_private ?? false and the App's answer is "
            "discarded, so a private repository is shown as public.",
        ),
        (
            "useRepoList.ts",
            "registeredRow ignores the GitHub App entry it already matched; the CLI registers "
            "every repo with is_private false, so private repos render without their lock.",
        ),
        (
            "src/hooks/useRepoList.ts",
            "the row's visibility comes from the registration record, never from GitHub's live "
            "answer, so the page displays a private repo as public.",
        ),
    ),
    "shared-esp-stream": (
        (
            "RequestExecutionCommand.py:22",
            "the request and the workflow execution are written to the same event stream, so the "
            "second aggregate collides with the first.",
        ),
        (
            "ExecutionRequestAggregate.py",
            "both records reuse one stream identifier, and the request's events contaminate the "
            "execution's state when it is loaded.",
        ),
        (
            "ExecutionRequestAggregate.py:15",
            "the request and the run occupy one stream, and the second write conflicts on the "
            "expected version, so the start is dropped.",
        ),
        (
            "RequestExecutionCommand.py",
            "aggregate_id is the execution_id, and ESP keys streams by id alone, so the two "
            "aggregates share a stream.",
        ),
    ),
    "transcript-superseded-revision-issues": (
        (
            "session_relationship_resolver.py:210",
            "an unresolved_spawn gap reported by an earlier revision of the transcript is kept "
            "after a later revision resolved the Agent call, so the session reads incomplete.",
        ),
        (
            "session_relationship_resolver.py",
            "issues from older archived revisions are never dropped once superseded, so coverage "
            "is reported missing for a fully accounted run.",
        ),
        (
            "agent_sessions/domain/services/session_relationship_resolver.py",
            "the resolver only filters inactive evidence; a stale revision's issue survives the "
            "revision that fixed it and marks the session incomplete.",
        ),
    ),
    "codex-turn-failed-reason-dropped": (
        (
            "CodexStreamProcessor.py:300",
            "turn.failed events are never dispatched, so the reason codex gave is thrown away "
            "and the phase reports the generic missing terminal turn message.",
        ),
        (
            "CodexStreamProcessor.py",
            "the parser has no branch for the error event type or a failed turn; the message "
            "codex sent is lost and the operator sees only that the stream ended.",
        ),
        (
            "execute_workflow/CodexStreamProcessor.py:260",
            "a turn failed event is unhandled: its error.message is discarded instead of "
            "becoming the phase's error reason.",
        ),
    ),
    "cli-packages-own-remote-check": (
        (
            "install.ts:140",
            "packagesCommand decides whether a source is remote with its own inline predicate "
            "instead of parseSource, so it can disagree with install and update.",
        ),
        (
            "commands/workflow/install.ts",
            "a second, divergent remote check: a URL the resolver treats as remote can be "
            "treated as a local path here and hidden as missing.",
        ),
        (
            "install.ts",
            "the listing duplicates the resolver's notion of a remote source rather than "
            "calling parseSource, and the two drift apart on shorthand.",
        ),
    ),
    "github-token-first-installation": (
        (
            "WorkspaceProvisionHandler.py:259",
            "the token is minted for installations[0], the first installation, not the one "
            "that owns the repo under work, so gh gets a token for the wrong org.",
        ),
        (
            "WorkspaceProvisionHandler.py",
            "_resolve_github_app_token assumes a single org and takes an arbitrary installation; "
            "with two organizations the agent cannot read its own repository.",
        ),
        (
            "handlers/WorkspaceProvisionHandler.py:250",
            "the GITHUB_TOKEN ignores which owner the repo belongs to and always uses the first "
            "App installation.",
        ),
    ),
    "codex-deliverable-phase-failed": (
        (
            "AgentExecutionHandler.py:231",
            "any codex error_reason becomes a non-zero exit, even when the phase already wrote "
            "its deliverable to artifacts/output, so finished work is failed.",
        ),
        (
            "AgentExecutionHandler.py",
            "a codex stream that ends without turn.completed fails the phase although it "
            "produced its output; the handler never checks for the artifact.",
        ),
        (
            "handlers/AgentExecutionHandler.py:225",
            "the phase is marked failed on a missing terminal turn after it completed its work; "
            "the deliverable is discarded.",
        ),
    ),
    "codex-brace-line-protocol-fault": (
        (
            "CodexStreamProcessor.py:490",
            "any line that starts with { and fails json.loads sets error_reason immediately, so "
            "a TSX line the agent echoed fails an otherwise successful phase.",
        ),
        (
            "CodexStreamProcessor.py",
            "stdout carries the agent's own subprocess output, but a brace-leading line that "
            "does not parse is treated as a protocol fault and the phase fails.",
        ),
        (
            "execute_workflow/CodexStreamProcessor.py:484",
            "startswith('{') is taken as proof of a protocol event; a malformed echo from the "
            "agent output is recorded as a fault and the run exits non-zero.",
        ),
    ),
    "repo-name-collision-skipped-clone": (
        (
            "setup_phase_secrets.py:456",
            "two repositories with the same bare name from different orgs map to one directory; "
            "the [ -d ] guard skips the second clone silently.",
        ),
        (
            "setup_phase_secrets.py",
            "the destination is derived from the repo name alone, so a collision leaves the "
            "phase working in the wrong repository without any error.",
        ),
        (
            "workspace_backends/service/setup_phase_secrets.py:440",
            "acme/api and other/api collide on /workspace/repos/api and the idempotency guard "
            "means the second is never cloned.",
        ),
    ),
    "sessions-execution-filter-dropped": (
        (
            "sessions.py:40",
            "the list route declares no execution_id query parameter, so FastAPI drops it "
            "silently and the whole collection comes back.",
        ),
        (
            "routes/sessions.py",
            "filtering sessions by execution id is ignored: the parameter is not declared and "
            "every session is returned.",
        ),
        (
            "sessions.py",
            "GET /sessions?execution_id=... returns all sessions, unfiltered, because the route "
            "has no such filter.",
        ),
    ),
    "artifacts-execution-filter-dropped": (
        (
            "artifacts.py:60",
            "list_artifacts has no execution_id parameter; FastAPI drops it silently, so a "
            "phase asking for its run's deliverable gets the most recent artifact of any run.",
        ),
        (
            "routes/artifacts.py",
            "the execution id filter is not declared and the rows carry none, so the query "
            "returns every artifact unfiltered.",
        ),
        (
            "artifacts.py",
            "asking for one execution's artifacts is ignored: the filter is missing and the "
            "answer is all artifacts.",
        ),
    ),
    "executions-total-is-page-length": (
        (
            "queries.py:80",
            "total is set to len(domain_summaries), the page length, not the collection size, "
            "so clients believe they have every execution.",
        ),
        (
            "executions/queries.py",
            "the response's total equals page_size whenever the page is full; it never counts "
            "the projection.",
        ),
        (
            "queries.py",
            "total reports the number of returned rows rather than the count of executions, so "
            "paging stops after the first page.",
        ),
    ),
    "github-shorthand-any-slash": (
        (
            "resolver.ts:94",
            "isGitHubShorthand accepts any string with a slash, so a local path like "
            "~/workflows/foo is treated as owner/repo shorthand and cloned from GitHub.",
        ),
        (
            "packages/resolver.ts",
            "the shorthand check never validates two segments: a nested path such as a/b/c "
            "is resolved as a github repository.",
        ),
        (
            "resolver.ts",
            "any source containing a slash is taken as GitHub shorthand; a home-relative path "
            "is never treated as local.",
        ),
    ),
    "guard-moved-gitlink-unsaved-work": (
        (
            "unpushed_work_guard.py:595",
            "every status --porcelain line counts as unsaved work, including a submodule "
            "gitlink that a checkout moved, so finished phases are failed.",
        ),
        (
            "unpushed_work_guard.py",
            "a submodule pointer moved by git checkout without --recurse-submodules looks "
            "identical to an edited submodule and is falsely reported as unpushed work.",
        ),
        (
            "execute_workflow/unpushed_work_guard.py",
            "' M lib/sub' for a submodule a checkout moved is not edited work, but the guard reads "
            "every line of the porcelain as unsaved and refuses the phase.",
        ),
    ),
    "declared-skills-not-invocable": (
        (
            "ExecuteWorkflowHandler.py:540",
            "a phase that declares skills and scopes its allowed tools never gets the Skill "
            "tool, so its skills are installed but cannot be invoked.",
        ),
        (
            "ExecuteWorkflowHandler.py",
            "Skill is not granted when a phase restricts its tools: the declared skills are "
            "withheld because the tool list omits Skill.",
        ),
        (
            "execute_workflow/ExecuteWorkflowHandler.py",
            "the handler resolves the phase's skills but leaves the tool list as declared, so "
            "skill invocation is unavailable to the agent.",
        ),
    ),
    "redis-retry-non-idempotent": (
        (
            "redis_client.py:32",
            "retry_on_timeout=True re-sends a command Redis may already have applied; GETDEL "
            "and SET NX are not idempotent, so the retry loses the signal or reports a duplicate.",
        ),
        (
            "control/adapters/redis_adapter.py:76",
            "check_signal uses getdel under a client that retries on timeout: if the first "
            "attempt deleted the key and the reply was lost, the retry returns nothing and the "
            "cancel signal is dropped.",
        ),
        (
            "dedup/redis_dedup.py",
            "the SET NX claim is retried after a timeout; the first attempt already set the "
            "key, so the retry sees it and the first delivery is treated as a duplicate.",
        ),
    ),
    "redis-url-password-logged": (
        (
            "_wiring.py:846",
            "the controller logs the REDIS_URL verbatim at startup, so the Redis password "
            "appears in docker logs and the rotating log files.",
        ),
        (
            "_wiring.py",
            "redis_url is written to logger.info unredacted; its credential leaks into every "
            "log sink.",
        ),
        (
            "syn_api/_wiring.py",
            "the signal queue log line prints redis://:<password>@redis:6379 in plaintext.",
        ),
    ),
    "token-injector-get-post-only": (
        (
            "token_injector.py:117",
            "only do_GET and do_POST are defined, so an ext_authz check for a PUT, PATCH or "
            "DELETE gets a 501 and the agent's request is denied.",
        ),
        (
            "token_injector.py",
            "the authz handler answers GET and POST only; any other method is unhandled and "
            "the request to GitHub fails.",
        ),
        (
            "docker/token-injector/token_injector.py",
            "a DELETE to the GitHub API is rejected because the check service has no handler "
            "for that HTTP verb.",
        ),
    ),
    "workflow-run-task-undeliverable": (
        (
            "run.ts:195",
            "a -t task is sent even when no phase prompt references $ARGUMENTS or {{task}}, so "
            "the task is silently dropped and the run reports success.",
        ),
        (
            "commands/workflow/run.ts",
            "the CLI accepts a task no phase consumes; it is ignored by every prompt and the "
            "user is never told.",
        ),
        (
            "run.ts",
            "the task is undeliverable when the workflow's prompts have no {{task}} "
            "placeholder, yet the execution starts as if it was used.",
        ),
    ),
    "workflow-run-inputs-go-nowhere": (
        (
            "run.ts:180",
            "-i inputs that no phase references are sent and silently ignored; there is no "
            "warning, not even under --dry-run.",
        ),
        (
            "commands/workflow/run.ts",
            "a -R repo or an input no phase consumes goes nowhere and the CLI gives no warning.",
        ),
        (
            "run.ts",
            "unconsumed input values are dropped at dispatch without telling the user; the "
            "dry-run preview lists them as if they were used.",
        ),
    ),
    "input-alias-independent-resolution": (
        (
            "ArtifactCollector.py:232",
            "the flat <phase-id>.md alias and the nested tree are resolved independently by "
            "_resolve_phase_outputs and _resolve_phase_files, so they can disagree.",
        ),
        (
            "ArtifactCollector.py",
            "two separate lookups populate the flat alias and the input tree; one can find the "
            "output and the other not, leaving them out of sync.",
        ),
        (
            "execute_workflow/ArtifactCollector.py:240",
            "the alias is not derived from the resolved file tree, so a phase can receive a "
            "tree with no flat alias - an inconsistent input.",
        ),
    ),
    "shared-body-expired-by-oldest-capture": (
        (
            "body_retention.py:67",
            "age expiry selects each capture older than the retention age and tombstones its "
            "archive, so a shared body is erased while a recent capture still references it.",
        ),
        (
            "body_retention.py",
            "a content-addressed object is judged by its oldest capture; expiring that one "
            "deletes bytes another, newer capture needs.",
        ),
        (
            "session_inventory/body_retention.py",
            "retention expires the object as soon as any capture of it is old, not when every "
            "referencing capture has aged out.",
        ),
    ),
    "executions-enrichment-fetched-twice": (
        (
            "queries.py:642",
            "the list endpoint calls _load_execution_enrichment twice per request for the same "
            "ids, doubling the cost lookups.",
        ),
        (
            "queries.py:329",
            "the enrichment loader awaits get_execution_cost once per execution id in a loop - "
            "an N+1 query on every list request.",
        ),
        (
            "executions/queries.py",
            "cost enrichment is fetched one id at a time, and then fetched again by the "
            "endpoint, a redundant duplicate load.",
        ),
    ),
    "prompt-claims-checkout-without-clone": (
        (
            "workspace_prompt.py:29",
            "the prompt always says repos/ holds pre-cloned repositories, even for a phase with "
            "clone_repos: false, so the agent navigates into a directory that does not exist.",
        ),
        (
            "workspace_prompt.py",
            "SYN_WORKSPACE_PROMPT is an unconditional constant: a phase that is not cloned is "
            "still told to start in /workspace/repos/<name>.",
        ),
        (
            "execute_workflow/workspace_prompt.py:50",
            "with clone_repos disabled the instructions are false - they claim a checkout is on "
            "disk and tell the agent to navigate to it.",
        ),
    ),
    "heatmap-test-reads-clock-repeatedly": (
        (
            "test_heatmap_canonical_usage_source.py:114",
            "_utc_today() reads the clock again on every call, so a test that records before "
            "midnight and queries after it looks in a different day and fails.",
        ),
        (
            "test_heatmap_canonical_usage_source.py",
            "the write and the query each compute now() separately; across the UTC day "
            "boundary the bucket assertion finds no bucket - a flaky test.",
        ),
        (
            "tests/integration/test_heatmap_canonical_usage_source.py:138",
            "start, end and the expected bucket each re-read the date, so they can disagree "
            "when the date changes mid-test.",
        ),
    ),
    "pit-stop-password-on-argv": (
        (
            "pit_stop.sh:69",
            "curl is given -u admin:$SYN_API_PASSWORD on its command line, so the password is "
            "visible in the process list to anyone on the host.",
        ),
        (
            "pit_stop.sh",
            "the API credential is passed as a curl argument, which exposes it in "
            "/proc/<pid>/cmdline while each request runs.",
        ),
        (
            "scripts/pit_stop.sh:398",
            "api_post puts the secret in argv; it should reach curl via stdin or a config file.",
        ),
    ),
    "prompt-deliverable-only-if-acted": (
        (
            "workspace_prompt.py:116",
            "the prompt only asks for deliverable.md after making changes; a phase that "
            "finds nothing to do writes no artifact and the collector fails it.",
        ),
        (
            "workspace_prompt.py",
            "the completion instructions never cover a phase that declined to act or found the "
            "work already done, so it exits with no output and is failed.",
        ),
        (
            "execute_workflow/workspace_prompt.py:100",
            "writing the deliverable reads as conditional on having acted; when no change was "
            "needed the agent writes nothing to artifacts/output/.",
        ),
    ),
}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case_id", "file", "defect"),
    [(case, file, defect) for case, found in _PARAPHRASES.items() for file, defect in found],
)
def test_a_natural_correct_finding_passes(case_id: str, file: str, defect: str) -> None:
    seed = _case(case_id).expected
    report = _report(("other.py:3", "an unrelated defect."), (file, defect))
    score = score_report(seed, "blocked", report)
    assert score.passed, score


@pytest.mark.unit
def test_every_seed_has_at_least_three_paraphrases() -> None:
    defects = {c.id for c in load_suite(DEFAULT_SUITE).cases if c.polarity == "defect"}
    assert defects == set(_PARAPHRASES)
    assert all(len(found) >= 3 for found in _PARAPHRASES.values())


# Blocking findings that name a seed's file but describe a different defect.
_WRONG_DEFECTS: dict[str, tuple[str, str]] = {
    "redis-retry-non-idempotent": (
        "redis_client.py:30",
        "the socket timeout is read from a hard-coded constant instead of settings.",
    ),
    "binary-artifact-minio-key": (
        "minio.py:12",
        "the bucket name is read from an unvalidated setting.",
    ),
    "codex-cost-limit": (
        "CodexStreamProcessor.py:30",
        "a malformed JSON line raises instead of being logged.",
    ),
    "execution-id-as-eval-id": (
        "EvalAggregate.py:70",
        "archive does not check the caller's permission.",
    ),
    # The other defect the same fix closed: a true finding, not this seed's.
    "live-commits-unvalidated-sha": (
        "useEventFeed.ts:120",
        "the row key is built from the array index, so prepending a live event remounts every "
        "row and drops keyboard focus.",
    ),
    "repo-privacy-ignores-app": (
        "useRepoList.ts:58",
        "rows are keyed by full name alone, so two organizations registering the same name "
        "collapse into one row.",
    ),
    "shared-esp-stream": (
        "ExecutionRequestAggregate.py:9",
        "the request's priority field is never validated.",
    ),
}


@pytest.mark.unit
@pytest.mark.parametrize(("case_id", "found"), list(_WRONG_DEFECTS.items()))
def test_the_seed_file_with_a_different_defect_fails(case_id: str, found: tuple[str, str]) -> None:
    score = score_report(_case(case_id).expected, "blocked", _report(found))
    assert score.named_file is not None and not score.passed, score


@pytest.mark.unit
@pytest.mark.parametrize("case_id", list(_PARAPHRASES))
def test_a_correct_finding_outside_blocking_fails(case_id: str) -> None:
    file, defect = _PARAPHRASES[case_id][0]
    # The same structured finding the BLOCKING section would pass on, second,
    # after an unrelated blocking one: only the heading keeps it out.
    matching = f"### Finding 2\n- File: `{file}`\n- Defect: {defect}\n- Why blocking: it may."
    report = _report(("other.py:3", "an unrelated defect."), non_blocking=matching)
    assert not score_report(_case(case_id).expected, "blocked", report).passed
    promoted = _report(("other.py:3", "an unrelated defect."), (f"{file}", defect))
    assert score_report(_case(case_id).expected, "blocked", promoted).passed


# ---------------------------------------------------------------------------
# score_suite and launch_suite against the API's response shapes
# ---------------------------------------------------------------------------

_CASE = "binary-artifact-minio-key"
_PIN = "b2f680f00b4e154b94fa4802a92ead30429e7b98"
_WF = "eval-verify-pinned-v1"


@dataclass(frozen=True)
class _ServedPhase:
    phase_id: str
    prompt_template: str | None
    model: str


def _phases_of(loaded: LoadedSuite) -> list[_ServedPhase]:
    """The phases the server would serve back for the checked-in workflow."""
    local = WorkflowDefinition.from_file(ROOT / loaded.workflow.path)
    return [
        _ServedPhase(p.id, p.prompt_template, loaded.workflow.models[p.id]) for p in local.phases
    ]


class _Server:
    """A fresh API server: no workflow installed until `/workflows/from-yaml` installs one.

    `eval-1` pins the case's commit and holds `exec-1` (launched) and, when
    `attached` is set, `exec-attached`: a blocked run with a matching report
    that was attached afterwards, as the API allows without copying the baseline.
    """

    def __init__(
        self,
        loaded: LoadedSuite,
        *,
        attached: bool = False,
        served_phases: list[_ServedPhase] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.installed: str | None = None
        self.phases = served_phases if served_phases is not None else _phases_of(loaded)
        self.attached = attached
        self.case = _CASE
        """The case `eval-1` is tagged with; `eval_pin` must be its commit."""
        self.eval_pin = _PIN
        self.verdict = "blocked"
        """The review verdict `exec-1` reports."""
        self.run_workflow = loaded.workflow.id
        self.tag = loaded.suite.suite_tag
        self.existing = False
        """When set, every case already has its stable eval `eval-<pin[:6]>`."""
        self.scores: list[tuple[str, dict[str, object]]] = []

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://api", transport=httpx.MockTransport(self.handle))

    def _execution(self, run_id: str) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "workflow_execution_id": run_id,
                "workflow_id": self.run_workflow,
                "workflow_name": "w",
                "status": "completed",
                "review_verdict": self.verdict,
                "total_cost_usd": "3.75",
                "total_duration_seconds": 640.2,
                "unknown_duration_phase_count": 0,
                "total_input_tokens": 1,
                "total_output_tokens": 1,
                "total_cache_creation_tokens": 0,
                "total_cache_read_tokens": 0,
                "total_tokens": 2,
                "artifact_ids": ["art-1"],
                "phases": [
                    {
                        "phase_id": "verify",
                        "name": "v",
                        "status": "completed",
                        "artifact_id": "art-1",
                        "model": "claude-opus-5-5",
                        "requested_model": "opus",
                    }
                ],
            },
        )

    def _eval(self) -> dict[str, object]:
        return {
            "eval_id": "eval-1",
            "name": "n",
            "goal": "g",
            "starting_workflow_id": None,
            "tags": [self.tag, f"case:{self.case}"],
            "frozen": True,
            "archived": False,
            "created_at": None,
            "updated_at": None,
            "run_count": 1,
            "run_status_counts": {"completed": 1},
            "baseline_repos": [
                {
                    "repository": "syntropic137/syntropic137",
                    "requested_ref": self.eval_pin,
                    "commit_sha": self.eval_pin,
                }
            ],
        }

    def _stable(self, case_id: str) -> dict[str, object]:
        pin = next(c.commit for c in load_suite(DEFAULT_SUITE).cases if c.id == case_id)
        return {
            "eval_id": f"eval-{pin[:6]}",
            "tags": [self.tag, f"case:{case_id}"],
            "baseline_repos": [
                {"repository": "syntropic137/syntropic137", "requested_ref": pin, "commit_sha": pin}
            ],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/workflows/from-yaml":
            definition = WorkflowDefinition.from_yaml(request.content.decode())
            self.installed = definition.id
            return httpx.Response(
                201,
                json={
                    "id": definition.id,
                    "name": definition.name,
                    "workflow_type": "custom",
                    "classification": "standard",
                    "repository_url": "",
                    "requires_repos": True,
                    "status": "created",
                    "warnings": [],
                },
            )
        if path.startswith("/workflows/") and request.method == "GET":
            if path != f"/workflows/{self.installed}":
                return httpx.Response(404, json={"detail": "Workflow not found"})
            return httpx.Response(
                200,
                json={
                    "id": self.installed,
                    "name": "w",
                    "workflow_type": "custom",
                    "classification": "standard",
                    "requires_repos": True,
                    "phases": [asdict(p) for p in self.phases],
                },
            )
        if request.method == "POST" and path.endswith("/score"):
            self.scores.append((path, json.loads(request.content)))
            return httpx.Response(200, json={})
        if request.method == "POST" and path == "/evals":
            body = json.loads(request.content)
            pin = body["baseline_repos"][0]["requested_ref"]
            return httpx.Response(
                200,
                json={
                    "eval_id": f"eval-{pin[:6]}",
                    "name": body["name"],
                    "goal": body["goal"],
                    "starting_workflow_id": body.get("starting_workflow_id"),
                    "tags": body["tags"],
                    "baseline_repos": [
                        {
                            "repository": "syntropic137/syntropic137",
                            "requested_ref": pin,
                            "commit_sha": pin,
                        }
                    ],
                },
            )
        if request.method == "POST" and path.endswith("/execute"):
            # The real route 404s when the workflow repository has no such id.
            if path != f"/workflows/{self.installed}/execute":
                return httpx.Response(404, json={"detail": "Workflow not found"})
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "execution_id": f"exec-for-{body['eval_id']}",
                    "workflow_id": self.installed,
                },
            )
        if path == "/evals":
            # The real list filters by tag: another verifier's tag finds nothing.
            tags = set(request.url.params.get_list("tag"))
            # `eval-1` is what `score` finds. A launch installs first and, on
            # this fresh server, finds no case eval unless `existing` is set.
            scoring = self.installed is None
            evals = [self._eval()] if scoring and tags == {self.tag, f"case:{self.case}"} else []
            if self.existing and self.tag in tags:
                evals = [self._stable(t.removeprefix("case:")) for t in tags if t != self.tag]
            return httpx.Response(
                200,
                json={
                    "total": len(evals),
                    "page": 1,
                    "page_size": 200,
                    "status_counts": {},
                    "evals": evals,
                },
            )
        if path == "/evals/eval-1":
            return httpx.Response(200, json=self._eval())
        if path == "/evals/eval-1/runs":
            ids = ["exec-1"] + (["exec-attached"] if self.attached else [])
            return httpx.Response(
                200,
                json={
                    "total": len(ids),
                    "page": 1,
                    "page_size": 200,
                    "items": [
                        {
                            "execution_id": i,
                            "workflow_id": _WF,
                            "status": "completed",
                            "models": [{"phase_id": "verify", "model": "claude-opus-5-5"}],
                        }
                        for i in ids
                    ],
                },
            )
        if path in ("/executions/exec-1", "/executions/exec-attached"):
            return self._execution(path.rsplit("/", 1)[1])
        if path == "/artifacts/art-1/content":
            return httpx.Response(
                200,
                json={
                    "artifact_id": "art-1",
                    "content": _FINDING,
                    "content_type": "text/markdown",
                    "size_bytes": 10,
                },
            )
        return httpx.Response(404, json={"detail": path})


def _launched(loaded: LoadedSuite) -> Launch:
    return Launch(
        suite=loaded.tag,
        case=_CASE,
        eval_id="eval-1",
        run_id="exec-1",
        commit=_PIN,
        workflow_id=loaded.workflow.id,
    )


_LAUNCHED = _launched(load_suite(DEFAULT_SUITE))


@pytest.mark.unit
def test_score_reads_verdict_report_cost_and_model_from_the_api() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)
    rows, unrecorded = score_suite(loaded, server.client(), [_LAUNCHED])

    scored = [r for r in rows if r.case == _CASE]
    assert len(scored) == 1
    row = scored[0]
    assert row.run_id == "exec-1"
    assert row.score is not None and row.score.verdict == "blocked" and row.score.passed
    assert row.cost_usd == Decimal("3.75")
    assert row.models == "verify=claude-opus-5-5"
    assert {r.status for r in rows if r.case != _CASE} == {"not launched"}
    assert unrecorded == ()

    table = render(loaded, rows)
    assert "exec-1" in table and "PASS" in table and "$3.75" in table and "1/37 passed" in table


@pytest.mark.unit
def test_an_attached_run_with_a_matching_blocked_report_is_never_scored() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded, attached=True)
    rows, unrecorded = score_suite(loaded, server.client(), [_LAUNCHED])

    assert [r.run_id for r in rows if r.score] == ["exec-1"]
    assert all(r.run_id != "exec-attached" for r in rows)
    assert len(unrecorded) == 1 and unrecorded[0].startswith("exec-attached")


@pytest.mark.unit
def test_a_tagged_eval_run_with_no_launch_record_does_not_pass() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    rows, unrecorded = score_suite(loaded, _Server(loaded).client(), [])

    assert not any(r.score and r.score.passed for r in rows)
    assert {r.status for r in rows} == {"not launched"}
    assert unrecorded and unrecorded[0].startswith("exec-1")


@pytest.mark.unit
def test_a_launched_run_whose_eval_pins_another_commit_is_rejected() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)
    server.eval_pin = "0" * 40
    rows, _ = score_suite(loaded, server.client(), [_LAUNCHED])

    row = next(r for r in rows if r.case == _CASE)
    assert row.score is None and row.status.startswith("rejected: eval eval-1 pins")


@pytest.mark.unit
def test_a_launched_run_of_another_workflow_is_rejected() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)
    server.run_workflow = "sdlc-reverify-pr-v1"
    rows, _ = score_suite(loaded, server.client(), [_LAUNCHED])

    row = next(r for r in rows if r.case == _CASE)
    assert row.score is None and row.status.startswith("rejected: ran workflow")


@pytest.mark.unit
def test_launch_on_a_fresh_server_installs_the_workflow_before_any_eval(tmp_path: Path) -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)
    ledger = tmp_path / "launches.jsonl"
    lines = launch_suite(loaded, server.client(), ledger)

    paths = [(r.method, r.url.path) for r in server.requests]
    assert paths[0] == ("POST", "/workflows/from-yaml")
    assert paths[1] == ("GET", f"/workflows/{_WF}")
    assert "prompt_file" not in server.requests[0].content.decode()
    creates = [
        json.loads(r.content)
        for r in server.requests
        if r.method == "POST" and r.url.path == "/evals"
    ]
    starts = [json.loads(r.content) for r in server.requests if r.url.path.endswith("/execute")]
    assert [c["baseline_repos"][0]["requested_ref"] for c in creates] == [
        c.commit for c in loaded.cases
    ]
    assert [c["tags"] for c in creates] == [["suite:verifier-seed", c.tag] for c in loaded.cases]
    assert all(s["tags"] == ["suite-version:6", f"verifier:{_WF}"] for s in starts)
    assert [s["eval_id"] for s in starts] == [f"eval-{c.commit[:6]}" for c in loaded.cases]
    assert len(lines) == 1 + len(loaded.cases)

    recorded = read_launches(ledger)
    assert [(x.case, x.commit, x.eval_id, x.run_id) for x in recorded] == [
        (c.id, c.commit, f"eval-{c.commit[:6]}", f"exec-for-eval-{c.commit[:6]}")
        for c in loaded.cases
    ]
    assert {x.workflow_id for x in recorded} == {_WF}


@pytest.mark.unit
def test_launch_creates_no_eval_when_the_server_definition_differs(tmp_path: Path) -> None:
    loaded = load_suite(DEFAULT_SUITE)
    phases = _phases_of(loaded)
    phases[0] = replace(phases[0], model="sonnet")
    server = _Server(loaded, served_phases=phases)

    with pytest.raises(RuntimeError, match="differs from"):
        launch_suite(loaded, server.client(), tmp_path / "launches.jsonl")
    assert not any(r.url.path == "/evals" for r in server.requests)
    assert not (tmp_path / "launches.jsonl").exists()


@pytest.mark.unit
def test_launch_stops_when_the_server_pins_another_commit(tmp_path: Path) -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)
    inner = server.handle

    def wrong_pin(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/evals":
            return httpx.Response(
                200,
                json={
                    "eval_id": "e",
                    "baseline_repos": [
                        {
                            "repository": "syntropic137/syntropic137",
                            "requested_ref": "x",
                            "commit_sha": "0" * 40,
                        }
                    ],
                },
            )
        return inner(request)

    client = httpx.Client(base_url="http://api", transport=httpx.MockTransport(wrong_pin))
    with pytest.raises(RuntimeError, match="pinned"):
        launch_suite(loaded, client, tmp_path / "launches.jsonl")


@pytest.mark.unit
def test_a_run_that_reported_no_verdict_fails() -> None:
    assert not score_report(_EXPECTED, None, _FINDING).passed


# ---------------------------------------------------------------------------
# Same cases, different verifier
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_launch_under_the_codex_verifier_runs_and_records_the_codex_workflow(
    tmp_path: Path,
) -> None:
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    server = _Server(loaded)
    ledger = tmp_path / "launches.jsonl"
    launch_suite(loaded, server.client(), ledger)

    paths = [(r.method, r.url.path) for r in server.requests]
    assert paths[1] == ("GET", f"/workflows/{_CODEX_WF}")
    creates = [
        json.loads(r.content)
        for r in server.requests
        if r.method == "POST" and r.url.path == "/evals"
    ]
    # The case evals are shared by every verifier; the run says which one it was.
    assert all("starting_workflow_id" not in c for c in creates)
    starts = [json.loads(r.content) for r in server.requests if r.url.path.endswith("/execute")]
    assert {tuple(s["tags"]) for s in starts} == {("suite-version:6", f"verifier:{_CODEX_WF}")}
    assert all(not any(t.startswith("verifier") for t in c["tags"][1:]) for c in creates)
    starts = [r.url.path for r in server.requests if r.url.path.endswith("/execute")]
    assert set(starts) == {f"/workflows/{_CODEX_WF}/execute"}
    recorded = read_launches(ledger)
    assert {(x.suite, x.workflow_id) for x in recorded} == {
        (f"verifier-seed-v1:v6:{_CODEX_WF}", _CODEX_WF)
    }


@pytest.mark.unit
def test_scoring_one_verifier_never_counts_the_other_verifiers_runs() -> None:
    opus = load_suite(DEFAULT_SUITE)
    codex = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    # The server answers as if the opus run were in the eval: only the ledger
    # line's tag keeps it out of the codex table.
    rows, _ = score_suite(codex, _Server(opus).client(), [_launched(opus)])

    assert {r.status for r in rows} == {"not launched"}
    assert "workflow eval-verify-pinned-codex-v1" in render(codex, rows)


@pytest.mark.unit
def test_a_codex_run_scores_in_the_codex_table() -> None:
    codex = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    rows, unrecorded = score_suite(codex, _Server(codex).client(), [_launched(codex)])

    row = next(r for r in rows if r.case == _CASE)
    assert row.score is not None and row.score.passed
    assert unrecorded == ()


# ---------------------------------------------------------------------------
# Every version keeps its score (PR #1700 review)
# ---------------------------------------------------------------------------

# evals/verifier-seed-v1/launches.jsonl as v1 committed it, copied verbatim.
# Never edit these: they are what the owner's recorded 4/4 rests on.
_V1_LEDGER = """\
{"suite":"verifier-seed-v1:v1","case":"binary-artifact-minio-key","eval_id":"eval-ba8c2aba01b1414495f021b11ca5f8a6","run_id":"exec-0014a3de808d","commit":"b2f680f00b4e154b94fa4802a92ead30429e7b98","workflow_id":"eval-verify-pinned-v1"}
{"suite":"verifier-seed-v1:v1","case":"codex-cost-limit","eval_id":"eval-eb93f4482e5a4a0da14c76ba724797d0","run_id":"exec-d58cc7c768c8","commit":"123b25204fce5052f1b0ab494d2c59fa607624ad","workflow_id":"eval-verify-pinned-v1"}
{"suite":"verifier-seed-v1:v1","case":"execution-id-as-eval-id","eval_id":"eval-732d1230751e42d8bc1e8e643c23e8da","run_id":"exec-01377c8e4faf","commit":"7047b1c3daf1c4057d63eeb478cadd676d712bf5","workflow_id":"eval-verify-pinned-v1"}
{"suite":"verifier-seed-v1:v1","case":"shared-esp-stream","eval_id":"eval-45f40a9869f044078e0d8b44e5312403","run_id":"exec-707cefadabf8","commit":"6646da278d17a16e16549cf77b0749b25d8e8040","workflow_id":"eval-verify-pinned-v1"}
"""
_V1_CASES = {
    "binary-artifact-minio-key",
    "codex-cost-limit",
    "execution-id-as-eval-id",
    "shared-esp-stream",
}


class _LedgerServer:
    """Answers for each ledger line as the server holding that run would.

    Each eval carries the tag the line records and pins the line's commit;
    each run is a blocked verify whose report correctly names its case's defect.
    """

    def __init__(self, launches: list[Launch]) -> None:
        self.by_eval = {x.eval_id: x for x in launches}
        self.by_run = {x.run_id: x for x in launches}

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://api", transport=httpx.MockTransport(self.handle))

    def _eval(self, x: Launch) -> dict[str, object]:
        return {
            "eval_id": x.eval_id,
            "name": "n",
            "goal": "g",
            "starting_workflow_id": x.workflow_id,
            "tags": [x.suite, f"case:{x.case}", f"workflow:{x.workflow_id}"],
            "frozen": True,
            "archived": False,
            "created_at": None,
            "updated_at": None,
            "run_count": 1,
            "run_status_counts": {"completed": 1},
            "baseline_repos": [
                {
                    "repository": "syntropic137/syntropic137",
                    "requested_ref": x.commit,
                    "commit_sha": x.commit,
                }
            ],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = path.strip("/").split("/")
        if request.method == "POST" and path.endswith("/score"):
            return httpx.Response(200, json={})
        if path == "/evals":
            # Before the duplicate migration: no eval carries the stable suite tag.
            tags = set(request.url.params.get_list("tag"))
            evals = [self._eval(x) for x in self.by_eval.values() if {x.suite} == tags]
            return httpx.Response(
                200,
                json={
                    "total": len(evals),
                    "page": 1,
                    "page_size": 200,
                    "status_counts": {},
                    "evals": evals,
                },
            )
        if parts[0] == "evals" and len(parts) == 2:
            return httpx.Response(200, json=self._eval(self.by_eval[parts[1]]))
        if parts[0] == "evals" and parts[2:] == ["runs"]:
            x = self.by_eval[parts[1]]
            run = {"execution_id": x.run_id, "workflow_id": x.workflow_id, "status": "completed"}
            return httpx.Response(
                200, json={"total": 1, "page": 1, "page_size": 200, "items": [run]}
            )
        if parts[0] == "executions":
            x = self.by_run[parts[1]]
            return httpx.Response(
                200,
                json={
                    "workflow_execution_id": x.run_id,
                    "workflow_id": x.workflow_id,
                    "workflow_name": "w",
                    "status": "completed",
                    "review_verdict": "blocked",
                    "total_cost_usd": "2.00",
                    "total_duration_seconds": 300.0,
                    "unknown_duration_phase_count": 0,
                    "total_input_tokens": 1,
                    "total_output_tokens": 1,
                    "total_cache_creation_tokens": 0,
                    "total_cache_read_tokens": 0,
                    "total_tokens": 2,
                    "artifact_ids": [f"art-{x.run_id}"],
                    "phases": [
                        {
                            "phase_id": "verify",
                            "name": "v",
                            "status": "completed",
                            "artifact_id": f"art-{x.run_id}",
                            "model": "claude-opus-5-5",
                            "requested_model": "opus",
                        }
                    ],
                },
            )
        if parts[0] == "artifacts":
            x = self.by_run[parts[1].removeprefix("art-")]
            return httpx.Response(
                200,
                json={
                    "artifact_id": parts[1],
                    "content": _report(_PARAPHRASES[x.case][0]),
                    "content_type": "text/markdown",
                    "size_bytes": 10,
                },
            )
        return httpx.Response(404, json={"detail": path})


def _v1_ledger(tmp_path: Path) -> list[Launch]:
    ledger = tmp_path / "launches.jsonl"
    ledger.write_text(_V1_LEDGER)
    return read_launches(ledger)


@pytest.mark.unit
def test_the_v1_fixture_is_the_committed_ledger_verbatim() -> None:
    committed = (DEFAULT_SUITE / "launches.jsonl").read_text().splitlines()
    assert _V1_LEDGER.splitlines() == committed[: len(_V1_LEDGER.splitlines())]


@pytest.mark.unit
def test_v1_loads_its_own_four_cases_under_its_legacy_tag() -> None:
    v1 = load_suite(DEFAULT_SUITE, version=1)

    assert v1.tag == "verifier-seed-v1:v1"
    assert v1.workflow.id == _WF
    assert {c.id for c in v1.cases} == _V1_CASES
    assert not v1.is_current


@pytest.mark.unit
def test_the_committed_v1_ledger_scores_four_of_four_against_the_v1_cases(
    tmp_path: Path,
) -> None:
    launches = _v1_ledger(tmp_path)
    v1 = load_suite(DEFAULT_SUITE, version=1)
    rows, unrecorded = score_suite(v1, _LedgerServer(launches).client(), launches)

    assert {r.case for r in rows} == _V1_CASES
    assert all(r.status == "completed" for r in rows), [r.status for r in rows]
    assert [r.run_id for r in rows] == [x.run_id for x in launches]
    assert all(r.score and r.score.passed for r in rows)
    assert unrecorded == ()
    assert "4/4 passed" in render(v1, rows)


@pytest.mark.unit
def test_v1_runs_never_count_toward_the_current_version(tmp_path: Path) -> None:
    launches = _v1_ledger(tmp_path)
    current = load_suite(DEFAULT_SUITE)
    rows, unrecorded = score_suite(current, _LedgerServer(launches).client(), launches)

    assert len(rows) == 37 and {r.status for r in rows} == {"not launched"}
    assert unrecorded == ()


@pytest.mark.unit
def test_score_prints_every_version_the_workflow_ran() -> None:
    suite = load_suite(DEFAULT_SUITE).suite
    assert versions_run(suite, _WF) == [1, 3, 4, 5, 6]
    assert versions_run(suite, _CODEX_WF) == [2, 3, 4, 5, 6]
    assert versions_run(suite, _SONNET_WF) == [3, 4, 5, 6]


# The twelve cases of #1750's v3: the six v2 defects and the six clean controls.
_V3_CLEAN = {
    "clean-acquisition-fence-test",
    "clean-api-stdlib-event-loop",
    "clean-capture-volume-release",
    "clean-github-token-installation-routing",
    "clean-redis-signal-queue-fail-open",
    "clean-remote-source-single-predicate",
}


@pytest.mark.unit
@pytest.mark.parametrize("workflow", [_WF, _CODEX_WF, _SONNET_WF])
def test_v3_under_each_verifier_holds_its_twelve_cases_and_its_own_tag(workflow: str) -> None:
    v3 = load_suite(DEFAULT_SUITE, workflow=workflow, version=3)

    assert v3.tag == f"verifier-seed-v1:v3:{workflow}"
    assert v3.workflow.id == workflow
    assert {c.id for c in v3.cases if c.polarity == "defect"} == _V2_CASES
    assert {c.id for c in v3.cases if c.polarity == "clean"} == _V3_CLEAN


# Both were blocked by two strong verifiers for a real defect: retired in v5.
_RETIRED = {"clean-github-token-installation-routing", "clean-redis-signal-queue-fail-open"}


@pytest.mark.unit
def test_a_retired_control_scores_in_the_versions_that_held_it_and_never_launches_again(
    tmp_path: Path,
) -> None:
    v4 = load_suite(DEFAULT_SUITE, version=4)
    held = {c.id: c for c in v4.cases if c.id in _RETIRED}
    assert set(held) == _RETIRED and len(v4.cases) == 36
    # As it ran: still a clean control there, so v4's runs score as they did.
    assert all(isinstance(c, CleanCase) for c in held.values())

    current = load_suite(DEFAULT_SUITE)
    assert not {c.id for c in current.cases} & _RETIRED
    ledger = tmp_path / "launches.jsonl"
    launch_suite(current, _Server(current).client(), ledger)
    assert not {x.case for x in read_launches(ledger)} & _RETIRED


@pytest.mark.unit
@pytest.mark.parametrize("workflow", [_WF, _CODEX_WF, _SONNET_WF])
def test_v5_scores_its_own_cases_under_every_verifier_without_the_v6_controls(
    workflow: str,
) -> None:
    v5 = load_suite(DEFAULT_SUITE, workflow=workflow, version=5)
    current = load_suite(DEFAULT_SUITE, workflow=workflow)

    assert v5.tag == f"verifier-seed-v1:v5:{workflow}"
    assert len(v5.cases) == 33
    assert {c.source_pr for c in v5.cases if c.polarity == "clean"} == {917, 1010}
    added = {c.id for c in current.cases} - {c.id for c in v5.cases}
    assert {c.source_pr for c in current.cases if c.id in added} == _V6_CLEAN_PRS


@pytest.mark.unit
def test_a_retired_case_no_history_version_holds_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    # v5 and later histories hold the case, so take it out of every one first:
    # what is under test is a retired case with no version to score it in.
    suite = suite_dir / "suite.yaml"
    held = "      - redis-retry-non-idempotent\n"
    assert held in suite.read_text()
    suite.write_text(suite.read_text().replace(held, ""))
    case = suite_dir / "cases" / "redis-retry-non-idempotent.yaml"
    case.write_text(case.read_text() + "retired: v5 - never ran\n")

    with pytest.raises(
        DefinitionError, match=r"retired case\(s\) \['redis-retry-non-idempotent'\]"
    ):
        load_suite(suite_dir)


@pytest.mark.unit
def test_v3_defaults_to_the_first_verifier_it_ran() -> None:
    assert load_suite(DEFAULT_SUITE, version=3).workflow.id == _WF


@pytest.mark.unit
def test_a_past_version_under_a_workflow_it_never_ran_is_refused() -> None:
    with pytest.raises(DefinitionError, match="version 1 ran only"):
        load_suite(DEFAULT_SUITE, workflow=_CODEX_WF, version=1)


@pytest.mark.unit
def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(DefinitionError, match="version 7 is not one of"):
        load_suite(DEFAULT_SUITE, version=7)


@pytest.mark.unit
def test_a_history_entry_naming_a_missing_case_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    (suite_dir / "cases" / "codex-cost-limit.yaml").unlink()
    with pytest.raises(DefinitionError, match=r"history v1 names no such case\(s\)"):
        load_suite(suite_dir)


# Read from the committed ledger, as the v1 fixture is: the six-case v2 codex runs.
_V2_CASES = {
    "binary-artifact-minio-key",
    "codex-cost-limit",
    "execution-id-as-eval-id",
    "live-commits-unvalidated-sha",
    "repo-privacy-ignores-app",
    "shared-esp-stream",
}


@pytest.mark.unit
def test_the_committed_v2_codex_runs_score_against_the_six_v2_cases_only() -> None:
    v2 = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF, version=2)
    launches = [x for x in read_launches(DEFAULT_SUITE / "launches.jsonl") if x.suite == v2.tag]
    rows, unrecorded = score_suite(v2, _LedgerServer(launches).client(), launches)

    assert {c.id for c in v2.cases} == _V2_CASES
    assert {r.case for r in rows} == _V2_CASES
    assert "not launched" not in {r.status for r in rows}
    assert unrecorded == ()


# ---------------------------------------------------------------------------
# Train and holdout
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_holdout_is_new_cases_only_and_within_its_share() -> None:
    cases = load_suite(DEFAULT_SUITE).cases
    holdout = {c.id for c in cases if c.split == "holdout"}

    assert len(holdout) == 11 and len(cases) == 37
    # The pre-v4 defects were already run against the verifiers: never holdout.
    assert not holdout & _V2_CASES


@pytest.mark.unit
def test_a_train_launch_never_starts_a_holdout_case(tmp_path: Path) -> None:
    train = load_suite(DEFAULT_SUITE, split="train")
    ledger = tmp_path / "launches.jsonl"
    launch_suite(train, _Server(train).client(), ledger)

    holdout = {c.id for c in load_suite(DEFAULT_SUITE, split="holdout").cases}
    launched = {x.case for x in read_launches(ledger)}
    assert len(launched) == 26
    assert not launched & holdout


@pytest.mark.unit
def test_the_split_flag_selects_the_cases_check_reports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pins themselves are checked by the shallow-guarded tests above; this
    # one is about what the CLI hands to the check, so it runs on a shallow CI
    # clone too.
    checked: list[LoadedSuite] = []

    def record(loaded: LoadedSuite, repo: Path) -> list[str]:
        checked.append(loaded)
        return []

    monkeypatch.setattr(eval_suite, "check_commits", record)
    assert main(["check", "--split", "holdout"]) == 0
    assert [c.split for c in checked[0].cases] == ["holdout"] * 11
    out = capsys.readouterr().out
    assert ": 11 case(s)" in out
    assert "case:binary-artifact-minio-key" not in out


@pytest.mark.unit
def test_a_case_without_a_split_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "codex-cost-limit.yaml"
    case.write_text(case.read_text().replace("split: train\n", ""))

    with pytest.raises(DefinitionError, match="split"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_a_suite_with_too_little_holdout_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    for path in (suite_dir / "cases").glob("*.yaml"):
        path.write_text(path.read_text().replace("split: holdout", "split: train"))

    with pytest.raises(DefinitionError, match="0 of 37 cases are holdout"):
        load_suite(suite_dir)


# ---------------------------------------------------------------------------
# Install provenance: the real aggregate decides, as the route does
# ---------------------------------------------------------------------------


class _Templates:
    """The workflow repository and publisher the install handler needs, held in a dict."""

    def __init__(self) -> None:
        self.by_id: dict[str, WorkflowTemplateAggregate] = {}

    async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
        return self.by_id.get(aggregate_id)

    async def save(self, aggregate: WorkflowTemplateAggregate) -> None:
        assert aggregate.id is not None
        self.by_id[aggregate.id] = aggregate

    async def publish(self, events: object) -> None:
        return None

    def install(
        self,
        document: str,
        *,
        version: str | None,
        source_digest: str | None,
        package_name: str | None = None,
        force: bool = False,
    ) -> bool:
        """What `POST /workflows/from-yaml` does: the real command and handler. True if changed."""
        command = build_command_from_definition(
            WorkflowDefinition.from_yaml(document),
            version=version,
            source_digest=source_digest,
            package_name=package_name,
            force=force,
        )
        handler = CreateWorkflowTemplateHandler(self, self, model_defaults=PhaseModelDefaults())
        return asyncio.run(handler.handle(command)).changed

    def archive(self, workflow_id: str) -> None:
        aggregate = self.by_id[workflow_id]
        aggregate.archive_workflow(ArchiveWorkflowTemplateCommand(workflow_id=workflow_id))
        aggregate.mark_events_as_committed()


def _provenanced_server(loaded: LoadedSuite, templates: _Templates) -> tuple[_Server, httpx.Client]:
    """`_Server`, with `from-yaml` answered by the real install rules (409 on a conflict)."""
    server = _Server(loaded)
    inner = server.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/workflows/from-yaml":
            server.requests.append(request)
            params = request.url.params
            try:
                changed = templates.install(
                    request.content.decode(),
                    version=params.get("version"),
                    source_digest=params.get("source_digest"),
                    force=params.get("force") == "true",
                )
            except WorkflowTemplateConflictError as e:
                return httpx.Response(409, json={"detail": str(e)})
            server.installed = loaded.workflow.id
            return httpx.Response(
                201,
                json={"id": loaded.workflow.id, "status": "created" if changed else "unchanged"},
            )
        return inner(request)

    return server, httpx.Client(base_url="http://api", transport=httpx.MockTransport(handle))


def _document(loaded: LoadedSuite) -> str:
    """The document `launch` uploads, as the first install request carried it."""
    server = _Server(loaded)
    launch_suite(loaded, server.client(), Path(os.devnull))
    return server.requests[0].content.decode()


@pytest.mark.unit
def test_launch_installs_with_the_suite_version_and_the_document_digest(tmp_path: Path) -> None:
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    server = _Server(loaded)
    launch_suite(loaded, server.client(), tmp_path / "launches.jsonl")

    install = server.requests[0]
    document = install.content.decode()
    digest = hashlib.sha256(install.content).hexdigest()
    assert install.url.params.get("version") == f"{loaded.suite.version}.0.0"
    assert install.url.params.get("source_digest") == f"sha256:{digest}"
    assert "force" not in install.url.params
    assert install_provenance(loaded, document).source_digest == f"sha256:{digest}"


@pytest.mark.unit
def test_an_identical_relaunch_is_an_unchanged_install(tmp_path: Path) -> None:
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    templates = _Templates()
    ledger = tmp_path / "launches.jsonl"

    _, client = _provenanced_server(loaded, templates)
    first = launch_suite(loaded, client, ledger)
    _, client = _provenanced_server(loaded, templates)
    again = launch_suite(loaded, client, ledger)

    assert first[0].startswith(f"workflow {_CODEX_WF}: created as 6.0.0")
    assert again[0].startswith(f"workflow {_CODEX_WF}: unchanged as 6.0.0")


@pytest.mark.unit
def test_a_changed_workflow_without_a_version_bump_is_refused_before_any_eval(
    tmp_path: Path,
) -> None:
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    templates = _Templates()
    document = _document(loaded)
    provenance = install_provenance(loaded, document)
    # The server holds this suite version under another digest: the republish signature.
    templates.install(document, version=provenance.version, source_digest="sha256:" + "0" * 64)

    server, client = _provenanced_server(loaded, templates)
    with pytest.raises(RuntimeError, match=r"different source.*bump the suite version"):
        launch_suite(loaded, client, tmp_path / "launches.jsonl")
    assert not any(r.url.path == "/evals" for r in server.requests)


@pytest.mark.unit
def test_a_cli_installed_archived_record_is_restored_by_launch_without_force(
    tmp_path: Path,
) -> None:
    """The VPS state that blocked the provenance-less launch (2026-10-07).

    `syn workflow install workflows/evals/verify-pinned-codex` records version
    0.0.0 (no manifest), no digest and package name; `syn workflow delete -f`
    archives it. An install declaring no version is refused (provenance guard).
    `launch` declares the suite version + digest: a different version on an archived
    template, so the update is accepted, the template is active again and the
    recorded provenance is the suite's. No `force` is needed.
    """
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    templates = _Templates()
    document = _document(loaded)
    templates.install(
        document, version="0.0.0", source_digest=None, package_name="verify-pinned-codex"
    )
    templates.archive(_CODEX_WF)
    with pytest.raises(WorkflowTemplateConflictError, match="declares no version"):
        templates.install(document, version=None, source_digest=None)

    _, client = _provenanced_server(loaded, templates)
    lines = launch_suite(loaded, client, tmp_path / "launches.jsonl")

    stored = templates.by_id[_CODEX_WF]
    assert lines[0].startswith(f"workflow {_CODEX_WF}: created as 6.0.0")
    assert not stored.is_archived
    assert stored.source_digest == install_provenance(loaded, document).source_digest


@pytest.mark.unit
def test_an_edited_prompt_relaunched_over_an_archived_template_without_a_bump_is_refused(
    tmp_path: Path,
) -> None:
    """Codex review of #1705: archiving must not open the republish hole.

    Launch v2, archive its workflow, edit an inlined prompt, relaunch without
    bumping the suite. The same version under a new digest is a republish
    whether or not the template is archived, so the real handler refuses it,
    the archived record is untouched and no eval is created.
    """
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    templates = _Templates()
    _, client = _provenanced_server(loaded, templates)
    launch_suite(loaded, client, tmp_path / "launches.jsonl")
    launched = install_provenance(loaded, _document(loaded)).source_digest
    templates.archive(_CODEX_WF)

    root = tmp_path / "root"
    workflow_dir = (root / loaded.workflow.path).parent
    shutil.copytree((ROOT / loaded.workflow.path).parent, workflow_dir)
    prompt = workflow_dir / "phases" / "verify.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")

    server, client = _provenanced_server(loaded, templates)
    with pytest.raises(RuntimeError, match=r"different source.*bump the suite version"):
        launch_suite(loaded, client, tmp_path / "launches.jsonl", root=root)

    stored = templates.by_id[_CODEX_WF]
    assert stored.is_archived
    assert stored.source_digest == launched
    assert not any(r.url.path == "/evals" for r in server.requests)


@pytest.mark.unit
def test_an_unchanged_relaunch_restores_an_archived_template(tmp_path: Path) -> None:
    """The recovery the archived exemption exists for still needs no bump or force."""
    loaded = load_suite(DEFAULT_SUITE, workflow=_CODEX_WF)
    templates = _Templates()
    _, client = _provenanced_server(loaded, templates)
    launch_suite(loaded, client, tmp_path / "launches.jsonl")
    templates.archive(_CODEX_WF)

    _, client = _provenanced_server(loaded, templates)
    lines = launch_suite(loaded, client, tmp_path / "launches.jsonl")

    assert lines[0].startswith(f"workflow {_CODEX_WF}: created as 6.0.0")
    assert not templates.by_id[_CODEX_WF].is_archived


@pytest.mark.unit
def test_launch_reuses_each_case_eval_and_creates_none(tmp_path: Path) -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)
    server.existing = True

    launch_suite(loaded, server.client(), tmp_path / "launches.jsonl")

    assert not any(r.method == "POST" and r.url.path == "/evals" for r in server.requests)
    starts = [json.loads(r.content) for r in server.requests if r.url.path.endswith("/execute")]
    assert [s["eval_id"] for s in starts] == [f"eval-{c.commit[:6]}" for c in loaded.cases]
    assert {tuple(s["tags"]) for s in starts} == {("suite-version:6", f"verifier:{_WF}")}


@pytest.mark.unit
def test_score_records_each_verdict_on_the_eval() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server = _Server(loaded)

    score_suite(loaded, server.client(), [_LAUNCHED])

    [(path, body)] = server.scores
    assert path == "/evals/eval-1/runs/exec-1/score"
    assert body["verdict"] == "PASS"
    assert body["score"] == 1.0
    assert (body["scorer"], body["scorer_version"]) == ("eval_suite.py", "6")
    assert isinstance(body["evidence"], str) and _CASE in body["evidence"]


# ---------------------------------------------------------------------------
# Clean controls: a merged change with no known defect passes only certified
# ---------------------------------------------------------------------------


@pytest.fixture
def merged(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A repo whose main merged a one-commit PR with --no-ff: (repo, base, PR head, merge)."""
    repo = tmp_path / "merged"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("one\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "a.py").write_text("two\n")
    _git(repo, "commit", "-qam", "feat: two")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from feature", "feature")
    return repo, base, head, _git(repo, "rev-parse", "HEAD")


def _later(repo: Path, message: str) -> str:
    """Commit `message` on main 31 days after HEAD, touching a file of its own, so
    the control's quiet window has passed."""
    (repo / "later.txt").write_text(message)
    _git(repo, "add", "later.txt")
    when = int(_git(repo, "show", "-s", "--format=%ct", "HEAD")) + 31 * _DAY
    env = {**os.environ, "GIT_AUTHOR_DATE": f"@{when}", "GIT_COMMITTER_DATE": f"@{when}"}
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], env=env, check=True)
    return _git(repo, "rev-parse", "HEAD")


def _clean_suite(tmp_path: Path, commit: str, merge: str, through: str) -> Path:
    suite_dir = _copy_suite(tmp_path)
    suite_file = suite_dir / "suite.yaml"
    suite = yaml.safe_load(suite_file.read_text())
    suite.pop("history", None)
    suite_file.write_text(yaml.safe_dump(suite))
    for p in (suite_dir / "cases").glob("*.yaml"):
        p.unlink()
    case = {
        "id": "control",
        "polarity": "clean",
        "source_pr": 7,
        "commit": commit,
        "merge_commit": merge,
        "clean_through": through,
        "task": "Review it.",
        "split": "train",
    }
    (suite_dir / "cases" / "control.yaml").write_text(json.dumps(case))
    return suite_dir


@pytest.mark.unit
def test_check_passes_a_clean_pin_at_the_merged_pr_head(
    tmp_path: Path, merged: tuple[Path, str, str, str]
) -> None:
    repo, _, head, merge = merged
    through = _later(repo, "chore: changelog for #7")  # a mention that fixes nothing
    loaded = load_suite(_clean_suite(tmp_path, head, merge, through))
    assert [c.polarity for c in loaded.cases] == ["clean"]
    assert check_commits(loaded, repo) == []


@pytest.mark.unit
def test_check_refuses_a_clean_pin_that_is_not_the_merges_second_parent(
    tmp_path: Path, merged: tuple[Path, str, str, str]
) -> None:
    repo, base, _, merge = merged
    through = _later(repo, "chore: later")
    problems = check_commits(load_suite(_clean_suite(tmp_path, base, merge, through)), repo)
    assert problems == [
        f"control: pins {base[:12]}, but the merge {merge[:12]}'s second parent is "
        f"{_git(repo, 'rev-parse', merge + '^2')[:12]}; pin the PR head the merge took"
    ]


@pytest.mark.unit
def test_check_refuses_a_merge_off_the_first_parent_chain(
    tmp_path: Path, merged: tuple[Path, str, str, str]
) -> None:
    # A merge made inside a branch and brought in by a later merge is not one
    # main took: its first parent is the branch, not main.
    repo, _, _, _ = merged
    _git(repo, "checkout", "-qb", "outer")
    _git(repo, "checkout", "-qb", "inner")
    (repo / "b.py").write_text("b\n")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-qm", "feat: b")
    inner_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "outer")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge inner", "inner")
    inner_merge = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    (repo / "c.py").write_text("c\n")
    _git(repo, "add", "c.py")
    _git(repo, "commit", "-qm", "main moves on")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge outer", "outer")
    tip = _git(repo, "rev-parse", "HEAD")

    problems = check_commits(load_suite(_clean_suite(tmp_path, inner_head, inner_merge, tip)), repo)
    assert problems == [
        f"control: the merge {inner_merge[:12]} is not on the first-parent chain of {tip[:12]}"
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "message", ["fix: the PR #7 retry never stops", "Fix(#7): restore the lost key"]
)
def test_check_refuses_a_clean_control_a_later_commit_fixes(
    tmp_path: Path, merged: tuple[Path, str, str, str], message: str
) -> None:
    repo, _, head, merge = merged
    fix = _later(repo, message)
    through = _later(repo, "chore: unrelated")
    problems = check_commits(load_suite(_clean_suite(tmp_path, head, merge, through)), repo)
    assert problems == [
        f"control: {fix[:12]} fixes or reverts #7 after it merged; "
        "a clean control must have no known defect"
    ]


@pytest.mark.unit
def test_check_refuses_a_clean_control_git_revert_undid(
    tmp_path: Path, merged: tuple[Path, str, str, str]
) -> None:
    # `git revert` names the merge by SHA, never by PR number.
    repo, _, head, merge = merged
    _git(repo, "revert", "--no-edit", "-m", "1", merge)
    revert = _git(repo, "rev-parse", "HEAD")
    through = _later(repo, "chore: later")
    problems = check_commits(load_suite(_clean_suite(tmp_path, head, merge, through)), repo)
    assert problems == [
        f"control: {revert[:12]} fixes or reverts #7 after it merged; "
        "a clean control must have no known defect"
    ]


_DAY = 86400
_PR_FILE = "def kept():\n    return 1\n\n\nclass Box:\n    def changed(self):\n        return 2\n"


def _commit_at(repo: Path, when: int, message: str, text: str | None = None) -> str:
    """Commit on the current branch at epoch `when`, writing `text` to m.py if given."""
    if text is not None:
        (repo / "m.py").write_text(text)
    else:
        (repo / "other.txt").write_text(message)
    _git(repo, "add", ".")
    env = {**os.environ, "GIT_AUTHOR_DATE": f"@{when}", "GIT_COMMITTER_DATE": f"@{when}"}
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], env=env, check=True)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def quiet(tmp_path: Path) -> tuple[Path, str, str, int]:
    """A repo whose main merged a PR that changed `Box.changed` in m.py at day 0:
    (repo, PR head, merge, the merge's epoch)."""
    repo = tmp_path / "quiet"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    day0 = 1_780_000_000
    _commit_at(repo, day0 - _DAY, "base", _PR_FILE.replace("return 2", "return 0"))
    _git(repo, "checkout", "-qb", "feature")
    head = _commit_at(repo, day0 - 60, "feat: box", _PR_FILE)
    _git(repo, "checkout", "-q", "main")
    env = {**os.environ, "GIT_AUTHOR_DATE": f"@{day0}", "GIT_COMMITTER_DATE": f"@{day0}"}
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "Merge pull request #7",
            "feature",
        ],
        env=env,
        check=True,
    )
    return repo, head, _git(repo, "rev-parse", "HEAD"), day0


@pytest.mark.unit
def test_check_refuses_a_control_whose_function_a_later_commit_changes_within_30_days(
    tmp_path: Path, quiet: tuple[Path, str, str, int]
) -> None:
    # Moved below a new function first, so only its qualified name finds it.
    repo, head, merge, day0 = quiet
    moved = "def added():\n    return 9\n\n\n" + _PR_FILE
    _commit_at(repo, day0 + _DAY, "feat: added", moved)
    touch = _commit_at(
        repo, day0 + 2 * _DAY, "refactor: tidy", moved.replace("return 2", "return 3")
    )
    through = _commit_at(repo, day0 + 40 * _DAY, "chore: later")

    problems = check_commits(load_suite(_clean_suite(tmp_path, head, merge, through)), repo)
    assert problems == [
        f"control: {touch[:12]} changes m.py:Box.changed within 30 days of the merge; "
        "a clean control's code must stay untouched that long"
    ]


@pytest.mark.unit
def test_check_passes_a_control_whose_other_functions_or_later_days_see_the_change(
    tmp_path: Path, quiet: tuple[Path, str, str, int]
) -> None:
    repo, head, merge, day0 = quiet
    other = _PR_FILE.replace("return 1", "return 5")
    _commit_at(repo, day0 + _DAY, "feat: kept", other)  # not a function the PR changed
    _commit_at(repo, day0 + 31 * _DAY, "feat: box", other.replace("return 2", "return 3"))
    through = _commit_at(repo, day0 + 40 * _DAY, "chore: later")

    loaded = load_suite(_clean_suite(tmp_path, head, merge, through))
    assert check_commits(loaded, repo) == []


@pytest.mark.unit
def test_check_refuses_a_control_younger_than_30_days_and_spares_an_older_one(
    tmp_path: Path, quiet: tuple[Path, str, str, int]
) -> None:
    repo, head, merge, day0 = quiet
    young = _commit_at(repo, day0 + 10 * _DAY, "chore: later")
    old = _commit_at(repo, day0 + 30 * _DAY, "chore: later still")

    assert check_commits(
        load_suite(_clean_suite(tmp_path / "young", head, merge, young)), repo
    ) == [
        f"control: clean_through {young[:12]} is under 30 days after the merge; "
        "a clean control needs that long untouched"
    ]
    assert check_commits(load_suite(_clean_suite(tmp_path / "old", head, merge, old)), repo) == []


def _quiet_repo(tmp_path: Path, before: str, after: str) -> tuple[Path, str, str, int]:
    """Like `quiet`, but the PR changes m.py from `before` to `after`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    day0 = 1_780_000_000
    _commit_at(repo, day0 - _DAY, "base", before)
    _git(repo, "checkout", "-qb", "feature")
    head = _commit_at(repo, day0 - 60, "feat: change", after)
    _git(repo, "checkout", "-q", "main")
    env = {**os.environ, "GIT_AUTHOR_DATE": f"@{day0}", "GIT_COMMITTER_DATE": f"@{day0}"}
    merge = ["git", "-C", str(repo), "merge", "-q", "--no-ff", "-m", "Merge #7", "feature"]
    subprocess.run(merge, env=env, check=True)
    return repo, head, _git(repo, "rev-parse", "HEAD"), day0


def _touches_after(tmp_path: Path, after: str, later: str) -> tuple[str, list[str]]:
    """A PR changes `return 0` to `return 2` in `after`; on day 2 main rewrites m.py
    to `later`. Returns that commit and what `check` says, read through day 40."""
    repo, head, merge, day0 = _quiet_repo(tmp_path, after.replace("return 2", "return 0"), after)
    touch = _commit_at(repo, day0 + 2 * _DAY, "refactor: later", later)
    through = _commit_at(repo, day0 + 40 * _DAY, "chore: later")
    return touch, check_commits(load_suite(_clean_suite(tmp_path, head, merge, through)), repo)


def _untouched(touch: str) -> str:
    return f"control: {touch[:12]} changes m.py:"


@pytest.mark.unit
def test_check_follows_a_function_defined_under_a_conditional(tmp_path: Path) -> None:
    source = "if True:\n    def changed():\n        return 2\n"
    touch, problems = _touches_after(tmp_path, source, source.replace("return 2", "return 3"))
    assert problems == [
        f"{_untouched(touch)}changed within 30 days of the merge; "
        "a clean control's code must stay untouched that long"
    ]


@pytest.mark.unit
def test_check_follows_a_property_getter_beside_its_same_named_setter(tmp_path: Path) -> None:
    source = (
        "class Box:\n    @property\n    def value(self):\n        return 2\n\n"
        "    @value.setter\n    def value(self, new):\n        self._value = new\n"
    )
    touch, problems = _touches_after(tmp_path, source, source.replace("return 2", "return 3"))
    assert problems == [
        f"{_untouched(touch)}Box.value within 30 days of the merge; "
        "a clean control's code must stay untouched that long"
    ]


@pytest.mark.unit
def test_check_ignores_a_function_added_after_the_changed_one(tmp_path: Path) -> None:
    source = "def changed():\n    return 2\n"
    _, problems = _touches_after(tmp_path, source, source + "\n\ndef other():\n    return 9\n")
    assert problems == []


@pytest.mark.unit
def test_check_refuses_a_line_inserted_inside_the_changed_function(tmp_path: Path) -> None:
    source = "def changed():\n    return 2\n"
    later = "def changed():\n    print()\n    return 2\n"
    touch, problems = _touches_after(tmp_path, source, later)
    assert problems == [
        f"{_untouched(touch)}changed within 30 days of the merge; "
        "a clean control's code must stay untouched that long"
    ]


@pytest.mark.unit
def test_a_clean_case_with_a_fix_or_expected_findings_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "clean-api-stdlib-event-loop.yaml"
    case.write_text(case.read_text() + "fix_commit: " + "a" * 40 + "\n")

    with pytest.raises(DefinitionError, match="fix_commit"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_a_case_without_a_polarity_is_refused(tmp_path: Path) -> None:
    suite_dir = _copy_suite(tmp_path)
    case = suite_dir / "cases" / "codex-cost-limit.yaml"
    case.write_text(case.read_text().replace("polarity: defect\n", ""))

    with pytest.raises(DefinitionError, match="polarity"):
        load_suite(suite_dir)


@pytest.mark.unit
def test_each_split_holds_clean_controls() -> None:
    # 31 defects outnumber the 6 controls, so a false-block rate is only
    # measurable on each side of the split if both sides hold some.
    for split in ("train", "holdout"):
        cases = load_suite(DEFAULT_SUITE, split=split).cases
        assert any(isinstance(c, CleanCase) for c in cases), split
        assert any(isinstance(c, DefectCase) for c in cases), split


def _clean_case() -> CleanCase:
    return next(c for c in load_suite(DEFAULT_SUITE).cases if isinstance(c, CleanCase))


@pytest.mark.unit
def test_a_certified_clean_control_passes() -> None:
    score = score_case(_clean_case(), "certified", "## BLOCKING\n\nNone.\n")
    assert score.passed and not score.false_block


@pytest.mark.unit
def test_a_blocked_clean_control_fails_as_a_false_block_whatever_it_names() -> None:
    # The finding names a defect seed's file and every keyword: on a clean
    # control that is still a false block, never a catch.
    score = score_case(_clean_case(), "blocked", _FINDING)
    assert score.findings == 1
    assert not score.passed and score.false_block


@pytest.mark.unit
def test_a_clean_control_with_no_verdict_fails_and_is_not_a_false_block() -> None:
    score = score_case(_clean_case(), None, "")
    assert not score.passed and not score.false_block


@pytest.mark.unit
def test_score_case_still_needs_a_defect_blocked_and_named() -> None:
    defect = _case(_CASE)
    assert score_case(defect, "blocked", _FINDING).passed
    assert not score_case(defect, "certified", _FINDING).passed
    assert not score_case(defect, "blocked", "## BLOCKING\n\nNone.\n").passed
    assert not score_case(defect, "blocked", _FINDING).false_block


def _clean_server(loaded: LoadedSuite, verdict: str) -> tuple[_Server, Launch]:
    clean = _clean_case()
    server = _Server(loaded)
    server.case, server.eval_pin, server.verdict = clean.id, clean.commit, verdict
    launch = Launch(
        suite=loaded.tag,
        case=clean.id,
        eval_id="eval-1",
        run_id="exec-1",
        commit=clean.commit,
        workflow_id=loaded.workflow.id,
    )
    return server, launch


@pytest.mark.unit
def test_score_records_a_certified_clean_control_as_a_pass() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server, launch = _clean_server(loaded, "certified")
    rows, _ = score_suite(loaded, server.client(), [launch])

    [(_, body)] = server.scores
    assert (body["verdict"], body["score"]) == ("PASS", 1.0)
    assert f"{_clean_case().id} (clean)" in str(body["evidence"])
    table = render(loaded, rows)
    assert "1/37 passed" in table
    assert "false-block rate (clean controls blocked): 0/1 (0%)" in table
    assert "catch rate (defect cases blocked and named): -" in table


@pytest.mark.unit
def test_score_records_a_blocked_clean_control_as_a_false_block() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    server, launch = _clean_server(loaded, "blocked")
    rows, _ = score_suite(loaded, server.client(), [launch])

    [(_, body)] = server.scores
    assert (body["verdict"], body["score"]) == ("FAIL", 0.0)
    table = render(loaded, rows)
    assert "0/37 passed" in table
    assert "false-block rate (clean controls blocked): 1/1 (100%)" in table


@pytest.mark.unit
def test_rates_separate_catches_from_false_blocks_per_table() -> None:
    loaded = load_suite(DEFAULT_SUITE)
    clean = _clean_case()
    defect = _case(_CASE)

    def row(case_id: str, score: Score) -> ScoredRun:
        return ScoredRun(
            case=case_id,
            eval_id="e",
            run_id="r",
            status="completed",
            score=score,
            cost_usd=None,
            duration="-",
            models="-",
        )

    rows = [
        row(defect.id, score_case(defect, "blocked", _FINDING)),
        row(defect.id, score_case(defect, "certified", "")),
        row(clean.id, score_case(clean, "blocked", _FINDING)),
        row(clean.id, score_case(clean, "certified", "")),
        row(clean.id, score_case(clean, "certified", "")),
    ]
    assert rates(rows) == (
        "catch rate (defect cases blocked and named): 1/2 (50%)\n"
        "false-block rate (clean controls blocked): 1/3 (33%)"
    )
    assert "3/5 passed" in render(loaded, rows)
