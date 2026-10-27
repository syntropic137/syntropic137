# implementer-seed-v1: the IMPLEMENTER eval kind (#1725)

The verifier suite (`evals/verifier-seed-v1`) asks whether a verifier BLOCKS a
known bug. This suite asks the other question: **given the problem, does the
implementing agent fix it?** It is scored by tests, not by reading a report.

## What a case is

| Field | Meaning |
|---|---|
| `commit` | The first parent of a real merged fix: the tree with the bug and none of the fix |
| `fix_commit` | The merge that shipped the fix |
| `task` | The problem as its issue (or the fix PR's symptom section) stated it, with the fix's own description of the solution removed. It must not name `source_pr`; `check` refuses one that does |
| `hidden_tests` | The pytest files the fix PR added or changed, run at their `fix_commit` content. They are not at `commit`, so the agent never sees them |

Where a hidden test imports a name the fix introduced, the task says so under
"Interface the scoring tests use". Without it no correct fix could pass except
by guessing a name, and the case would measure the guess. That paragraph
states the contract, not the implementation.

The same applies to every exact spelling a hidden test depends on, and
`check` enforces it (#2023). It parses each hidden test at `fix_commit` and
reads four kinds of spelling:

- names imported from a `syn_*` package;
- attribute names passed to `setattr` (monkeypatching);
- literals in `assert "<text>" in ...`;
- `raises(match=...)` patterns.

Each one must appear in the task text or somewhere in the tree at the pin, or
`check` fails. `assert "<text>" not in ...` is exempt, because a fix passes it
by never printing the text. State a templated message with one concrete
example (`after <n> attempt(s)`, for example `after 1 attempt(s)`), because
the check matches literals.

A monkeypatch target is checked where it lives, not anywhere in the tree.
`monkeypatch.setattr(client_retry, "_now", ...)`, or the string form
`setattr("syn_x.mod.Name", ...)`, is resolved to its `syn_*` module (or a class
in one) at the pin. The attribute must be bound there (by a def, class,
assignment or import, read from the AST) or named in the task. A fixture that
patches a name only the fix adds errors every test that uses it, whatever the
patch does. A target whose module is new in the fix is left to the task's
interface paragraph.

v4 (2026-10-18) states `client_retry._now` in `token-mint-retry-5xx`. Every
one of its tests patches it in the `clock` fixture, and it existed only in the
fix. At v3 all 4 E2 runs ERRORed at setup in both arms. The tree-wide grep had
passed it, because `_now` appears at the pin in unrelated apps/syn-api tests.
Positive control: the reference fix through `eval-implement-score-v2` PASSed
(`exec-a25cdb4da7ba`). v4 is FROZEN at 2026-10-18T00:48:16Z; no case changes before the
next experiment that uses this suite reports.

v3 (2026-10-17) added `AdmissionDrainTimeoutError.unsettled` to `pause-not-blocked-by-queue`, after the check was extended to attribute reads (an attribute access, a `def` or a class-level annotation at the pin, with submodules searched at their gitlinks; a bare word is not enough, because `unsettled` existed at the pin only as a local variable).

v2 (2026-10-17) added the missing statements to `exec-status-lost`,
`codex-sandbox-tmpdir` and `token-mint-retry-5xx`. A Sonnet 5.5 pilot and an
Opus 5.5 pilot both failed the same hidden tests on a log string that existed
only in the fix.

## Admission

A case is admitted only if its hidden tests discriminate:

```
uv run python scripts/eval_implementer.py check            # git only: SHAs, first parent, hidden files at the fix
uv run python scripts/eval_implementer.py admit [--case ID] # runs the tests: minutes per case
```

`admit` scores the empty patch (must be FAIL) and the fix's own diff minus
its hidden tests (must be PASS). The five cases were chosen from fix merges on
`main` since 2026-09-15 whose tests are self-contained unit tests (no
Postgres, no Docker, no pnpm). The `admit` output for this version is recorded
in the PR that added the suite.

## Running a case

1. **Implement**: launch `eval-implement-pinned-v1` (one `implement` phase,
   Opus, `delivers_repo_changes: false`) on an eval whose Baseline pins the
   case's `commit`, with the case's `task` as the `task` input. The phase
   writes `artifacts/output/implement.patch` and pushes nothing.
2. **Score** with the container referee (#2108 S4), on a host with Docker:

   ```
   uv run python scripts/eval_referee.py --case <id> --eval <eval-id> --execution <exec-id>
   ```

   No agent carries the verdict. Per patch, the referee:

   - fetches the implement phase's one `implement.patch` artifact through the
     API (none, or more than one, is refused, never guessed);
   - bundles this repository holding the pin and the fix, and each submodule
     holding every gitlink the pin and the fix record, and mounts them
     read-only into a throwaway container from the pinned workspace image.
     Nothing is cloned from GitHub;
   - copies in `scripts/implementer_scorer.py` at a recorded commit (HEAD,
     refused if the file has uncommitted changes); that commit is part of
     `scorer_version` (`<suite version>-<commit[:12]>`);
   - runs `implementer_scorer.py prepare` with the network on: the intended
     hidden node ids collected at `fix_commit`, then a worktree at the pin
     with its `uv sync`. No agent code runs;
   - runs `docker network disconnect`, then checks the container has no
     interface but loopback. Either failing is ERROR and the patch is not run;
   - runs `implementer_scorer.py score --prepared`: apply the patch, write each
     hidden test (and every `conftest.py` the patch touches) at its
     `fix_commit` content, run pytest on the hidden files only. It never
     syncs: a prepared tree without its environment is ERROR. A prepared tree
     scores one patch;
   - takes the verdict from the scorer's exit code and its last line,
     `RESULT: <outcome>`, which must agree (a crash is ERROR, not FAIL), and
     records it as `EvalRunScored`, scorer `eval_implementer.py`.

   Before any agent patch of a case, the reference fix (must PASS) and the
   empty patch (must FAIL) run through this same path in the same invocation.
   If either does not hold, no agent patch is scored.

   | Result | Exit | When |
   |---|---|---|
   | PASS | 0 | every intended hidden test ran and passed |
   | FAIL | 1 | the patch does not apply, a hidden test failed, a hidden test could not be collected (the change does not provide what it imports, or needs the network), or one was skipped, xfailed, deselected or never reported |
   | ERROR | 2 | the environment or the referee: the pin, a submodule commit or a hidden file is missing, `uv sync` failed, the network could not be cut, the prepared environment is gone, pytest erred internally or collected nothing, or the run timed out |

   pytest's exit 0 alone is not a PASS: it also covers skipped, xfailed and
   deselected tests, so a patch that adds a skip hook would earn it. The
   intended set is the node ids pytest collects from the hidden files at
   `fix_commit`, where no agent code exists. A recording plugin loaded from
   outside the tree reports how each one ended, and each must have a passing
   `call`. What this does not stop: code the tests import runs in the same
   process as pytest and can tamper with it. The container bounds what that
   code can reach; it does not make the in-process judge tamper-proof.

   `eval_implementer.py score --case <id> --patch <diff>` runs the same scorer
   on a host, with the network on. It is for debugging a case, never for a
   recorded score. `eval-implement-score-v1` and `-v2` (an agent ran the
   scorer and reported its result) are retired; archive them on any deployment
   that still has them.

`launch` and the score ledger are not wired into `scripts/eval_suite.py` for
this kind yet. That script's `Case`, scoring and `_report_of` all assume a
verifier report. Today the implement run is launched like any eval run, and
the referee is run by hand per case.

## Leakage: NOT prevented today

The task requires that the workspace cannot fetch commits after the pin or
read the fix PR. **The platform cannot guarantee that today.** The suite
relies on the phase prompt's rules, which an agent can break:

| Channel | Why it is open | What closing it needs |
|---|---|---|
| Local object store | The provisioning clone is a full `git clone` of the default branch (`setup_phase_secrets.py`). The pin is a `checkout --detach` on top of it (`pinned_checkout.py`), so `git log --all` or `git show <fix>` already reach the fix, offline | A pinned-clone mode: `git init` + `git fetch --depth=1 origin <sha>` (or a bundle made at the pin), with no other refs and no remote-tracking branches |
| Remote fetch | Setup writes a GitHub credential to `~/.git-credentials` and logs in `gh` (#725), so `git fetch` and `gh pr view` work | A phase-level "no repo credential" option for read-only phases. An eval phase that writes a patch needs no credential after the clone |
| Network | The Envoy sidecar's egress allowlist works per host. github.com has to be allowed for the clone, so it cannot block "commits after X" | Clone during setup, then drop github.com from the allowlist for the agent's phase (or give the phase an empty allowlist) |

Until all three exist, a PASS means "the hidden tests passed on the agent's
patch". It does not prove the agent never saw the fix. Read the run's tool
trace (Bash commands that name `git log --all`, `git show`, `fetch`, `gh`)
before trusting an unexpectedly good score. Tracked as a follow-up on #1725.
