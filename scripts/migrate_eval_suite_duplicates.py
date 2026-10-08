#!/usr/bin/env python3
"""Fold a suite's per-launch duplicate evals into one stable eval per case (one-off).

Before evals v2, every ``eval_suite.py launch`` created a fresh eval per case,
tagged with the version tag (``verifier-seed-v1:v1``, ``verifier-seed-v1:v2:<wf>``).
Now each case has ONE eval, tagged ``suite:<eval_suite>`` + ``case:<id>``. For
each case this script:

1. finds the stable eval, or creates it pinned to the case's commit,
2. finds the duplicates: evals tagged ``case:<id>`` and any version tag of the
   suite (current or ``history``) that are not the stable eval,
3. moves each duplicate's runs into the stable eval (detach, then attach;
   attach never copies a baseline, so a duplicate that pins another commit
   is skipped and reported, never folded, and so is a case whose stable eval
   pins another commit),
4. archives the duplicate once it has no runs left. Archive is a soft delete:
   its events remain.

A move is two requests, and a run between them belongs to no eval, where no
membership list can find it again. So each move is written to a journal
(``--journal``, JSON lines) BEFORE the detach and marked done after the attach.
Every non-dry run starts by finishing the journal's unfinished moves: a run in
no eval is attached to its target, a run already there is marked done, and a
run anywhere else stops the migration rather than guess.

The launch ledger is never edited: ``score`` finds a moved run in the stable
eval by its run id.

    uv run python scripts/migrate_eval_suite_duplicates.py --dry-run [--suite DIR] [--api-url URL]
    uv run python scripts/migrate_eval_suite_duplicates.py           [--suite DIR] [--api-url URL] [--journal FILE]

Run ``--dry-run`` first and read it. Never point it at a shared server without
the owner's go-ahead: the moves and archives are real commands.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_suite import (
    DEFAULT_SUITE,
    Case,
    LoadedSuite,
    _basic_auth,  # pyright: ignore[reportPrivateUsage]
    _case_evals,  # pyright: ignore[reportPrivateUsage]
    _detail,  # pyright: ignore[reportPrivateUsage]
    _Eval,  # pyright: ignore[reportPrivateUsage]
    _EvalList,  # pyright: ignore[reportPrivateUsage]
    _member_runs,  # pyright: ignore[reportPrivateUsage]
    load_suite,
)

from syn_shared.settings.dev_tooling import get_dev_api_url


class _Move(BaseModel):
    """One journal line: a run's move between evals, before (``detaching``) and after (``moved``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run: str
    source: str
    target: str
    state: Literal["detaching", "moved"]


class _EvalRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eval_id: str


class _ExecutionEval(BaseModel):
    """The one field of ``GET /executions/{id}`` this script reads: the run's current eval."""

    model_config = ConfigDict(extra="ignore")

    eval: _EvalRef | None = None


