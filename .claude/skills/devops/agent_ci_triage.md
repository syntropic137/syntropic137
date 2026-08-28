# Agent: Investigate a CI failure (smoke test, release gate, release pipeline)

## Purpose

Diagnose which workflow failed, separate flake from real bug, and decide whether to re-run or escalate. Matches SKILL.md "When to invoke" triggers: "What's blocking the release?", "CI failed on the release PR", "smoke test broke".

## Workflow

1. Get the full check rollup for the PR.
   ```
   gh pr view <N> --json statusCheckRollup
   ```
2. Identify which workflow failed and read its YAML before guessing at causes.
   - `.github/workflows/ci.yml` - standard PR/main CI (lint, format, typecheck, unit, fitness, codegen drift)
   - `.github/workflows/smoke-test.yml` - selfhost compose stack health (single-arch, AMD64)
   - `.github/workflows/release-gate.yml` + `.github/workflows/_check-*.yml` - release PR gate (version, codegen, multi-arch dry-run, OSV, pip-audit)
   - `.github/workflows/release-create.yml` - post-merge publish pipeline (release tag, GHCR, npm)
3. Pull the failed job logs.
   ```
   gh run view <run-id> --log-failed
   ```
4. Match against known flake classes. If it's one of these, re-run once before investigating:
   - `apt-get` DNS failures during base-image build
   - `corepack` pnpm fetch transient failures
   - `undici.UND_ERR_SOCKET` from npm/registry
   - Transient GHCR / docker registry 5xx
   ```
   gh run rerun <run-id> --failed
   ```
5. If it fails twice in a row on the same step, treat as a real bug. Common root causes from past incidents:
   - Envoy / sidecar base-image apt rot (the v0.25.3 -> v0.25.4 lesson; rebuild locally to confirm)
   - Codegen drift (`just docs-sync` not run; CLI types or OpenAPI spec stale)
   - Missing `GH_TOKEN` / OIDC permission intersection in a release workflow
   - `vsa manifest` not run in fresh worktree (manifest missing)
6. Check `docs/retrospectives/` for prior incidents matching the symptom before opening a fresh investigation.
7. Escalate to the operator with: failed workflow name, failed step, error excerpt, prior occurrences, and recommended fix.

## References

- `.github/workflows/release-create.yml`, `release-gate.yml`, `_check-*.yml`, `smoke-test.yml`, `ci.yml`
- `docs/release-process.md` "Failure recovery" section
- `docs/retrospectives/` - prior incident write-ups (e.g. envoy base-image rot)
- Memory: `project_release_pipeline_lessons` - workflow_call / OIDC pitfalls (operator-local; ask if needed)

## Hard rules to honor

- Re-run once for known flake classes; do not spam reruns (`feedback_no_polling_loops`).
- Never approve a release deployment gate to "unblock" CI; human only.
- Never `--no-verify` locally to "match" a failing CI step.
- No em dashes; pre-push hook blocks them.

## Health check

If this file is out of date with the repository (workflow names changed, file paths moved, hard rules contradicted by current behavior), STOP and:
1. Note the drift in the response to the user.
2. Either fix this file inline (preferred for small drift) or escalate to the user with a one-line summary of what needs updating.

Keeping these skill files healthy is a higher priority than completing the immediate task with a stale recipe.
