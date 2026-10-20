# Agent: Gather mutation evidence for a PR

## Purpose

Prove that the tests a PR adds actually catch the bug they claim to, without
Docker on this machine. Local Docker verifier runs are banned (permission
prompts) and agent workspaces have no Docker, so the run happens on a GitHub
runner: `.github/workflows/mutation-evidence.yml`, dispatch-only. Use it when a
reviewer or a verify phase asks "does this test kill the bug?".

## Workflow

1. On the PR branch, write each mutation as a real patch of production or harness source (never a test module) and
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
   By default PR code runs on the runner host with Docker, timescaledb and the
   event store, like CI's integration job, so Docker-backed tests (docker
   compose, e.g. the broker suite) run. For tests that need no Docker, a third
   argument `false` uses the socket-less sandbox instead:
   `just mutation-evidence 1929 "<ids>" false`. See "What the runner
   guarantees".
   It prints the run URL, waits, prints the table, and exits non-zero unless
   every mutation was killed. The same table is the job summary and ONE PR
   comment (marker `<!-- mutation-evidence -->`, updated in place on re-runs).
4. Read the verdict:
   - `killed`: a named test failed (or collection broke) with the patch applied,
     and pytest listed it.
   - `SURVIVED`: every named test passed. Fix the test, or the patch is wrong.
   - `APPLY FAILED` / `NOT APPLIED`: the patch is stale or empty. Regenerate it.
   - `REFUSED`: vetted before applying. A patch may touch ANY production
     source, including harness and adapter code that lives under `tests/`
     (a broker stand-in is production for the test). It may not touch a named
     test file, a test module (`test_*.py`, `*_test.py`, `*.test.*`,
     `*.spec.*`), a test package `__init__.py`, conftest, any pytest config
     (pyproject, pytest.ini, pytest.toml and dot-variants, tox.ini,
     setup.cfg), a lockfile (`*.lock`, pnpm/npm/bun locks, go.sum), `.github/`
     or `ci/`, `.mutations/`, a submodule (mutate it in its own repo), a symlinked
     or git-ignored path, or paths it did not declare; renames and copies are
     refused.
   - `ERROR`: pytest exited without a failure on record (interrupt, timeout,
     usage error). Not a kill.
   - Baseline red, zero tests ran, or a named test SKIPPED, XFAILED or
     XPASSED: evidence void,
     nothing else was run. A skip would pass under every mutant; it usually
     means a Docker-backed test was run with `docker=false`.
5. Before merge, the orchestrator deletes `.mutations/` in a final commit,
   only after the comment reports PASS for the PR's current head SHA. CI job
   `mutations-not-merged` fails any PR into main that still tracks it. That red
   check is not a defect for a workflow phase to fix: a phase that deletes the
   patches before the PASS leaves nothing but a workspace rerun, which is not
   trusted evidence (#2028).
   The comment, which names the head SHA, is the record; with merge commits the
   patches also stay reachable in that SHA's history.

## What the runner guarantees

- Inputs are validated by `scripts/mutation_evidence.py` (strict node-id and
  path patterns, no `..`, no option-like segments, `mutations_dir` under
  `.mutations/`) and reach shell only via env.
- Default (`docker=true`): PR code runs on the runner host, where it can reach
  the Docker daemon and so could forge its own report. That evidence is for
  honest PR code. No secrets or write tokens exist in the job, and the
  workflow has no cache access.
- `docker=false`: `uv sync` and every pytest run happen in a pinned uv
  container with the checkout mounted, `.git` read-only, no Docker socket and
  only the test env vars, so the trusted runner, its report and the comment
  token stay out of reach. A named test that needs Docker skips there, which
  voids the baseline.
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
