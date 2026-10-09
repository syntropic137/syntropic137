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

- **Wordmark** (TopNav, PhoneTop): the Syntropic137 S mark (`SMark`, drawn from `skyline-core`'s `sMark()`, the same geometry as the landing nav) with Orbitron type replaces the cube drawn on the boards; the S is 21px wide, 44px tall, the most the one-row top bar holds without growing (the landing nav uses 24 to 26px). It replaced the raster S of feedback 1117bb69. Favicons and the web manifest are the S too (`apps/syn-ui/public/`). The desktop app icons (`apps/syn-desktop/scripts/make-icons.py`) are separate placeholder art and do not derive from it. The cube's extrude recipe stays in skyline-core for the charts.
- **Status colours** (Executions, Execution, Sessions, Session, Overview, Workflow runs): each state has its own `--sky-status-*` token, chosen once by `statusSemantics()`. Completed is green with a check (the boards draw it accent blue), failed red with a cross, running accent with a spinning partial ring and a pulsing badge, pending and queued muted with a clock, cancelled grey with a dash, interrupted amber with a pause. Phase segments, the outcome ring and the list split use the same tokens.
- **Skyline** (Main, PhoneOverview): the camera looks down more, `dims.elevation` 68 degrees against the boards' 30 (`SKYLINE_ELEVATION`), and the depth rows sit half as far apart again (`SKYLINE_ROW_SPREAD` 1.5), so a short day behind a tall one keeps a pickable top (feedback 75cf7eb2: at 60 degrees a live day hid completely). The pair is the smallest even step at which every fixtures bar shows at least half its top face and every bar of a pinned live year at least a quarter (`skylineView.test.ts`). Bars are coloured by `skylineTone()`: outcome mix (pass, mixed, fail, none) from the status tokens when a day has outcome counts, otherwise a four-step accent ramp by sessions, with a legend under the chart. The pointer picks bars by their silhouettes, front row first (`pickSkylineBar()`), so a short bar beside a tall one picks itself.
- **Feedback** (every page, dev only): the React widget's floating bubble replaces the boards' top-bar Feedback button, bottom right and above the dock on phones, and the Quick note is one box (owner, Oct 9 2026: "I just want a simple single feedback section and the ticket is opened"): an autofocused "What's on your mind?" textarea sent as typed, compact always-visible type and priority chips under it (default Other / Medium, hotkey letter on hover or focus), then the visible page chip (route and middle-truncated URL), the element pin, Take screenshot / Capture area / Upload image with thumbnails, and a voice-note recorder; only build and viewport sit under a collapsed Details. Cmd/Ctrl+Enter sends, a one-line Sent with the id shows and the dialog closes itself after a second. No board draws it; colours are `--sky-feedback-*` tokens.
- **Top bar** (TopNav): one row from 64rem, never wrapping. The capsule shows icons only (labels kept for screen readers and as tooltips) until 90rem, where the labels fit; at 80rem they are about 90px too wide. A top-bar Feedback button, where one shows, is icon-only on desktop.
- **Command palette** (CompNav "command · ⌘K"): ⌘K / Ctrl+K, the search buttons, the phone More sheet and the desktop shortcut all open one palette: recent executions, sessions and workflows from the cached list reads, Run workflow, Copy page for an agent, Go to (with the keymap's `G` hints) and Help (shortcuts, docs, feature requests, GitHub issues). The group holding the best match comes first. No theme toggle: the app is dark only.
- **Keyboard** (every page, no board): one keymap in skyline-core (`state/keymap.ts`). `g` then `o e s w v a t r` jumps to a section, `j`/`k` or the arrows move the active list row (token focus ring), Enter opens it, Esc or Backspace goes back, `/` focuses the list search, `?` opens the shortcuts overlay, which lists the same keymap. Nothing fires while typing in a field.
- **Run Row phase bar** (Main, Executions, Workflow): phase blocks sit on one grid per list (`runSlots()`: the most phases any row has), so blocks are one size and phase N lines up across rows; duration moved to a 2px rule under the blocks. The boards squeezed equal blocks into a duration-length fill, which turned an 8-phase 1-minute run into slivers (feedback c80ad278).
- **Live commits** (Main): intentionally not shipped. The owner judged the commit feed noise at thousands of commits a day (feedback 627f4206); the panel, its `/events/recent` resource and fixture are gone. Something better (PRs, perhaps) needs a canvas decision first.
- **List defaults** (Executions, Sessions): open on the last 24 hours with 100 rows a page (`MAX_PAGE_SIZE`); All and the other windows stay in the Time window control (`?window=all`). Fixture time windows are measured back from the fixture clock, so the 24h view has today's runs on any day.

## For agents

UI work starts by reading this file, `skyline-spec.md`, the relevant boards and `packages/syn-ui/CONVENTIONS.md`. The `design-handoff` skill (`.claude/skills/design-handoff/SKILL.md`) has the steps.

## Shipped

Boards for these screens are frozen history. Change the code, not the board.

| Screen | Board | Route | PR | Date |
|---|---|---|---|---|
| Overview | `Main.dc.html`, `PhoneOverview.dc.html` | `/` | #1764 | 2026-10-08 |
| Executions | `Executions.dc.html`, `Execution.dc.html`, `PhoneExecutions.dc.html`, `PhoneExecution.dc.html` | `/executions`, `/executions/:executionId` | #1764 | 2026-10-08, eyes-on 2026-10-09 |
| Sessions | `Sessions.dc.html`, `Session.dc.html`, `PhoneSessions.dc.html`, `PhoneSession.dc.html` | `/sessions`, `/sessions/:sessionId` | #1764 | 2026-10-08, eyes-on 2026-10-09 |
| Workflows list | `Workflows.dc.html`, `PhoneWorkflows.dc.html` | `/workflows` | #1764 | 2026-10-08 |
| Evals | `Evals.dc.html`, `Eval.dc.html`, `PhoneEvals.dc.html`, `PhoneEval.dc.html` | `/evals`, `/evals/:evalId` | #1764 | 2026-10-08 |
| Artifacts | `Artifacts.dc.html`, `Artifact.dc.html`, `PhoneArtifacts.dc.html`, `PhoneArtifact.dc.html` | `/artifacts`, `/artifacts/:artifactId` | #1764 | 2026-10-08, eyes-on 2026-10-09 |
| Triggers | `Triggers.dc.html`, `PhoneTriggers.dc.html` | `/triggers` | #1764 | 2026-10-08, eyes-on 2026-10-09 |
| Repos | `Repos.dc.html`, `PhoneRepos.dc.html` | `/repos` | #1764 | 2026-10-08, eyes-on 2026-10-09 |
| Eval Trend panel | `Eval.dc.html`, `PhoneEval.dc.html` (trend section) | `/evals/:evalId` | #1764 | 2026-10-08 |
| Workflows list trend cards | `Workflows.dc.html`, `PhoneWorkflows.dc.html` (duration graph, Faster/Slower/Steady) | `/workflows` | #1764 | 2026-10-08 |
| Workflow detail and runs (with Performance panel) | `Workflow.dc.html`, `PhoneWorkflow.dc.html` | `/workflows/:workflowId`, `/workflows/:workflowId/runs` | #1764 | 2026-10-08 |

Sessions was finished from its board in the 2026-10-09 eyes-on pass; what is left there needs backend fields (agent split, tools count) or a canvas decision. The Workflow detail Performance panel shipped from the canvas export's newer `Workflow.dc.html` and `PhoneWorkflow.dc.html`; the snapshots in `canvas/` predate that panel.
