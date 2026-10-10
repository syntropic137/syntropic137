# README banners

One banner per org repo, in the Design V2 brand: the cube S on the left; on the right a pill (license and a short label), the repo's display name in Orbitron (any `137` in the accent) and the repo's key command in JetBrains Mono. A train of the repo's key phrases, in small mono caps, runs slowly counterclockwise round the inside of the card (one repeat per 60s, faded at the corners and side joins). Ground `#0A0C14` with the landing's accent glow wash and 28px dot grid, rounded corners and a hairline edge so the card reads on GitHub's light and dark pages alike.

The train is SMIL (`<animate>` on a `textPath`'s `startOffset`), which browsers run in an SVG shown through `<img>`; no script. The top edge and the bottom edge are separate halves so both read upright; they meet, faded, at the middle of each side.

Generated, don't edit the SVGs by hand. Edit `repos.json`, then from the repo root:

```bash
pnpm --filter @syn137/skyline-core run repo-banner            # all
pnpm --filter @syn137/skyline-core run repo-banner syntropic137-setup   # one
```

Needs `uv` on `PATH` (fontTools runs through `uvx`; nothing is installed).

## Usage

Copy `<repo>.svg` into the target repo (e.g. `assets/banner.svg`) and put it at the top of its README, followed straight away by the repo's command in a fenced block:

````markdown
<p align="center">
  <img src="assets/banner.svg" alt="Syntropic137 Setup: deploy and run your own Syntropic137 stack" width="100%">
</p>

```bash
npx @syntropic137/setup init
```
````

An SVG shown as an image can't be interactive, so the command drawn in the banner can't be selected or copied. The fenced block under it gets GitHub's native copy button. Repos without a `command` (event-sourcing-platform, software-leverage-points, syntropic137-system-monorepo) skip the block.

Optionally, wrap the image in a link to the repo's docs or install page, so a click on the banner goes somewhere useful. Keep the fenced block under it either way: the link makes the whole image clickable, but the command inside it still can't be copied.

````markdown
<p align="center">
  <a href="https://syntropic137.com">
    <img src="assets/banner.svg" alt="Syntropic137 Setup: deploy and run your own Syntropic137 stack" width="100%">
  </a>
</p>

```bash
npx @syntropic137/setup init
```
````

Use `width="100%"` for the main repo, or a fixed width of 760 to 900 elsewhere. The banner has its own dark card, so one file serves both color schemes; no `<picture>` needed.

## Fonts

GitHub serves README SVGs through `<img>`, which loads nothing external. Each banner therefore embeds its fonts as base64 woff2 `@font-face` data: URIs, built by `packages/syn-ui/skyline-core/scripts/fontSubset.ts`:

1. pin each variable font from `apps/syn-landing/public/fonts/` (OFL) to one static weight: `uvx --from fonttools --with brotli fonttools varLib.instancer <font> wght=<w>` (Orbitron 600, Instrument Sans 400, JetBrains Mono 500);
2. subset to exactly the glyphs that banner uses and re-encode: `pyftsubset --text=... --flavor=woff2 --no-hinting`.

The same static instances give the advance widths the layout uses to fit the title and command into the column. Each SVG stays around 12 to 14 KB. `SOURCE_DATE_EPOCH=0` pins the font timestamps, so regenerating unchanged input gives byte-identical files. Font stacks still list fallbacks for renderers that ignore `@font-face` (`rsvg-convert`, some previewers).

## Fields (`repos.json`)

| Field | Required | Shown as |
|---|---|---|
| `name` | yes | Output file name (the repo name) |
| `title` | yes | Big Orbitron line |
| `label` | yes | Pill text (upper-cased) |
| `license` | no | Pill prefix with the scales glyph |
| `command` | no | Mono line after a `$`; also the README code block |
| `edge` | no | `{ "text": "A · B · C", "seconds": 60 }`: the edge train, 3 to 5 short phrases; `seconds` 0 or absent keeps it still |
| `tagline` | no | Names the image (`aria-label`, `<title>`); drawn only with `taglineAt` |
| `taglineAt` | no | `none` (default), `below` (own line under the title) or `side` (beside the title on its baseline) |
| `gaps` | no | Override vertical gaps in px: `pillTitle`, `titleCommand` (default 48 each), `titleTagline`, `taglineCommand` |
| `alt` | no | `aria-label` and `<title>` (default: `title: tagline`) |

Preview a variant without touching these files: `pnpm --filter @syn137/skyline-core run repo-banner --config /path/variants.json --out /tmp/banners`.
