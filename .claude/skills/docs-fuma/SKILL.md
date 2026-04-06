# Skill: Fumadocs Site — Syntropic137 Documentation

Build, extend, and maintain the Fumadocs documentation site at `apps/syn-docs/`.

## Quick Start

```bash
# Dev server (port 3001)
cd apps/syn-docs && pnpm run dev

# Build
cd apps/syn-docs && pnpm run build

# Regenerate API docs from OpenAPI spec
cd apps/syn-docs && pnpm run generate:openapi
```

## Stack

| Layer | Tech | Version |
|-------|------|---------|
| Framework | Next.js | ^16.1.6 |
| Docs engine | fumadocs-core / fumadocs-ui / fumadocs-mdx | ^16.6.2 / ^16.6.2 / ^14.2.7 |
| API docs | fumadocs-openapi | ^10.3.5 |
| Styling | Tailwind CSS 4 + fumadocs preset | |
| 3D hero | @react-three/fiber + drei | ^9.5.0 / ^10.7.7 |
| Icons | lucide-react | ^0.468.0 |
| Search | Orama (built-in via fumadocs) | |

## Project Structure

```
apps/syn-docs/
├── app/
│   ├── (home)/page.tsx              # Landing page with hero + features
│   ├── docs/
│   │   ├── layout.tsx               # DocsLayout with sidebar
│   │   └── [[...slug]]/page.tsx     # Docs page renderer + LLM buttons
│   ├── llms/page.tsx                # LLM docs landing (system prompt, endpoints)
│   ├── llms.txt/route.ts            # Structured page index (dynamic, absolute URLs)
│   ├── llms-full.txt/route.ts       # All docs concatenated as plain text
│   ├── api/
│   │   ├── search/route.ts          # Orama search API
│   │   └── docs-txt/[...slug]/route.ts  # Per-page plain text endpoint
│   ├── layout.tsx                   # Root layout (metadata, RootProvider)
│   └── global.css                   # SR-71 theme variables
├── components/
│   ├── diagrams/                    # Architecture diagram system (see below)
│   ├── HeroScene.tsx                # Three.js 3D visualization
│   ├── LLMCopyButton.tsx            # Per-page "Copy for LLM" + "View as TXT" + "Edit on GitHub"
│   ├── Badge.tsx                    # MDX badge component
│   ├── FeatureCard.tsx              # MDX feature card + grid
│   └── GradientButton.tsx           # MDX gradient button + button group
├── content/docs/                    # MDX content (22 pages)
│   ├── index.mdx                    # Root overview
│   ├── meta.json                    # Root nav: ["index", "guide", "api", "cli"]
│   ├── guide/                       # 4 pages (getting-started, architecture, configuration, self-hosting)
│   ├── api/                         # 14 pages (auto-generated from OpenAPI + index)
│   └── cli/                         # 1 page (index.mdx)
├── lib/
│   ├── source.ts                    # fumadocs loader, openapi, APIPage
│   ├── layout.shared.tsx            # Shared nav config (logo, links, github)
│   └── cn.ts                        # clsx utility
├── scripts/generate-api-docs.mjs    # OpenAPI JSON → MDX generator
├── mdx-components.tsx               # All custom MDX component registrations
├── source.config.ts                 # fumadocs source config
├── next.config.mjs                  # MDX plugin + .txt rewrites
├── openapi.json                     # Committed OpenAPI spec (~45 endpoints)
└── package.json
```

## Theme: SR-71 Precision

Cold instrument blues and titanium grays. No purple, no red, no warm colors.

**CSS Variables** (`app/global.css`):

| Variable | Dark | Light |
|----------|------|-------|
| `--fd-primary` | sky-400 `56 189 248` | sky-400 `56 189 248` |
| `--fd-accent` | sky-500 `14 165 233` | sky-500 `14 165 233` |
| `--fd-background` | zinc-950 `9 9 11` | `250 250 250` |
| `--fd-muted` | zinc-900 `24 24 27` | `244 244 245` |
| `--fd-muted-foreground` | zinc-400 `161 161 170` | zinc-500 `113 113 122` |

**Design rules:**
- Primary accent: `sky-400` / `sky-500`
- Backgrounds: `zinc-950` dark, near-white light
- Subtle card hovers with `sky-500` glow at 0.08-0.1 opacity
- Code borders: `sky-500/12` → `sky-500/15`
- No bouncy transforms. Thin scrollbars. Sharp precision.

## Content Authoring

### Adding a new docs page

1. Create `content/docs/<section>/<slug>.mdx` with frontmatter:
   ```yaml
   ---
   title: Page Title
   description: One-line description
   ---
   ```
2. Add `<slug>` to the parent `meta.json` `pages` array
3. Use separators in meta.json for grouping: `"---Group Name---"`

### Sidebar structure

- `meta.json` controls page order and grouping
- `"root": true` in a section's meta.json makes it a top-level tab
- Single-page sections should be flat `.mdx` files, NOT `folder/index.mdx` (avoids unnecessary dropdown)

### MDX components available

All registered in `mdx-components.tsx`. Use directly in MDX without imports:

```mdx
<Badge variant="cyan" icon="zap">Event-Sourced</Badge>

<FeatureGrid>
  <FeatureCard icon="workflow" title="Workflows" description="..." gradient="cyan" />
  <FeatureCard icon="eye" title="Observability" description="..." gradient="green" />
</FeatureGrid>

<GradientButton href="/docs/guide/getting-started" variant="primary" icon="rocket">
  Get Started
</GradientButton>

<SystemArchitectureDiagram />
<EventSourcingFlowDiagram />
```

---

## Architecture Diagram System

Location: `apps/syn-docs/components/diagrams/`

This is a composable, MDX-native diagram system built with React + Tailwind. No external diagram tools needed.

### Primitives

All exported from `components/diagrams/index.ts` and registered as MDX components.

#### `<Diagram>`
Top-level container. Adds border, padding, overflow-x-auto.

```mdx
<Diagram>
  {/* diagram content */}
</Diagram>
```

#### `<DiagramNode icon="server" label="API Server" sublabel="Port 8000" color="indigo" size="md" />`

A single box with icon + label. The core building block.

**Props:**
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `icon` | string | required | Icon name from icon map (see below) |
| `label` | string | required | Primary label |
| `sublabel` | string | — | Secondary text below label |
| `color` | ColorVariant | `'indigo'` | Color scheme |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | Node size |

#### `<DiagramGroup title="Infrastructure" color="slate" columns={3}>`

Titled container that arranges children in a CSS grid.

**Props:**
| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `title` | string | required | Group header text |
| `color` | ColorVariant | `'indigo'` | Header accent color |
| `columns` | `1 \| 2 \| 3 \| 4` | — | Grid columns |

#### `<DiagramGrid columns={3}>`

Pure CSS grid layout without title/border. For arranging nodes evenly.

#### `<DiagramArrow direction="down" label="events" />`

Directional arrow. `direction`: `'down'` (default) or `'right'`.

#### `<DiagramRow>` / `<DiagramColumn>`

Flex containers. Row = horizontal, Column = vertical.

#### `<DiagramFlow label="Event Pipeline">`

Horizontal flow with auto-inserted arrows between children.

#### `<DiagramSeparator label="Isolation Boundary" />`

Gradient horizontal line with optional centered label.

### Color Variants (7)

| Variant | Border/BG | Icon/Text | Mnemonic |
|---------|-----------|-----------|----------|
| `indigo` | sky-500 | sky-400 | Primary services |
| `purple` | blue-500 | blue-400 | Secondary services |
| `pink` | rose-500 | rose-400 | External/alerts |
| `cyan` | cyan-500 | cyan-400 | Data/streaming |
| `slate` | zinc-500 | zinc-400 | Infrastructure |
| `emerald` | teal-500 | teal-400 | Success/health |
| `amber` | amber-500 | amber-400 | Warnings/config |

### Icon Map (24 icons)

```
terminal, layout, github, server, database, drive, workflow, eye, activity,
shield, zap, git, plug, box, layers, radio, send, lock, unlock, play, pause,
stop, check, x, globe, container, cpu, monitor
```

### Pre-built Diagrams

Use these directly in MDX — no props needed:

| Component | Description | Source |
|-----------|-------------|--------|
| `<SystemArchitectureDiagram />` | 5-layer system: Users → Platform → Infra → Isolation → Agents | `SystemArchitectureDiagram.tsx` |
| `<EventSourcingFlowDiagram />` | Pipeline: Command → Aggregate → Event → Store → Projections | `EventSourcingDiagram.tsx` |
| `<TwoEventTypesDiagram />` | Domain Events vs Observability Events comparison | `EventSourcingDiagram.tsx` |
| `<CQRSDiagram />` | Write side (commands/aggregates) vs Read side (projections/cache) | `EventSourcingDiagram.tsx` |
| `<DomainModelDiagram />` | 4 bounded contexts + event flow | `EventSourcingDiagram.tsx` |
| `<StateMachineDiagram />` | Execution lifecycle with terminal states | `EventSourcingDiagram.tsx` |
| `<DeploymentArchitectureDiagram />` | 5-layer deployment: External → Frontend → Backend → Data | `DeploymentDiagram.tsx` |
| `<WorkspaceIsolationDiagram />` | Container lifecycle: Create → Setup → Agent → Cleanup | `DeploymentDiagram.tsx` |
| `<ScalingDiagram />` | Load balancer → servers → shared data stores | `DeploymentDiagram.tsx` |

### Building a New Diagram

1. Create `components/diagrams/MyDiagram.tsx`
2. Import primitives from `./DiagramPrimitives`
3. Compose using `Diagram` > `DiagramGroup` > `DiagramNode` pattern
4. Export from `components/diagrams/index.ts`
5. Register in `mdx-components.tsx`

**Example:**