def _write(journal: Path, move: _Move) -> None:
    """Append and fsync: the line must be on disk before the request it guards is sent."""
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(move.model_dump_json() + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _unfinished(journal: Path) -> list[_Move]:
    """Moves whose last journal line is ``detaching``: detached, maybe never attached."""
    if not journal.exists():
        return []
    last: dict[str, _Move] = {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        if line.strip():
            move = _Move.model_validate_json(line)
            last[move.run] = move
    return [m for m in last.values() if m.state == "detaching"]


def _current_eval(client: httpx.Client, run: str) -> str | None:
    response = client.get(f"/executions/{run}")
    _check(response, f"read {run}")
    found = _ExecutionEval.model_validate(response.json()).eval
    return None if found is None else found.eval_id


def recover(client: httpx.Client, journal: Path, *, dry_run: bool) -> list[str]:
    """Finish every move an earlier run left between its detach and its attach."""
    verb = "would " if dry_run else ""
    out: list[str] = []
    for move in _unfinished(journal):
        now = _current_eval(client, move.run)
        if now == move.source:
            # The detach never landed; the normal pass moves it again.
            out.append(f"recover: {move.run} is still in {move.source}, moved again below")
            continue
        if now is not None and now != move.target:
            raise RuntimeError(
                f"recover: {move.run} was moving {move.source} -> {move.target} but is in {now}; "
                "resolve it by hand before running again"
            )
        if not dry_run:
            if now is None:
                _check(
                    client.post(f"/executions/{move.run}/eval", json={"eval_id": move.target}),
                    f"recover: attach {move.run}",
                )
            _write(journal, move.model_copy(update={"state": "moved"}))
        action = "attach" if now is None else "mark done"
        out.append(f"recover: {verb}{action} {move.run} -> {move.target}")
    return out


def version_tags(loaded: LoadedSuite) -> set[str]:
    """Every tag a pre-v2 launch put on its evals: the current version's per workflow, and history's."""
    s = loaded.suite
    return {f"{s.current_tag_prefix}:{w.id}" for w in s.workflows} | {h.tag for h in s.history}


def _duplicates(
    client: httpx.Client, loaded: LoadedSuite, case: Case, keep: str | None
) -> list[_Eval]:
    found: dict[str, _Eval] = {}
    for tag in sorted(version_tags(loaded)):
        params = httpx.QueryParams([("tag", tag), ("tag", case.tag), ("page_size", 200)])
        response = client.get("/evals", params=params)
        response.raise_for_status()
        for ev in _EvalList.model_validate(response.json()).evals:
            if ev.eval_id != keep:
                found[ev.eval_id] = ev
    return [found[k] for k in sorted(found)]


def _check(response: httpx.Response, what: str) -> None:
    if response.is_error:
        raise RuntimeError(f"{what}: {response.status_code} {_detail(response)}")


def migrate(
    loaded: LoadedSuite, client: httpx.Client, *, dry_run: bool, journal: Path | None = None
) -> list[str]:
    """Fold every case's duplicates into its stable eval; one line per action taken or planned.

    ``journal`` is required unless ``dry_run``: it is how an interrupted move is found again.
    """
    if not dry_run and journal is None:
        raise ValueError("a real migration needs a journal")
    s = loaded.suite
    verb = "would " if dry_run else ""
    out: list[str] = recover(client, journal, dry_run=dry_run) if journal is not None else []
    for case in loaded.cases:
        stable = _case_evals(client, loaded, case)
        if len(stable) > 1:
            out.append(f"{case.id}: SKIP, {len(stable)} evals carry {s.suite_tag} {case.tag}")
            continue
        if stable:
            stable_pin = [(b.repository, b.commit_sha) for b in stable[0].baseline_repos]
            if stable_pin != [(s.repository, case.commit)]:
                out.append(
                    f"{case.id}: SKIP, stable eval {stable[0].eval_id} pins {stable_pin}, "
                    f"the case pins {case.commit[:12]}"
                )
                continue
        keep = stable[0].eval_id if stable else None
        duplicates = _duplicates(client, loaded, case, keep)
        if keep is None and not duplicates:
            continue
        if keep is None:
            if dry_run:
                keep = "<new>"
            else:
                response = client.post(
                    "/evals",
                    json={
                        "name": f"{s.eval_suite or s.id}: {case.id}",
                        "goal": s.goal,
                        "baseline_repos": [
                            {"repository": s.repository, "requested_ref": case.commit}
                        ],
                        "tags": [s.suite_tag, case.tag],
                    },
                )
                _check(response, f"{case.id}: create")
                keep = _Eval.model_validate(response.json()).eval_id
            out.append(f"{case.id}: {verb}create stable eval {keep} @ {case.commit[:12]}")
        for dup in duplicates:
            pinned = [(b.repository, b.commit_sha) for b in dup.baseline_repos]
            if pinned != [(s.repository, case.commit)]:
                out.append(
                    f"{case.id}: SKIP {dup.eval_id}, it pins {pinned}, the case pins {case.commit[:12]}"
                )
                continue
            for run in _member_runs(client, dup.eval_id):
                if not dry_run:
                    assert journal is not None  # checked above
                    rid = run.execution_id
                    move = _Move(run=rid, source=dup.eval_id, target=keep, state="detaching")
                    _write(journal, move)
                    _check(
                        client.delete(f"/executions/{rid}/eval", params={"eval_id": dup.eval_id}),
                        f"{case.id}: detach {rid}",
                    )
                    _check(
                        client.post(f"/executions/{rid}/eval", json={"eval_id": keep}),
                        f"{case.id}: attach {rid}",
                    )
                    _write(journal, move.model_copy(update={"state": "moved"}))
                out.append(f"{case.id}: {verb}move run {run.execution_id} {dup.eval_id} -> {keep}")
            if not dry_run:
                left = _member_runs(client, dup.eval_id)
                if left:
                    out.append(
                        f"{case.id}: SKIP archive {dup.eval_id}, {len(left)} run(s) still in it"
                    )
                    continue
                _check(
                    client.post(f"/evals/{dup.eval_id}/archive"),
                    f"{case.id}: archive {dup.eval_id}",
                )
            out.append(f"{case.id}: {verb}archive {dup.eval_id}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--api-url", default=None, help="defaults to DEV__API_URL / localhost")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="moves in flight, for recovery (default: <suite>/migration-journal.jsonl)",
    )
    args = parser.parse_args(argv)

    loaded = load_suite(args.suite)
    with httpx.Client(
        base_url=args.api_url or get_dev_api_url(), timeout=60, auth=_basic_auth()
    ) as client:
        journal = args.journal or args.suite / "migration-journal.jsonl"
        lines = migrate(loaded, client, dry_run=args.dry_run, journal=journal)
    print("\n".join(lines) or "nothing to migrate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
