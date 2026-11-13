# dreamship-implement-v8

Implement a DreamShip bead behind a failing test and open the PR, have Codex try
to falsify it, then fix what the review blocked on.

v8 keeps v7's prompts, models, phase order, timeouts and pinned skills, and
fixes the two gaps that v7's proof run (exec-204170cce3f0, PR #2191) found.

1. **`software-leverage-review` never ran.** Its SKILL.md says to start it with
   `claude -p`, and inside a workspace `claude -p` answers `Not logged in`.
   - The only reason it asks for `claude -p` is to get a top-level session that
     can dispatch subagents. A phase agent already is one.
   - So in v8, implement and remediate run it in their own session, as its
     orchestrator, dispatching one reviewer per leverage point with the Agent tool.
   - Its fan-out needs every point in its `slp-manifest.yaml`, so all 20 are
     installed in those two phases.
   - Each phase writes the report under `artifacts/output/slr-<phase>/`, where
     it is kept as an artifact, and posts it on the PR.
2. **The review phase saw only part of four skills.**
   - Codex cuts long tool output in the middle. One `cat` over all eight skills
     reached the model at 60% (security), 85% (testing), 92% (vertical-slices)
     and 94% (software-leverage-review).
   - The four skills it then re-read one at a time arrived in full.
   - So the review prompt now asks for one file per command, with no `rtk` and
     no loops, and a line count printed for each skill.

## Usage

```bash
syn workflow install workflows/dreamship/implement-v8
syn workflow run dreamship-implement-v8 --repo AweHelm/dream-ship-os -t "<bead id and spec>"
```

## Skills

Every skill is pinned to a commit:

- `syntropic137/software-leverage-points` at 9dad3b8f;
- DreamShip's own skills, `AweHelm/dream-ship-os/.claude/skills`, at a3cbd316.

| Phase | Agent | Loaded first | Also installed for software-leverage-review's reviewers |
|---|---|---|---|
| implement | claude opus | software-leverage-review, software-complexity, principles-and-patterns, dry, types, error-handling, testing, architecture, security, documentation; DreamShip: managing-beads, canonical-knowledge, delivery-process, merging-a-pr, red-gates-and-fitness, code-quality-assurance, vertical-slices, foundational-books, systematic-rename | the other 11 manifest points |
| review | codex gpt-sol | software-leverage-review, testing, security, architecture; DreamShip: canonical-knowledge, red-gates-and-fitness, code-quality-assurance, vertical-slices | none, because review does not run it |
| remediate | claude opus | software-leverage-review, testing, security, architecture; DreamShip: managing-beads, delivery-process, merging-a-pr, red-gates-and-fitness | the other 17 manifest points |

**Cost.** By its own SKILL.md, `software-leverage-review` costs about $15-25 and
10-15 minutes per run. v8 runs it twice per workflow run: in implement, and in
remediate on remediate's own fixes.

DreamShip's repo also carries its own copies of several leverage-point skills.
Skill names must be unique in a workspace, so v8 takes the leverage-point
repo's copies.

## Timeouts

Unchanged from v6. See [implement-v6](../implement-v6/README.md) for the evidence.
