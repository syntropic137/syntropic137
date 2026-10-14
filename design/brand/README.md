# Brand

Every Syntropic137 brand asset, grouped by **style** (one folder per visual identity) and, inside a style, by **what the file is for**.

## Start here

| I want to... | Go to |
|---|---|
| Upload a profile picture, banner or cover somewhere | [`v2/BRAND.md`](v2/BRAND.md#where-does-it-go-upload-ready-files), "Where does it go?" |
| Understand the brand (logo, colour, type, voice) | [`v2/BRAND.md`](v2/BRAND.md) |
| Find a file by purpose, or regenerate one | [`v2/README.md`](v2/README.md) |
| See what changed and when | [`CHANGELOG.md`](CHANGELOG.md) |

## Styles

| Folder | Style | Status |
|---|---|---|
| [`v2/`](v2/) | Design V2, October 2026: the cube S, the run city, Skyline tokens | **Current.** Use this. |
| (none) | V1: the raster cube logo, Inter, the old landing tokens | Retired. Never stored here; listed in [`CHANGELOG.md`](CHANGELOG.md#1x-retired). |

A new identity gets a new folder (`v3/`) next to `v2/`. The old folder stays untouched, so links into it keep working.

## Layout

```text
design/brand/
├── README.md          this file: styles and breadcrumbs
├── VERSION            kit version (semver), currently 2.x = the v2 style
├── CHANGELOG.md       kit history across every style
└── v2/                Design V2 (current)
    ├── BRAND.md       the guide: what the brand is, rules, where every file goes
    ├── README.md      folder map and regenerate commands
    ├── logo/          the S mark, vector
    ├── app-icons/     favicons, PWA and home-screen icons
    ├── avatars/       profile pictures (the official social icon)
    ├── social/        upload-ready banners and covers, one folder per platform
    │   ├── x/  youtube/  discord/  linkedin/  github/
    ├── link-preview/  Open Graph / X card image for the website
    ├── readme-banners/ one SVG banner per org repo, plus repos.json
    ├── renders/       Blender stills (webp) to compose new art from
    └── sources/       HTML templates and scripts that render the PNGs
```

## Rules

- Files are named for their size or variant; the folder says what they are for. `social/x/header-1500x500.png` is the X header.
- Edit sources, never outputs. Generated files say so in [`v2/README.md`](v2/README.md).
- Any change: bump [`VERSION`](VERSION) and add a [`CHANGELOG.md`](CHANGELOG.md) entry.
