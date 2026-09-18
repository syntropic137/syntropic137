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

Your job is to try to make the PR's central claim FALSE, and to report honestly
whether you succeeded. A review that sets out to confirm a change finds it
confirmed.

## First: pin the refs you are reviewing

**You are in a fresh workspace on the default branch** - the PR's code is not
checked out here. The previous phase recorded a base SHA and a head SHA. Work
from those SHAs and not from the branch names, so that what you are reviewing
cannot move while you review it:

```
git fetch origin
git rev-parse origin/<pr-branch>     # THE GATE: must equal the recorded head SHA
git rev-parse origin/main            # for the record only - NOT a gate
git diff <recorded-base>...<recorded-head>
```

**The head is the review; the base is not.** One of those two refs moving
invalidates your work and the other does not, and treating them alike costs a
whole run:

| what moved | what it means | what you do |
|---|---|---|
| **the head** | the code under review changed, and the map you were given describes commits that are no longer the PR | stop and report it. Findings against a superseded head send the author to fix what is already fixed |
| **`origin/main`** | unrelated work landed while you ran; the head is exactly the one that was recorded | keep going, and record the move |

A queue merges to `origin/main` here, so base movement is the normal condition
of this repository rather than an exception: a review that halts for it cannot
run concurrently with a merge, and one that did halt threw away $10.09 of
finished work and delivered no verdict (#1290). None of the commands above read
`origin/main` as an input, so the move costs you one line of disclosure and
nothing else. Put that line in your output, so the report can carry it:

```text
Reviewed against base `<recorded-base>`; `origin/main` has since moved to `<current-main>`.
```

### When the merge, and not the head, is what you are judging

Some findings are not about the head alone: "this caller no longer exists",
"this collides with what just landed", "these two changes are each correct and
contradict each other". Those are claims about the MERGE RESULT, and the merge
visible from the recorded base is the one that existed when the map was
written. Asserting such a claim against a base you know has moved is the same
dishonesty as reviewing the wrong head, pointed the other way.

So produce the merge before you make one, and say which base it is against:

```
git checkout -b merge-check <recorded-head> && git merge origin/main
```

A conflict is a finding, not a reason to stop. Restore the tree afterwards, as
the read-only rule below requires. If you cannot produce the merge, say the
claim is unsettled against current `origin/main` rather than asserting it
against the old base - an unsettled claim that is labelled is useful, and one
that is quietly stale is not.

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
