# Skills versioning: pin, record, upgrade

How a workflow gets a skill at a known version, how a run records which version
it used, and how to move to a newer one on purpose. Written 2026-10-08, when
`syntropic137/syntropic137-skills` started versioning.

## What exists already, and what does not

**There is no "skills source" setting to pin, and none is needed.** No
workspace runs `npx skills add <owner/repo>`. A skill reaches a workspace one of
two ways:

| Layer | How | Pinned by |
|---|---|---|
| 1. Platform | Baked into the agentic-workspace image (for example the delegation skills under `/opt/agentic/plugins/delegation/skills`) | The image digest in `PINNED_DIGESTS` |
| 2. Workflow | Declared in a workflow's `skills:` as `<org>/<repo>/<skill>@<ref>` or `<url>@<ref>`, registered into the content-addressed skill store, materialised to `/workspace/.syn-skills/<name>/`, then installed with `skills add <local path> --agent <key> -y` | The `@<ref>` in the workflow YAML; `@latest` is rejected |

Design: [skills distribution](superpowers/specs/2026-08-17-skills-distribution-design.md),
YAML reference: [workflow packages](workflow-packages.md#skills-skills).

**Each run already records which skill version it used.** At start, every
phase's skills are frozen into `WorkflowExecutionStartedEvent.pinned_phases`
and served by `GET /executions/{id}` as
`phases[].pinned_at_start.skills[]` (`PinnedSkillInfo`):

| Field | Meaning |
|---|---|
| `name` | The skill name |
| `version` | The ref as declared: a tag, branch or sha |
| `resolved_sha` | sha256 of the skill tree the workspace was actually given |
| `source_url` | Where it came from |

`resolved_sha` is the ground truth: two runs with the same value had
byte-identical skills, whatever their declared refs say. So "record installed
skill versions per phase" was not added again here: it would be a second,
parallel record of the same fact.

## The contract with a skills repository

`syntropic137/syntropic137-skills` (and any skills repo that wants the same
upgrade discipline) promises:

1. **A release is an immutable, repository-wide git tag `vX.Y.Z`.** Tags are
   never moved. Per-skill tags like `<skill>@1.2.0` are not created, by
   convention rather than because anything forbids them: each skill entry
   carries its own ref, so skills from one repository can be pinned to
   different refs, and the verbose mapping form (separate `source` and
   `version` keys, `parseVerbose` in `skill-ref.ts`) accepts a version
   containing `@`. What does not work is such a ref in the compact string
   forms: `skill-ref.ts` refuses an ambiguous `@` in `<url>@<version>`, and the
   `skills` CLI reads `owner/repo#name@1.2.0` as ref `name` with skill filter
   `1.2.0`. One tag per release keeps every pin a short string.
2. **Each skill states its own semver** as a quoted string in its frontmatter,
   `metadata.version` (the Agent Skills spec has no top-level `version`, and
   `metadata` values are strings). It is part of the skill tree, so it is
   covered by `resolved_sha`.
3. **`CHANGELOG.md`** (Keep a Changelog) has one line per skill per version,
   so the upgrade from one tag to another can be read before it is made.

What Syntropic137 relies on is only (1): the ref. Neither the `skills` CLI nor
Syntropic137 reads `metadata.version` to decide anything. Checked against
`skills` CLI 1.7.0, the version the agentic-workspace images install
(`SKILLS_CLI_VERSION`), on 2026-10-08:

- The CLI's `skills-lock.json` records the source, the `ref` as given (branch,
  tag or sha; it does not resolve it to a commit) and a content hash of the
  skill folder
  ([src/local-lock.ts](https://github.com/vercel-labs/skills/blob/v1.7.0/src/local-lock.ts)).
  Of `metadata` it reads only `metadata.internal`
  ([src/skills.ts](https://github.com/vercel-labs/skills/blob/v1.7.0/src/skills.ts)).
- `skills update` depends on scope
  ([src/update.ts](https://github.com/vercel-labs/skills/blob/v1.7.0/src/update.ts)):
  for global skills it reinstalls when the folder hash at the recorded ref
  differs; for project skills it re-fetches every updatable skill at its
  recorded ref without comparing hashes. Neither compares semver.
- `experimental_install` reinstalls from `source#ref` and does not check the
  result against the recorded hash
  ([src/install.ts](https://github.com/vercel-labs/skills/blob/v1.7.0/src/install.ts)).
- A full 40-character commit sha works as a ref in 1.7.0; 1.5.14 cloned with
  `--branch` and could not use one
  ([1.7.0 src/git.ts](https://github.com/vercel-labs/skills/blob/v1.7.0/src/git.ts)).
  Workspaces do not depend on this: layer 2 installs from a local path.

On the Syntropic137 side, registration is idempotent on
`(source_url, version, skill_name)`: `RegisterSkillHandler` returns the
existing registration for that triple without fetching again. So a workflow
that pins `@main` gets whatever `main` was at the **first** successful
registration of that triple, and keeps getting those bytes on every later
registration, however far `main` has moved. The version field does not protect
it either way. Only a new ref (a new tag) brings new content.

## Using a skill from syntropic137-skills

Pin a release tag, never a branch:

```yaml
phases:
  - id: implement
    skills:
      - syntropic137/syntropic137-skills/execution-control@v1.1.0
```

The three-segment form resolves the skill to `skills/<skill>/` inside the
clone (`skillDirInClone` in `skill-tree.ts`). Registration identity is
`(source_url, version, skill_name)`, so `@v1.1.0` registers once and is reused,
which is correct for a tag that never moves.

## Upgrade path: bump pin -> eval -> deploy

A skill is an eval variant like a prompt or a model, so it is upgraded the same
way:

1. **Release.** In the skills repo, merge the change (the version check makes
   it bump the skill and add its changelog line), then tag `vX.Y.Z`.
2. **Bump the pin in a variant, not in place.** Copy the workflow to a variant
   whose only difference is `@vOLD` -> `@vNEW` for the skills that changed
   (read `CHANGELOG.md` between the two tags to see which did). Keeping the
   rest byte-identical means a score difference is the skill.
3. **Eval.** Run the eval suite under both workflows and compare the score
   tables (see [evals and execution tags](plans/20260929_evals-and-execution-tags.md)).
   Confirm from `phases[].pinned_at_start.skills[]` that each run got the
   `version` and a `resolved_sha` you expected.
4. **Deploy.** Change the production workflow's pin to `@vNEW` and
   re-register it (`syn workflow update`, or `syn workflow install` for a package). Executions started
   afterwards record the new ref. Executions already running keep the skills
   they were pinned to at start.

Rollback is the same step with the old tag.

## Deliberately not done (2026-10-08)

- **No image or agentic-workspace change.** Layer 2 needs none. Layer 1 skills
  are versioned by the image digest, and upgrading them already follows the
  `PINNED_DIGESTS` bump.
- **`metadata.version` is not surfaced as its own field.** `version` (the
  declared ref) plus `resolved_sha` identify the skill exactly. Once refs are
  release tags, the skill's own semver can be looked up in the tagged
  `CHANGELOG.md`. If a run view should show it directly, the place to add it is
  registration: read it from the SKILL.md frontmatter that registration already
  treats as the manifest, store it on the registration, and add an optional
  `skill_version` to `PinnedSkillInfo`. That needs a domain event field, so it
  needs an issue first.
- **The `lib/syntropic137-skills` submodule** is not used by any runtime path.
  Its pin (`c173610`) is the content the skills repo's `v1.0.0` tag describes.
  Move it to a release tag when it is next needed, rather than tracking `main`.
