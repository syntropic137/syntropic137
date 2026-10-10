# README banners

One banner per org repo, in the Design V2 brand: the cube S on the left; on the right a pill (license and a short label), the repo's display name in Orbitron (any `137` in the accent), a tagline in Instrument Sans and the repo's key command in JetBrains Mono. Ground `#0A0C14` with the landing's accent glow wash and 28px dot grid, rounded corners and a hairline edge so the card reads on GitHub's light and dark pages alike.

Generated, don't edit the SVGs by hand. Edit `repos.json`, then from the repo root:

```bash
pnpm --filter @syn137/skyline-core run repo-banner            # all
pnpm --filter @syn137/skyline-core run repo-banner syntropic137-setup   # one
```

Needs `uv` on `PATH` (fontTools runs through `uvx`; nothing is installed).

## Usage

Copy `<repo>.svg` into the target repo (e.g. `assets/banner.svg`) and put it at the top of its README:

```html
<p align="center">
  <img src="assets/banner.svg" alt="Syntropic137 Setup: deploy and run your own Syntropic137 stack" width="100%">
</p>
```

Use `width="100%"` for the main repo, or a fixed width of 760 to 900 elsewhere. The banner has its own dark card, so one file serves both color schemes; no `<picture>` needed.

## Fonts

GitHub serves README SVGs through `<img>`, which loads nothing external. Each banner therefore embeds its fonts as base64 woff2 `@font-face` data: URIs, built by `packages/syn-ui/skyline-core/scripts/fontSubset.ts`:

1. pin each variable font from `apps/syn-landing/public/fonts/` (OFL) to one static weight: `uvx --from fonttools --with brotli fonttools varLib.instancer <font> wght=<w>` (Orbitron 600, Instrument Sans 400, JetBrains Mono 500);
2. subset to exactly the glyphs that banner uses and re-encode: `pyftsubset --text=... --flavor=woff2 --no-hinting`.

The same static instances give the advance widths the layout uses to fit the title and command into the column. Each SVG stays around 13 KB. Font stacks still list fallbacks for renderers that ignore `@font-face` (`rsvg-convert`, some previewers).

## Fields (`repos.json`)

| Field | Required | Shown as |
|---|---|---|
| `name` | yes | Output file name (the repo name) |
| `title` | yes | Big Orbitron line |
| `label` | yes | Pill text (upper-cased) |
| `license` | no | Pill prefix with the scales glyph |
| `tagline` | no | Instrument Sans line |
| `command` | no | Mono line after a `$` |
| `alt` | no | `aria-label` and `<title>` (default: `title: tagline`) |
