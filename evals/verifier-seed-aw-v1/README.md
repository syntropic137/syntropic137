# verifier-seed-aw-v1: the verifier seed suite for agentic-workspace

The same eval as [verifier-seed-v1](../verifier-seed-v1/README.md), over
`AgentParadise/agentic-workspace` instead of syntropic137. An eval's baseline
pins one SHA per repository, so a second repository is a second suite.
Every rule is verifier-seed-v1's and lives in its README: how a defect case
is pinned, how a clean control is chosen, how a blocked run is judged, and
how a case is retired. This file holds only what differs.

## Checking it

`check` reads the pins from an agentic-workspace checkout, so name one:

```
git submodule update --init lib/agentic-workspace
git -C lib/agentic-workspace fetch origin
uv run python scripts/eval_suite.py check --suite evals/verifier-seed-aw-v1 --repo lib/agentic-workspace
```

Without `--repo`, `check` looks in syntropic137 and reports every pin as
missing.

## What differs

- **Clean controls come from imported history.** agentic-workspace's mainline
  before 2026-09-25 was imported from `AgentParadise/agentic-primitives`, and
  its own PR numbers restart there. A control merged before then has
  `source_pr` set to the agentic-primitives PR its merge names. Rule 2's
  search covers both repositories.
- **Non-Python expected files.** `scripted-agent-tests-not-in-ci` expects
  `.github/workflows/ci.yml`: the defect is a package the CI matrix omits,
  visible in the diff without running anything.
