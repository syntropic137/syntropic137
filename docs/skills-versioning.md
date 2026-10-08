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

1. **A release is an immutable git tag `vX.Y.Z`.** Tags are never moved.
   Per-skill tags like `<skill>@1.2.0` are not created: `skill-ref.ts` rejects a
   ref containing `@`, and the `skills` CLI pins one ref per repository
   (`owner/repo#ref`).
2. **Each skill states its own semver** as a quoted string in its frontmatter,
   `metadata.version` (the Agent Skills spec has no top-level `version`, and
   `metadata` values are strings). It is part of the skill tree, so it is
   covered by `resolved_sha`.
3. **`CHANGELOG.md`** (Keep a Changelog) has one line per skill per version,
   so the upgrade from one tag to another can be read before it is made.

What Syntropic137 relies on is only (1): the ref. Neither the `skills` CLI nor
Syntropic137 reads `metadata.version` to decide anything. The CLI's lock file
records the `ref` and a content hash, `skills update` reinstalls when the
content at the same ref changes, and nothing compares semver. A workflow that
pins `@main` therefore gets whatever `main` is when it is registered, and the
version field does not protect it.

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
`(source_url, version, skill_name)`, so `@v1.1.0` registers once and is reused.

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
