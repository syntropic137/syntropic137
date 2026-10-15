# Brand kit changelog

Versions follow semver: major for a new identity, minor for a new asset or surface, patch for a fix. The current kit is described in [v2/BRAND.md](v2/BRAND.md); styles and layout in [README.md](README.md). Paths in entries before 2.4.0 are relative to the old flat layout.

## 2.4.0 (2026-10-13)

- **Organised by style and purpose.** Everything for the current style moves into `v2/`, grouped by what it is for: `logo/`, `app-icons/`, `avatars/`, `social/<platform>/`, `link-preview/`, `readme-banners/` (was `banners/`), `renders/`, `sources/` (was `og/`). `BRAND.md` moves to `v2/BRAND.md`; the top-level [`README.md`](README.md) is the index of styles with breadcrumbs. Social files drop the platform prefix now that the folder names it (`social/x-header-1500x500.png` is `v2/social/x/header-1500x500.png`). The duplicate avatars in `social/` are gone: profile pictures live only in `v2/avatars/`.
- **YouTube watermark.** `v2/social/youtube/watermark-600.png`: the avatar cut to a circle with transparent corners, so the dark lower cubes read on any footage.

## 2.3.0 (2026-10-13)

- **Share image.** `og-image.png` is now the Blender render of the S in the run city with the wordmark, tagline and install command (`og/og.html`, rendered by `og/render.sh` with the real fonts). Same layout at 1280 x 640 for the GitHub social preview. The text-free vector version moves to `og-image-vector.*`.
- **X header.** `social/x-header-1500x500.png` from `og/x-header.html`: the same render, with the wordmark, tagline and install command in the upper left, clear of the avatar X places over the lower-left corner.

## 2.2.0 (2026-10-10)

- **Banners: one centre line.** The S and the title's cap box share the card's vertical centre; the S plus the text column is centred horizontally.
- **Banners: symmetric spacing.** Pill and command each 48px from the title's cap box.
- **S uplight locked.** In banners and on dark grounds the S is uplit: a soft accent glow centred under it, offset below by 12% of its height (`S_UPLIGHT_OFFSET` in the banner generator). Identical on every banner.

## 2.1.0 (2026-10-10)

- **Avatar.** `avatar-1024.png` and `avatar-512.png`: the Blender close-up of the S on navy with a blue glow, for the GitHub org, X, Discord and npm profile pictures. The official social icon; replaces `icon-512.png` as the recommended avatar. Transparent cuts `avatar-transparent-1024.png` / `-512.png`.
- **Upload-ready social files** in `social/`, one per place: official avatar, X header, Discord banner, LinkedIn cover, YouTube banner, GitHub social preview, transparent avatar. Composed from the full Blender hero so the S is never cropped. "Where does it go?" table at the top of BRAND.md.

## 2.0.0 (2026-10-09)

"Design V2, October 2026". A new identity across the landing page, docs and dashboard.

- **S mark, vector.** Eleven isometric cubes, grid `BBG / B.. / DDD / ..D / DDD`, drawn by skyline-core's `sMark()`; `s-mark.svg` and `s-mark.themable.svg`. Replaces the raster cube logo.
- **Tokens.** One palette, type scale and motion set in `packages/syn-ui/themes/src/` (`syn137.css`, `tokens.css`, `motion.css`), shared by every app.
- **Blender hero.** The run city and the S, rendered in Blender (`design/reference/blender/build_hero.py`); alpha clip and 4K stills on the landing page; web cuts in `renders/`.
- **README banners.** One per org repo, generated from `banners/repos.json`, with the animated edge train.
- **Social image.** `og-image.png`: the S over the run city, generated from `heroCity()` and `sMark()`.
- **Favicons and app icons** from the S: `favicon.svg`, `favicon-32x32.png`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`.
- **Self-hosted fonts.** Instrument Sans, JetBrains Mono and Orbitron as woff2 in `apps/syn-landing/public/fonts/`.
- **Adoption.** The landing page (`apps/syn-landing`), the docs (`apps/syn-docs`) and the dashboard (`apps/syn-ui`) use the S mark, the tokens and the fonts.

## 1.x (retired)

Retired. Not current; don't use these in new work.

- The raster cube logo `logo_syntropic137.png` (still in the frozen `apps/syn-dashboard-ui`).
- `public/assets/syn137-banner.png`, the old README banner.
- `twitter-banner_syntropic137.png`, the old X header.
- Inter as the UI font.
- The old landing tokens (`--color-*`, `--glass-*`, `--grid-*`).
