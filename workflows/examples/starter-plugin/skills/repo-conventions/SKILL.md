---
name: repo-conventions
description: House conventions for this repository - commit message shape, branch naming, and where documents live. Use when writing a commit, opening a PR, or deciding where a new document belongs.
---

# Repository conventions

This skill is bundled inside the starter plugin. It ships with the plugin, so
it needs no network access and no version pin: `syn workflow install` reads
this directory, hashes the file tree with sha256, and registers the skill under
`version: sha256-<hash>`. Edit any byte here and the next install registers a
new version. Change nothing and the next install uploads nothing.

## Commits

- Conventional commits: `type(scope): summary`.
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`.
- The summary is imperative and lowercase: "add retry to poller", not "Added a retry".
- One logical change per commit.

## Branches

- `feat/<short-slug>` for features, `fix/<short-slug>` for fixes.
- Branch off the default branch. Never commit directly to it.

## Where documents live

- Architecture decisions go in `docs/adrs/` as `ADR-NNN-<slug>.md`.
- Internal guides go in `docs/`.
- Root-level markdown other than `README.md` is scratch and is never committed.

## Reporting

When you finish a task, state plainly what you changed and what you did not
verify. Never claim a check passed unless you ran it.