```tsx
// components/diagrams/MyDiagram.tsx
import { Diagram, DiagramGroup, DiagramNode, DiagramArrow, DiagramGrid } from './DiagramPrimitives';

export function MyDiagram() {
  return (
    <Diagram>
      <DiagramGroup title="Input Layer" color="indigo" columns={3}>
        <DiagramNode icon="terminal" label="CLI" color="indigo" />
        <DiagramNode icon="layout" label="Dashboard" color="indigo" />
        <DiagramNode icon="github" label="GitHub" color="purple" />
      </DiagramGroup>
      <DiagramArrow direction="down" label="commands" />
      <DiagramGroup title="Processing" color="cyan" columns={2}>
        <DiagramNode icon="workflow" label="Orchestrator" color="cyan" />
        <DiagramNode icon="server" label="API" color="cyan" />
      </DiagramGroup>
    </Diagram>
  );
}
```

---

## LLM Support Architecture

The docs site is designed for AI agent consumption from the ground up.

### Endpoints

| URL | Type | Purpose |
|-----|------|---------|
| `/llms.txt` | Dynamic route | Structured index with absolute URLs to every page |
| `/llms-full.txt` | Static route | All docs concatenated — one fetch = full knowledge |
| `/llms` | HTML page | Human-readable LLM docs with copyable system prompt |
| `/docs/<path>.txt` | Rewrite → API | Any individual page as plain text |

### How `.txt` rewrites work

`next.config.mjs` rewrites:
```
/docs/:path*.txt  →  /api/docs-txt/:path*
/docs.txt          →  /api/docs-txt/index
```

The API route at `app/api/docs-txt/[...slug]/route.ts` reads the MDX file, strips frontmatter and JSX components, and returns clean markdown as `text/plain`.

### Per-page LLM buttons

Every docs page renders `<LLMCopyButton>` with three actions:

1. **Copy for LLM** — copies page content (frontmatter/JSX stripped) to clipboard with title prepended
2. **View as TXT** — opens `/docs/<slug>.txt` in new tab (plain text version)
3. **Edit on GitHub** — links to `github.com/.../edit/<branch>/apps/syn-docs/content/docs/<file>.mdx`

The raw content is read server-side in `app/docs/[[...slug]]/page.tsx` using `fs.readFileSync` and passed to the client component.

### Content stripping

Both the per-page route and the full-docs route strip:
- YAML frontmatter (`---\n...\n---`)
- Self-closing JSX components (`<ComponentName />`)
- Excess newlines (3+ → 2)

### System prompt

The `/llms` page includes a copyable system prompt with:
- Architecture overview (4 bounded contexts)
- Key CLI commands
- Service ports table
- Pointers to `/llms.txt` and `/llms-full.txt`

---

## API Docs Generation

API reference pages are auto-generated from the committed `openapi.json`.

### Workflow

1. **Extract spec** (requires Python): `uv run python scripts/extract_openapi.py`
   - Imports FastAPI `create_app()`, calls `app.openapi()`, writes JSON
   - Sets `APP_ENVIRONMENT=test` to skip credential validation
2. **Generate MDX**: `pnpm run generate:openapi` (runs `scripts/generate-api-docs.mjs`)
   - Uses `fumadocs-openapi generateFiles()` to create MDX per OpenAPI tag
   - Output: `content/docs/api/*.mdx`
3. **Commit** `openapi.json` so Vercel builds don't need Python

The `APIPage` component from `fumadocs-openapi` is registered in `lib/source.ts` and available in MDX.

---

## Layout & Navigation

### Nav branding (`lib/layout.shared.tsx`)

```tsx
<div className="flex flex-col">
  <span className="font-bold text-sm tracking-tight text-fd-foreground">
    Syntropic<span className="text-sky-400">137</span>
  </span>
  <span className="text-[10px] text-fd-muted-foreground tracking-wide uppercase">
    Agentic Engineering
  </span>
</div>
```

### Sidebar tabs

Sections with `"root": true` in their `meta.json` become top-level sidebar tabs. Current tabs:
- **Documentation** (guide/)
- **API Reference** (api/)
- **CLI Reference** (cli/)

### Metadata template

```tsx
title: { template: '%s | Syntropic137', default: 'Syntropic137 — Agentic Engineering' }
```

---

## Common Tasks

### Add a new guide page

```bash
# 1. Create the MDX file
cat > apps/syn-docs/content/docs/guide/my-page.mdx << 'EOF'
---
title: My New Page
description: What this page covers
---

Content here. Use any registered MDX components.
EOF

# 2. Add to meta.json
# Edit apps/syn-docs/content/docs/guide/meta.json
# Add "my-page" to the "pages" array
```

### Add a new diagram

1. Create `apps/syn-docs/components/diagrams/NewDiagram.tsx`
2. Add export to `apps/syn-docs/components/diagrams/index.ts`
3. Add import + registration in `apps/syn-docs/mdx-components.tsx`
4. Use `<NewDiagram />` in any MDX file

### Add a new MDX component

1. Create component in `apps/syn-docs/components/`
2. Register in `apps/syn-docs/mdx-components.tsx` inside `getMDXComponents()`
3. Use in MDX without import

### Refresh API docs

```bash
# Full regeneration — CLI docs, OpenAPI spec, API docs, CLI types
just codegen
```

### Edit on GitHub branch

The edit URL branch defaults to `main`. Override with `NEXT_PUBLIC_EDIT_BRANCH` env var during development.
