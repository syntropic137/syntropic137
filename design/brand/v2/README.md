# Design V2 assets

Folder map for the current style. The guide (rules, voice, "Where does it go?") is [`BRAND.md`](BRAND.md); all styles: [`../README.md`](../README.md).

## By purpose

| Folder | For | Files |
|---|---|---|
| [`logo/`](logo/) | The S mark anywhere vector works | `s-mark.svg` (fixed colours: READMEs, social, anywhere CSS variables don't work; keep its provenance metadata), `s-mark.themable.svg` (reads `--ac`; reference for the `SMark` component, which is built from `skyline-core`'s `sMark()`) |
| [`app-icons/`](app-icons/) | Browser tabs, iOS home screen, PWA | `favicon.svg`, `favicon-32x32.png` (transparent), `app-icon.svg` (mark on `#0A0C14`, source for the rasters), `apple-touch-icon.png` (180), `icon-192.png`, `icon-512.png` |
| [`avatars/`](avatars/) | Profile pictures: GitHub, X, Discord, LinkedIn, YouTube, npm | `avatar-1024.png` (**official social icon**), `avatar-512.png`, `avatar-transparent-1024.png` / `-512.png` (slides, docs, light grounds) |
| [`social/`](social/) | Banners and covers, upload-ready, one folder per platform | see [`social/README.md`](social/README.md) |
| [`link-preview/`](link-preview/) | Link previews for syntropic137.com (Open Graph, X card) | `og-image.png` (1200 x 630, live; copied to `apps/syn-landing/public/`), `og-image-vector.svg` / `.png` (text-free, generated) |
| [`readme-banners/`](readme-banners/) | The banner at the top of each org repo's README | `<repo>.svg` (1200 x 400), `repos.json` (source); see [`readme-banners/README.md`](readme-banners/README.md) |
| [`renders/`](renders/) | Blender stills to compose new art from | `syn137-*.webp`; full-size stills live in the system monorepo `assets/blender-hero/` |
| [`sources/`](sources/) | Templates that render the PNGs | `og.html` (share image + GitHub preview), `x-header.html`, `hero-1920.jpg` (shared backdrop), `render.sh` |

## Regenerate

From the repo root.

```bash
# Share image, GitHub social preview, X header (headless Chrome, real fonts)
design/brand/v2/sources/render.sh

# Text-free vector share image (needs rsvg-convert)
pnpm --filter @syn137/skyline-core run og-image

# README banners (needs uv on PATH)
pnpm --filter @syn137/skyline-core run repo-banner

# App icons
cd design/brand/v2/app-icons
rsvg-convert -w 32 -h 32 favicon.svg -o favicon-32x32.png
rsvg-convert -w 180 -h 180 app-icon.svg -o apple-touch-icon.png
for s in 192 512; do rsvg-convert -w $s -h $s app-icon.svg -o icon-$s.png; done
```

The vector share image comes from `skyline-core`'s `heroCity()` and `sMark()` (`packages/syn-ui/skyline-core/scripts/og-image.ts`), so it uses the page's geometry. It has no text: no wordmark font is reliably available to `rsvg-convert`.

The Discord, LinkedIn and YouTube banners and the YouTube watermark were composed once from the Blender stills (the full dark hero fitted inside each size on its own ground colour, so the S is never cropped). No script; recompose from `renders/` or `assets/blender-hero/stills/`.
