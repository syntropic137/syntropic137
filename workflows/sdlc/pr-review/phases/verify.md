# Try to falsify the claim

$ARGUMENTS

The previous phase's map is at `artifacts/input/investigate.md`. Read it first.

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
