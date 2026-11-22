# dreamship-implement-v7

Implement a DreamShip bead behind a failing test and open the PR, have Codex try
to falsify it, then fix what the review blocked on.

v7 keeps v6's prompts, models, phase order and timeouts, and adds skills to
every phase. v6 and every earlier version loaded no skills: the agent runs with
`cwd=/workspace`, so it never discovers the cloned repo's `.claude/skills`. Its
implement transcript for exec-4083dbff1956 lists only Claude Code's built-in
skills. The operator stopped the line over this on 2026-11-06.

## Usage

```bash
syn workflow install workflows/dreamship/implement-v7
syn workflow run dreamship-implement-v7 --repo AweHelm/dream-ship-os -t "<bead id and spec>"
```

## Skills

Every skill is pinned to a commit:

- `syntropic137/software-leverage-points` at 9dad3b8f;
- DreamShip's own skills, from `AweHelm/dream-ship-os/.claude/skills` at a3cbd316.

DreamShip's skills resolve through the `.claude/skills/<name>/` lookup that this
change adds to the CLI's `skillDirInClone`.

| Phase | Agent | Leverage-point skills | DreamShip skills |
|---|---|---|---|
| implement | claude opus | software-leverage-review, software-complexity, principles-and-patterns, dry, types, error-handling, testing, architecture, security, documentation | managing-beads, canonical-knowledge, delivery-process, merging-a-pr, red-gates-and-fitness, code-quality-assurance, vertical-slices, foundational-books, systematic-rename |
| review | codex gpt-sol | software-leverage-review, testing, security, architecture | canonical-knowledge, red-gates-and-fitness, code-quality-assurance, vertical-slices |
| remediate | claude opus | software-leverage-review, testing, security, architecture | managing-beads, delivery-process, merging-a-pr, red-gates-and-fitness |

Each phase prompt names its skills and asks the agent to load them first and to
print `SKILLS LOADED:` as its first output line. Agents rarely invoke a skill the
prompt does not name, so naming them is part of loading them.

**Known limit.** `software-leverage-review` fans out to subagents through
`claude -p`, and a phase is already a subagent. The implement and remediate
prompts ask the agent to run it on the diff and to say so if it cannot run. The
first run with v7 is the measurement.

DreamShip's repo also carries its own copies of several leverage-point skills
(architecture, dry, types and others). Skill names must be unique in a
workspace, so v7 takes the leverage-point repo's copies, and the DreamShip copies
of those names are not installed.

## Timeouts

Unchanged from v6. See [implement-v6](../implement-v6/README.md) for the evidence.
