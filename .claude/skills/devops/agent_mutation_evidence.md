# Agent: Gather mutation evidence for a PR

## Purpose

Prove that the tests a PR adds actually catch the bug they claim to, without
Docker on this machine. Local Docker verifier runs are banned (permission
prompts) and agent workspaces have no Docker, so the run happens on a GitHub
runner: `.github/workflows/mutation-evidence.yml`, dispatch-only. Use it when a
reviewer or a verify phase asks "does this test kill the bug?".

## Workflow

1. On the PR branch, write each mutation as a real patch of NON-test source and
   commit it under `.mutations/` (one bug per file, `NN-short-name.patch`):
   ```
   # edit the source to re-introduce the bug, then:
   git diff -- path/to/source.py > .mutations/01-drop-guard.patch
   git checkout -- path/to/source.py
   git add .mutations/01-drop-guard.patch && git commit -m "test: mutation evidence patches"
   ```
   A `.mutations/README.md` mapping each patch to the test meant to kill it
   helps the reviewer; the runner only reads `*.patch`.
2. Push (normal pre-push hook; `.mutations/` is not in preflight).
3. Dispatch and wait, from the local machine:
   ```
   just mutation-evidence 1929 "packages/x/tests/test_y.py::test_z scripts/tests/test_a.py"
   ```
   It prints the run URL, waits, prints the table, and exits non-zero unless
   every mutation was killed. The same table is the job summary and ONE PR
   comment (marker `<!-- mutation-evidence -->`, updated in place on re-runs).
4. Read the verdict:
   - `killed`: a named test failed (or collection broke) with the patch applied,
     and pytest listed it.
   - `SURVIVED`: every named test passed. Fix the test, or the patch is wrong.
   - `APPLY FAILED` / `NOT APPLIED`: the patch is stale or empty. Regenerate it.
   - `REFUSED`: vetted before applying. A patch may not touch a named test
     file, anything test-shaped (tests dirs, `test_*.py`, conftest), pytest or
     build config (pyproject, uv.lock), `.github/`, `ci/fitness/`, `lib/`, a
     symlinked path, a git-ignored path, or paths it did not declare.
   - `ERROR`: pytest exited without a failure on record (interrupt, timeout,
     usage error). Not a kill.
   - Baseline red or zero tests ran: evidence void, nothing else was run.
5. Before merge, delete `.mutations/` in a final commit. CI job
   `mutations-not-merged` fails any PR into main that still tracks it ("delete
   .mutations/ before merge; evidence is in the mutation-evidence comment").
   The comment, which names the head SHA, is the record; with merge commits the
   patches also stay reachable in that SHA's history.

## What the runner guarantees

- Inputs are validated by `scripts/mutation_evidence.py` (strict node-id and
  path patterns, no `..`, no option-like segments, `mutations_dir` under
  `.mutations/`) and reach shell only via env.
- PR code never runs on the runner host: `uv sync` and every pytest run happen
  in a pinned uv container with the checkout mounted, `.git` read-only, no
  Docker socket and only the test env vars. The trusted runner, its report and
  the comment token stay out of reach. Consequence: a named test that itself
  needs Docker cannot run here.
- The named tests must pass on the unmutated head first.
- Each patch: `git apply --check`, apply, non-empty diff, non-test files only,
  bytecode cleared, tests run, tree restored and proven clean.
- Tests run with `-m ""`, so a named integration test runs (timescaledb and the
  gitlink-pinned event store are up, same setup as CI's integration job via
  `.github/actions/python-integration-env`).

## What it does not prove

- A survival is against the NAMED tests only; a wider suite may still kill it.
- A kill proves the test is real, not that the fix is right for every input
  shape production produces. Ask that question separately.

## Hard rules to honor

- Patches only. Never ask for free-form sed/shell mutations.
- Fork PRs are refused. The run uses the head SHA at dispatch time; push first.
- Dispatch from the local machine (`gh`); a workspace agent cannot.
- No em dashes; plain hyphens.

## Health check

If this file is out of date with the repository (workflow inputs, recipe name,
verdict labels in `scripts/mutation_evidence.py`), STOP and note the drift,
then fix this file inline or escalate.
