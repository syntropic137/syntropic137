# Pre-PR Checklist

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.


CI failures that could have been caught locally waste 8–10 minutes per round-trip and block the release chain. Always run these before pushing:

```bash
just qa-ci           # Every PR-gating CI JOB that CAN run locally, using the
                     # same commands those jobs use. ~3m30s. This is the check
                     # to run before pushing.
                     #
                     # It is job-level coverage, NOT proof of equivalence. CI
                     # runs on Ubuntu with pinned toolchains and a clean
                     # checkout; a step added inside an existing job, a widened
                     # matrix, or a change inside a reusable workflow is
                     # invisible to the parity gate. Never local at all:
                     # osv-scan, pip-audit, dependency-review (remote data),
                     # e2e-container, and the release-only gates.

just preflight       # The static half only (~1m). Faster inner loop; what the
                     # pre-push hook runs. A green preflight does NOT mean CI
                     # will pass - it runs no tests and no builds.

just preflight-agent # The subset of preflight that runs INSIDE an agent
                     # workspace container. Use this one only there: the image
                     # ships just, uv and node and nothing else, so vsa,
                     # cargo, pnpm, docker and registry credentials are all
                     # absent and seven gates cannot run at all (#1109).
                     # All of fitness runs: the APS thresholds via
                     # scripts/agent-fitness.sh (#1498) AND the pytest
                     # ci/fitness invariants. Docker-backed fitness tests
                     # skip there as a listed `NOT RUN`; CI runs them.
                     # On a dev machine run the full `just preflight` instead.
```

`scripts/check_ci_parity.py` (inside `preflight`) discovers every workflow that
triggers on `pull_request` and fails when one of their jobs has no entry: either
a just target that mirrors it, or a stated reason it cannot run locally. Add a
PR-gating job and you must map it there. Add a new static gate to `preflight`,
never to CI alone (#931).

`just qa` remains the broader local sweep (it runs non-unit tests too), but it is
not CI-shaped: some of its targets are deliberately more lenient than CI's.

**Git hooks:** `.githooks/pre-push` runs the fast checks automatically. Wire it up once with `just setup-hooks` after cloning.

**For small fixes on already-merged PRs** (formatting nits, Copilot review comments): push directly to `main` with `git push origin <branch>:main` rather than opening a new PR. Keeps the release chain unblocked.
