# Find what changed at the boundary

$ARGUMENTS

Read `artifacts/input/classify.md` first. It names the classes and flags any
that look new.

Your job is to establish, for each candidate regression, **what changed and
when** - or to establish that nothing did and the class is older than it looks.

## The boundary is a time, and you have to find it

A regression has a first occurrence. Find it in the corpus: the earliest
execution carrying that class. Then find what shipped near it.

```sh
git log origin/main --oneline --since="<window start>" --until="<window end>"
git log origin/main --merges --oneline --since="<window start>"
```

If the platform was deployed in the window, the deploy time is the strongest
candidate boundary, and the question becomes: **is the first occurrence after
it?** Note that a deploy time is not a merge time - code merges hours before it
runs anywhere - so compare against when the image started serving, not when the
PR closed.

## Prove it, do not assume it

Two failure modes to avoid, both of which produce confident wrong answers:

- **Post hoc.** A class appearing after a deploy is not caused by it. Look for a
  mechanism: does a merged diff plausibly produce this exact error string? If
  you cannot name the code path, say the link is unproven.
- **Absence of evidence.** A class not appearing before the boundary may mean it
  did not happen, or that the corpus does not reach back far enough, or that it
  happened and was recorded under a different message. Check the window length
  before claiming a class is new.

The strongest evidence is a **mechanism plus a boundary**: this commit changed
this function, that function produces this string, and the first occurrence is
after it shipped. Anything weaker, label as suspected.

## Read the ref, not the working tree

The checkout may sit on a stale branch. Use `git show origin/main:<path>` and
`git grep <pattern> origin/main -- <path>`. A `grep` of the working tree
describes some other moment.

And **the issue number is not the change.** Work merges under different issue
numbers than the one that reported it, so finding no mention of an issue proves
nothing. Search for the change: `git log origin/main --oneline -20 -- <path>`.

## Say what the change was FOR

This is the part that keeps a retrospective honest. A regression usually arrives
inside a fix, and the fix was usually right. Record what the change was trying
to achieve and whether it achieved it, alongside what it broke.

A deploy that removes one failure class and creates another is a **trade**, and
a retrospective that reports only the cost is as misleading as one that reports
only the benefit. If a class disappeared in the same window, say so with the
same rigour you applied to the one that appeared.

## Write to `artifacts/output/bisect.md`

**This phase declares a markdown output artifact, so a run that writes nothing
under `artifacts/output/` FAILS.** Write the file before you finish.

For each candidate regression:

1. **First occurrence** - execution id and timestamp.
2. **The boundary** - what shipped, when, and how you established the time.
3. **The mechanism** - the specific code path that produces the observed string,
   cited as `file:line` against `origin/main`. Or: "no mechanism found", which
   is a legitimate and useful answer.
4. **Confidence** - proven, suspected, or unproven, in those words.
5. **The trade** - what the change fixed, measured the same way.

If nothing regressed, say so. "The failure classes in this window are all
pre-existing" is a valuable finding and the next phase still has work: gates
that never caught a long-standing class are as interesting as gates that missed
a new one.
