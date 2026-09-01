# Revise the spec, and fix the unknowns list

You have both prior phases:

- `artifacts/input/research/spec.md` - the spec
- `artifacts/input/review-spec/review.md` - a different model's review of it

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## What to do

Work through the review finding by finding. For EACH one, either:

- **Accept** - change the spec, and say what changed.
- **Reject** - explain why the reviewer is wrong, with `file:line` evidence.

Rejecting is expected. A reviewer can be mistaken, and deferring to a wrong
finding makes the spec worse while looking responsive. Check anything you are
unsure about against the code rather than trusting either document.

Where the review says a stated fact was unverified, do one of two things: verify
it now and cite it, or demote it to an unknown. Do not leave it as prose.

## The final unknowns list is this phase's real output

The next phase runs one subagent per numbered unknown and cannot ask you what
you meant. This list is the contract. Produce it as a numbered table:

| # | The claim, stated so it can be false | How it would be settled | What outcome means FALSE |

Rules for the list:

- **Delete any unknown the review showed is already answered**, and move the
  answer into the body of the spec with its citation. Testing a known thing
  spends a subagent to produce a foregone conclusion.
- **Add the unknowns the review proposed**, if you accept them.
- **One claim per number.** An unknown that bundles two questions returns one
  verdict for two things, and whichever half was not tested reads as settled.
- **The settling evidence must be an observation, not an opinion.** A command
  and its output, or a file that would only exist if the thing happened. "Ask a
  model whether this is supported" is not a way to settle anything.
- Order them so that the ones a plan most depends on come first. If the
  experiment phase runs short, the important ones are done.

## Write to `artifacts/output/spec.md`

The COMPLETE revised spec, standalone. Whoever reads it next should not need the
review or the first draft. It ends with the numbered unknowns table above, and
then:

## Review disposition

| finding | accepted / rejected | what changed |

Every finding in the review gets a row. A finding silently dropped looks
identical to one that was considered and rejected, and only one of those is
honest work.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it - for example
`packages/syn-domain/src/syn_domain/contexts/orchestration/_shared/value_objects.py:85`,
never `_shared/value_objects.py:85`.

An abbreviated path is not a smaller version of a citation, it is an unusable
one. `_shared/value_objects.py` matches four bounded contexts in this
repository and identifies none of them, so a reader cannot follow it and a
checker cannot verify it. Measured across three runs: every cited file was
real, and up to 100% of citations were unusable purely because of this.

## Rules

- Still a spec. Do not write a plan, and do not decide the approach.
- The aim is a document that stays true, not one that looks finished.
