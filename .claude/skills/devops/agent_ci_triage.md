# Agent: diagnose a red check

## Purpose

Find which workflow and step failed, separate flake from defect, and either
rerun once or fix. Covers PR CI, `main` push runs, the release gate and the
release pipeline.

## Workflow

1. Get the rollup and the failing run.
   ```
   gh pr view N --json statusCheckRollup --jq '.statusCheckRollup[]|select(.conclusion=="FAILURE")|{name,detailsUrl}'
   gh run view <run-id> --log-failed | tail -100
   ```
2. Read the workflow YAML for that job before guessing. Map:
   - `ci.yml`: `python-qa`, `architectural-fitness`, `python-unit-tests`, `python-integration-tests`, `dashboard-ui`, `docs-site`, `cli-node`, `submodule-check`, `default-workspace-image`, `osv-scan`, `pip-audit`, `dependency-review`, `ci-success`.
   - `docs-lint.yml`, `syn-ui.yml`, `syn-landing.yml` on PRs; `smoke-test.yml`, `docs-drift.yml` on `main` pushes only; `e2e-container.yml` on PRs and `main` pushes touching workspace paths (image build probe), with the real agent run only on manual dispatch (`run_full_e2e=true`).
   - `release-gate.yml` (+ `_check-*.yml`) on PRs into `release`; `release-create.yml` -> `release-containers.yaml`, `release-cli.yaml` after merge; `release-beta.yaml` on prereleases.
3. Reproduce locally with the mirror target. `scripts/check_ci_parity.py` maps each PR-gating job to a `just` target; `just qa-ci` runs them all. Not local: osv-scan, pip-audit, dependency-review, e2e-container, release-only gates.
4. Known flake classes, rerun once: apt or DNS failures in image builds, corepack/pnpm fetch, `UND_ERR_SOCKET`, registry 5xx. `gh run rerun <run-id> --failed`. Twice on the same step is a defect.
5. Known defect classes:
   - Release notes check red: `_check-changelog.yml` reads `github.event.pull_request.body`, the frozen payload. Editing the body and re-running replays the old body and never clears it; push a commit or close/reopen to get a fresh event.
   - Codegen or OpenAPI drift: run `just codegen`, commit the rewrites.
   - Event-store pin: the ESP gitlink names a version whose `event-store` image is unpublished; ESP must release first (`just check-event-store-pin`).
   - `check-pinned-image-channels`: the `lib/agentic-workspace` gitlink must equal the commit `PINNED_DIGESTS` was built from; the gate reads `git ls-tree HEAD`, so commit before re-running.
   - Fitness ratchet: a value went up; fix the code, never raise the budget.
   - Reusable-workflow permissions: a callee cannot widen the caller's grants; declare the union on the caller.
   - Base-image rot (2026-05-01 envoy retro): rebuild locally to confirm.
   - `Mutation Patches Not Merged` red: not a defect, and never fixed by deleting `.mutations/` from a workflow phase or agent workspace. The PR still tracks the patches that trusted mutation evidence runs from. The orchestrator removes them, and only after the `<!-- mutation-evidence -->` PR comment reports PASS for the current head SHA (#2028). To gather that evidence (dispatch-only, never on a PR event) read `agent_mutation_evidence.md`.
   - Green in CI, red locally: CI may never collect that test. Check its marker against the job's selection (`-m unit` over testpaths; `ci/fitness -m architecture`) before calling it flaky (#1935).
6. A red `main` blocks every PR. Fix it first, via `agent_hotfix.md` if trivial.
7. Search `docs/retrospectives/` for the symptom. Report: workflow, job, step, excerpt, flake or defect, prior occurrences, fix.

## Health check

Depends on: the job ids listed in step 2 (`grep -nE '^  [a-z][a-z0-9-]*:$' .github/workflows/ci.yml`); `_check-changelog.yml` taking `pr_body` from the event payload; `just check-event-store-pin`, `check-pinned-image-channels`, `scripts/check_ci_parity.py` existing. If a workflow was added, renamed or re-triggered, update step 2 in the same session.
