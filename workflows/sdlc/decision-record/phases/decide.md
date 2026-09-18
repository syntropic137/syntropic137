# Choose a path, and draft the plan

You have the framing and paths (`artifacts/input/options/options.md`) and a
different model's attack on them (`artifacts/input/attack-options/attack.md`).
This is the only phase allowed to choose.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## First, dispose of every attack finding

For each finding: **accept** (and say what it changes) or **reject** (with
`file:line` evidence). Rejecting is expected; a reviewer can be wrong, and
deferring to a wrong finding makes the decision worse while looking responsive.
If the attack proposed a new path, treat it as a peer of the original paths.

## Then decide

Choose ONE path. It may be a combination, but say plainly which parts come from
which path. Write:

- **The decision**, in one sentence.
- **Rationale** - why this path beats each alternative against the success
  criteria. Name the specific criterion each rejected path loses on.
- **Rejected paths** - each, with the reason, so nobody re-litigates it without
  new evidence.
- **Load-bearing assumptions** - the claims this decision stands or falls on.
  Number them `A1`, `A2`, ... Each must be:
  - a **falsifiable statement**, not a topic
  - paired with the **experiment that would falsify it**: the exact command or
    observation, and which outcome means the decision is wrong
  - something **not already settled** by the repository; if grep answers it,
    answer it now and cite it
- **What would change this decision** - the evidence that should send us to a
  different path, and which one.
- **Needs human ratification?** - say whether the choice is one an agent may
  make, or one that belongs to the operator (product direction, a public
  contract, an irreversible data decision). If it belongs to the operator, say
  so; you still recommend.

## Then draft the plan

For the chosen path: steps in order, each with its `file:line` targets, how
each is verified, and what is out of scope. Mark every step that depends on an
assumption in the list above.

## Write to `artifacts/output/decision.md`

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it. An abbreviated path is not a smaller citation, it
is an unusable one: a reader cannot follow it and a checker cannot verify it.

## Rules

- Decide. A document that lists paths again and declines to choose has not
  done this phase's job.
- No production code, no commits.
