# Map what this change touches

$ARGUMENTS

Your job this phase is to produce a map, not a verdict. Do not decide whether the
change is good. A phase that judges while it investigates stops investigating,
because forming an opinion feels like progress.

## What to produce

1. **The claim.** State, in one sentence, what this PR says it accomplishes. Take
   it from the PR description and the commit message. If those disagree, say so.

2. **The path the claim depends on.** The claim is almost never confined to the
   diff. If the PR says a value is recorded and exposed, the path runs from
   wherever it originates, through every hop that carries it, to whatever a
   consumer reads. Walk it in the actual code and write down each hop with its
   file and line.

3. **The hops the diff does NOT touch.** These matter most. A change is usually
   correct in the lines it edits and wrong in a hop it assumed. List every hop on
   the path that the diff leaves alone, because the next phase will attack those
   first.

4. **What the tests cover.** For each hop, note whether a test exercises it. Be
   specific about which side of a boundary a test sits on: a test that constructs
   an object and asserts its fields proves the object, not the wire that carries
   it somewhere else.

5. **What you could not determine.** Anything you tried to establish and could
   not. This is not a failure; an unverified hop that is labelled is useful, and
   one that is quietly assumed is worse than useless.

## How to work

Every factual claim needs a command and its real output, pasted. Not a summary of
what you saw. If you write that something does not exist, show the search that
proves absence rather than reasoning that it must be so.

Read the diff with `git diff origin/main...HEAD`, but do not stop there - most of
this phase is reading code the diff does not contain.

You are read-only. Do not edit files, do not commit, do not push.
