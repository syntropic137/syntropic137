# Attack the paths

A different model framed this problem and researched the paths. Your value is
disagreement. You have `artifacts/input/options/options.md`.

> **Where to find that input.** The durable location is the directory
> `artifacts/input/<phase-id>/`, holding whatever the previous phase wrote under
> `artifacts/output/`. A flat `artifacts/input/<phase-id>.md` alias also exists
> today, but `ArtifactCollector` marks it "kept for one release (issue #988)", so
> a prompt that reads only the flat path will silently receive nothing once it
> goes. Look in the directory first and fall back to the flat file. If neither
> exists, stop and say so rather than proceeding on no input.

## The problem as stated

$ARGUMENTS

## Attack the framing first

1. **Is this the right problem?** Is the decision real, or is it already
   settled somewhere in the repository? Check the design docs and ADRs
   yourself. A framing that asks the wrong question poisons every path.
2. **Are the success criteria right?** A criterion no path could fail is not a
   criterion. A missing criterion lets a bad path win.
3. **Are the `file:line` citations real, and do they say what is claimed?**

## Attack each path

For every path:

- **The hidden assumption** most likely to be false. Test it against the code
  where you can.
- **The failure mode the author understated** - cost, complexity, a
  constraint it breaks, something it forecloses.
- **Evidence you can produce**, not argument: read the code, run a command.
- **Is it genuinely different** from another path, or a variant of one?

## What is missing

- **A path nobody listed.** This is often the most valuable finding. If you
  can name a better option, describe it as fully as the others.
- A constraint, consumer or prior decision no path accounts for.

## Write to `artifacts/output/attack.md`

Findings grouped by path, most severe first. Each: the fact, `file:line`, the
evidence you produced, and how it changes the path's standing. End with any new
path you propose.

Do not choose a path. Attack all of them, including the one that looks best,
harder than the rest.

## Citing code

Every `file:line` reference MUST be the path from the repository root, exactly
as `git ls-files` prints it. An abbreviated path is not a smaller citation, it
is an unusable one: a reader cannot follow it and a checker cannot verify it.

## End with exactly this, and nothing after it

Your document is the deliverable; the status block only says whether you
produced it. End your final message with these two lines, verbatim in shape:
`"success"` and `"comments"` are the only keys, the comment is one short
sentence on one line with no double quotes inside it, and `TASK_RESULT_END` is
on its own line. Every detail belongs in the file you wrote, not here. Three
runs of this workflow completed their document and were still failed because
the block carried extra keys, long text or no terminator.

```text
TASK_RESULT: {"success": true, "comments": "Wrote artifacts/output/<file> with <n> sections."}
TASK_RESULT_END
```

If you could not produce the document, use `"success": false` and say why in
the comment.
