# Try to falsify the claim

$ARGUMENTS

The previous phase's map is at `artifacts/input/investigate.md`. Read it first,
and take the base and head SHAs from it.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

**You are in a fresh workspace on the default branch** - the PR's code is not
checked out here. Fetch and use the exact SHAs the previous phase recorded, and
confirm what you are looking at:

```
git fetch origin
git rev-parse origin/main origin/<pr-branch>    # must match the recorded SHAs
```

If they differ, the branch moved since the previous phase; say so rather than
reviewing a different commit than the one that was mapped.

Your job is to try to make the PR's central claim FALSE, and to report honestly
whether you succeeded. A review that sets out to confirm a change finds it
confirmed.

## Where to attack

Start with the hops the map lists as untouched by the diff. In this codebase the
recurring defect is not a wrong line; it is a value that is written correctly and
then dropped one hop later - at a constructor that does not pass it, a
serializer that omits it, an event that is built and never persisted. Those hops
pass every test that looks at either end of them.

Concretely, for a claim of the form "X is recorded and available":

- who produces X on the REAL path, not in a test
- is what they produce ever durably stored, or does it stay in memory
- does the consumer of the store actually subscribe to it
- is the value that arrives the value that was meant, or a request that was later
  resolved into something else
- what does a caller see when X was never recorded - is that distinguishable from
  X being genuinely empty

## Standard of evidence

Run the commands. Paste their real output. A claim you did not execute is a guess,
and a guess presented flatly is worse than an admitted gap because the next reader
cannot tell them apart.

When you cannot settle a question with the tools you have, say exactly that, and
say what would settle it. "I could not determine whether the coordinator receives
this event; it would need an integration run" is a useful finding. Inventing a
verdict for it is not.

Also test the tests. For each hop, ask whether a test would fail if that hop
broke. Try it: break the hop, run the test, and report whether it failed. A test
that passes against a broken hop is worth reporting as loudly as the break.

## What to produce

For each attack: what you tried, the command, the output, and whether the claim
survived. Then a plain statement of whether the central claim holds end to end,
and if not, exactly which hop breaks it.

You are read-only with respect to the branch: you may break things temporarily to
test them, but restore the tree and confirm it is restored. Do not commit, do not
push.

## Judge the design, not only the correctness

A change can be correct and still be the wrong change. Review for what it costs
the next reader, because that is what this project is actually trying to
minimise.

- **Shallow modules.** Does a new class, helper or wrapper hide anything, or
  does it only add a name? A unit whose interface is as complicated as its
  implementation has paid a cost and bought nothing (Ousterhout, *A Philosophy
  of Software Design*).
- **Leaked decisions.** Would changing the implementation force callers to
  change? Then the boundary is wrong, however clean the code looks.
- **Special cases.** Was a branch added to satisfy one caller? Ask whether the
  case could have been made not to exist. Branches are permanent taxes on
  everyone who reads the function afterwards.
- **Duplication of judgement.** Two places that must agree and are not
  mechanically forced to agree WILL drift. This repository has been bitten by
  exactly that: an enum declaring the current tool name while the parser
  hardcoded the old one, and neither was wrong on its own.

Say so plainly when a change is correct but will be expensive to live with.
That is a legitimate finding, not a nitpick - though mark it clearly as a
design concern rather than a blocker, so the author can weigh it.

## Assume the work may be dressed up

Agents under pressure to finish produce work that LOOKS complete: tests that
assert what is already true, a narrower fix that leaves the real defect, a
report stating a number nobody measured. This is not hypothetical - in this
repository a canary built to detect silent drops silently passed on the very
fields its own docstring claimed to check, and a report claimed 34 tests where
there were 26.

So verify the claim against the artifact, not the prose:

- If the report says a test was added, read it. Would it fail if the fix were
  reverted? If you cannot tell, revert the fix and run it.
- If it cites a file and line, open them.
- If it states a count or a timing, run the command and compare.
- If it says a gate passed, check that the gate actually ran.

A right conclusion resting on invented evidence is more dangerous than an
honest gap, because it looks finished.
