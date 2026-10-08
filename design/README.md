# Design

How a design on the canvas becomes code in Skyline (`apps/syn-ui` and `packages/syn-ui/*`).

- `canvas/*.dc.html`: one board per screen, desktop and phone (`Phone*.dc.html`), plus component and foundation boards
- `canvas/canvas.json`: the canvas layout (board positions, pages, titles)
- `skyline-spec.md`: architecture, tokens, components, patterns, responsive rules, screen map, build order
- Live canvas, for viewing and comments only: https://claude.ai/artifact/M1bgLdL1fgrkwnPQZj32H9

## What the boards are

Each `*.dc.html` file is one interactive board:

- HTML and CSS with `{{placeholders}}`;
- `<sc-for>` and `<sc-if>` for repeats and conditions;
- `<dc-import>` for shared pieces such as TopNav;
- a small JS class at the bottom whose `renderVals()` computes the data and whose `setState()` handles interaction.

The boards run only inside the Claude Design canvas. Treat them as an interactive spec: read them for layout, copy, tokens, sample data and behaviour, never as code to ship.

## The loop

1. New screens and big changes are designed on the canvas first. That is the place to explore and comment.
2. Snapshot the changed boards into `design/canvas/` in a small `design:` PR.
3. An agent builds the change in `apps/syn-ui` and the `packages/syn-ui/*` packages from the board and the spec. Before opening the PR it screenshots its result at 1440px and 390px wide in fixtures mode and compares it with the board.
4. Once a screen ships, the code is the source of truth. Small tweaks go straight to code, reviewed in `/dev/components`, `/dev/patterns` and the screenshot tests. Don't redraw small changes on the canvas.

## Keeping boards honest

When a screen ships:

- add it to the Shipped table below (board, route, PR, date);
- treat that board as frozen history; don't build from it again;
- start a redesign by screenshotting the live app as the "before", never by editing an old board.

## Never sync screens back from code to the canvas

Sync components instead. Once Skyline settles, sync it into a claude.ai design-system project with `/design-sync`, so new designs use the real components and tokens.

## Component library: no Storybook

- The reference is `/dev/components` and `/dev/patterns` in apps/syn-ui, plus Playwright screenshot tests of those pages at both widths on every PR.
- Keep each component's example states in a data file next to the component, so Storybook could be adopted later if collaborators join or Skyline is published.

### Screenshot tests

`apps/syn-ui/e2e/screenshots.spec.ts` captures both pages at 1440px and 390px in fixtures mode and compares them with `apps/syn-ui/e2e/baselines/*-linux.png`. It runs only when `SYN_UI_SCREENSHOTS=1`, which only the `screenshots` job in `.github/workflows/syn-ui.yml` sets. The default e2e suite does not include it.

Baselines are Linux Chromium only, because fonts and rasterising differ on macOS. Never commit a baseline made on a Mac; local runs write `*-darwin.png`, which git ignores.

To refresh the baselines after an intended visual change:

1. Run the Skyline UI workflow by hand (Actions, "Skyline UI", Run workflow) on your branch with `update_screenshots` ticked. With no baselines committed, any run writes them.
2. Download the `skyline-screenshot-baselines` artifact, look at every image, and commit them to `apps/syn-ui/e2e/baselines/`.

Locally, `just skyline-screenshots` runs the same spec against your own OS (add `--update-snapshots=all` to write local baselines). It is useful for checking a change by eye, not for the CI comparison.

## Owner tweaks after demo

Small changes made in code after the owner reviewed the demo. Where a board disagrees, the code wins.

- **Wordmark** (TopNav, PhoneTop): the original Syntropic137 "S" mark (`apps/syn-ui/public/logo_syntropic137.png`) with Orbitron type replaces the cube drawn on the boards. The cube's extrude recipe stays in skyline-core for the charts.
- **Status colours** (Executions, Execution, Sessions, Session, Overview, Workflow runs): each state has its own `--sky-status-*` token, chosen once by `statusSemantics()`. Completed is green with a check (the boards draw it accent blue), failed red with a cross, running accent with a spinning partial ring and a pulsing badge, pending and queued muted with a clock, cancelled grey with a dash, interrupted amber with a pause. Phase segments, the outcome ring and the list split use the same tokens.

## For agents

UI work starts by reading this file, `skyline-spec.md`, the relevant boards and `packages/syn-ui/CONVENTIONS.md`. The `design-handoff` skill (`.claude/skills/design-handoff/SKILL.md`) has the steps.

## Shipped

Boards for these screens are frozen history. Change the code, not the board.

| Screen | Board | Route | PR | Date |
|---|---|---|---|---|
| Overview | `Main.dc.html`, `PhoneOverview.dc.html` | `/` | #1764 | 2026-10-08 |
| Executions | `Executions.dc.html`, `Execution.dc.html`, `PhoneExecutions.dc.html`, `PhoneExecution.dc.html` | `/executions`, `/executions/:executionId` | #1764 | 2026-10-08 |
| Sessions (partial) | `Sessions.dc.html`, `Session.dc.html`, `PhoneSessions.dc.html`, `PhoneSession.dc.html` | `/sessions`, `/sessions/:sessionId` | #1764 | 2026-10-08 |
| Workflows list | `Workflows.dc.html`, `PhoneWorkflows.dc.html` | `/workflows` | #1764 | 2026-10-08 |
| Evals | `Evals.dc.html`, `Eval.dc.html`, `PhoneEvals.dc.html`, `PhoneEval.dc.html` | `/evals`, `/evals/:evalId` | #1764 | 2026-10-08 |
| Artifacts | `Artifacts.dc.html`, `Artifact.dc.html`, `PhoneArtifacts.dc.html`, `PhoneArtifact.dc.html` | `/artifacts`, `/artifacts/:artifactId` | #1764 | 2026-10-08 |
| Triggers | `Triggers.dc.html`, `PhoneTriggers.dc.html` | `/triggers` | #1764 | 2026-10-08 |
| Repos | `Repos.dc.html`, `PhoneRepos.dc.html` | `/repos` | #1764 | 2026-10-08 |

Sessions is partial: finish it from its board. The new trend charts on `Eval.dc.html`, `PhoneEval.dc.html`, `Workflow.dc.html`, `PhoneWorkflow.dc.html` and the Workflows list cards are not shipped yet, so those parts of the boards are still live specs.
