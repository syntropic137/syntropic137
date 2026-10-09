# Syntropic137 Landing Page — Design System

> **Source:** Approved mood 41A-Comprehensive  
> **Framework:** Agnostic (Vite + React, Vite + vanilla, Next.js, Astro, etc.)  
> **Version:** 1.0 · 2026-03-04

---

## Table of Contents

1. [CSS Custom Properties](#css-custom-properties)
2. [Colors](#colors)
3. [Typography](#typography)
4. [Spacing](#spacing)
5. [Components](#components)
6. [Layout Sections](#layout-sections)
7. [Responsive Breakpoints](#responsive-breakpoints)
8. [Animations](#animations)
9. [Code Syntax Theme](#code-syntax-theme)

---

## CSS Custom Properties

Ready-to-paste `:root` block. Drop this into your global CSS.

```css
:root {
  /* ── Base Palette ── */
  --color-base:             #0F0F1A;
  --color-mid:              #172E75;
  --color-apex:             #E6F2FF;
  --color-accent-primary:   #4D80FF;
  --color-accent-secondary: #3366E6;
  --color-accent-tertiary:  #1A80B3;

  /* ── Semantic Colors ── */
  --color-bg:               #0F0F1A;
  --color-bg-elevated:      rgba(15, 15, 26, 0.8);
  --color-border:           rgba(77, 128, 255, 0.15);
  --color-border-hover:     rgba(77, 128, 255, 0.3);
  --color-text-primary:     #E6F2FF;
  --color-text-secondary:   rgba(230, 242, 255, 0.6);
  --color-text-accent:      #4D80FF;
  --color-glow:             rgba(77, 128, 255, 0.2);

  /* ── Glass ── */
  --glass-bg:               rgba(15, 15, 26, 0.6);
  --glass-blur:             20px;
  --glass-radius:           12px;

  /* ── Nav ── */
  --nav-bg:                 rgba(15, 15, 26, 0.9);
  --nav-border:             rgba(77, 128, 255, 0.1);
  --nav-height:             64px;

  /* ── Blueprint Grid ── */
  --grid-color:             rgba(23, 46, 117, 0.08);
  --grid-size:              40px;

  /* ── Typography ── */
  --font-sans:              system-ui, 'Inter', -apple-system, sans-serif;
  --font-mono:              'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  --font-orbitron:          'Orbitron', var(--font-sans);

  --text-h1:                clamp(36px, 5vw, 56px);
  --text-h2:                clamp(28px, 3.5vw, 36px);
  --text-card-title:        clamp(18px, 2vw, 20px);
  --text-body:              clamp(15px, 1.5vw, 16px);
  --text-code:              clamp(13px, 1.2vw, 14px);
  --text-nav:               14px;
  --text-badge:             12px;

  --weight-regular:         400;
  --weight-medium:          500;
  --weight-semibold:        600;
  --weight-bold:            700;

  /* ── Spacing Scale ── */
  --space-xs:               4px;
  --space-sm:               8px;
  --space-md:               16px;
  --space-lg:               24px;
  --space-xl:               32px;
  --space-2xl:              48px;
  --space-3xl:              64px;
  --space-4xl:              96px;

  /* ── Layout ── */
  --container-max:          1200px;
  --section-padding:        clamp(64px, 8vw, 96px);
  --card-padding:           32px;

  /* ── Transitions ── */
  --ease-default:           cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast:          0.2s;
  --duration-normal:        0.6s;

  /* ── Code Syntax ── */
  --syn-keyword:            #4D80FF;
  --syn-string:             #1A80B3;
  --syn-comment:            rgba(77, 128, 255, 0.4);
  --syn-function:           #E6F2FF;
  --syn-property:           #3366E6;
  --syn-punctuation:        rgba(230, 242, 255, 0.5);

  /* ── Traffic Lights (code editor) ── */
  --dot-red:                #FF5F57;
  --dot-yellow:             #FFBD2E;
  --dot-green:              #27C93F;
}
```

---

## Colors

### Base Palette

| Token | Value | Usage |
|---|---|---|
| `--color-base` | `#0F0F1A` | Page background, darkest tone |
| `--color-mid` | `#172E75` | Mid-tone blue, blueprint grid, subtle fills |
| `--color-apex` | `#E6F2FF` | Lightest tone, primary text |
| `--color-accent-primary` | `#4D80FF` | Main accent — buttons, links, highlights |
| `--color-accent-secondary` | `#3366E6` | Deeper blue — secondary elements, code properties |
| `--color-accent-tertiary` | `#1A80B3` | Teal — strings, tertiary accents |

### Semantic Colors

| Token | Value | Usage |
|---|---|---|
| `--color-bg` | `#0F0F1A` | Body background |
| `--color-bg-elevated` | `rgba(15, 15, 26, 0.8)` | Glass panel backgrounds |
| `--color-border` | `rgba(77, 128, 255, 0.15)` | Default glass borders |
| `--color-border-hover` | `rgba(77, 128, 255, 0.3)` | Hover state borders |
| `--color-text-primary` | `#E6F2FF` | Headlines, card titles, important text |
| `--color-text-secondary` | `rgba(230, 242, 255, 0.6)` | Body copy, descriptions |
| `--color-text-accent` | `#4D80FF` | Accent words, links, commands |
| `--color-glow` | `rgba(77, 128, 255, 0.2)` | Radial glow effects behind hero video/logo |

### Glow Example

```css
.hero-glow {
  background: radial-gradient(
    ellipse 600px 400px at center,
    var(--color-glow) 0%,
    transparent 70%
  );
}
```

---

## Typography

### Font Stacks

```css
body        { font-family: var(--font-sans); }
code, pre   { font-family: var(--font-mono); }
```

**Orbitron** (`--font-orbitron`) is the display face. Used on: hero h1, nav brand, footer name, section/page brand labels. Load via Google Fonts:

```html
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
```

| Element | Font | Weight |
|---|---|---|
| **Hero h1** | `--font-orbitron` | 700 |
| **Nav brand** | `--font-orbitron` | 700 |
| **Footer name** | `--font-orbitron` | 700 |
| **Section brand labels** | `--font-orbitron` | 700 |
| **Body / UI** | `--font-sans` | 400–700 |
| **Code / mono** | `--font-mono` | 400–500 |

### Scale

| Element | Size | Weight | Color | Notes |
|---|---|---|---|---|
| **h1 (Hero)** | 48–56px (mobile: 36px) | 700 | `--color-text-primary` | Orbitron face; accent word "dead." in `--color-text-accent` |
| **h2 (Section)** | 32–36px (mobile: 28px) | 600 | Mixed | e.g. "Why" in primary + "Syntropic" in accent |
| **Card title** | 18–20px | 600 | `--color-text-primary` | |
| **Body** | 15–16px | 400 | `--color-text-secondary` | line-height: 1.6 |
| **Code** | 13–14px | 400 | Per syntax theme | `font-family: var(--font-mono)` |
| **Nav links** | 14px | 500 | `rgba(230, 242, 255, 0.7)` | Hover → `--color-text-primary` |
| **Install cmd** | 14px mono | 400 | `--color-text-accent` | On `rgba(77, 128, 255, 0.1)` bg |
| **Badge (MIT)** | 12px | 600 | `--color-text-accent` | `text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid var(--color-accent-primary)` |

### Accent Word Pattern

Headlines use a two-tone pattern. Wrap accent words in a `<span>`:

```html
<h1>IDEs are <span class="accent">dead.</span></h1>
<h2>Why <span class="accent">Syntropic?</span></h2>
```

```css
.accent { color: var(--color-text-accent); }
```

---

## Spacing

### Scale

| Token | Value |
|---|---|
| `--space-xs` | 4px |
| `--space-sm` | 8px |
| `--space-md` | 16px |
| `--space-lg` | 24px |
| `--space-xl` | 32px |
| `--space-2xl` | 48px |
| `--space-3xl` | 64px |
| `--space-4xl` | 96px |

### Key Measurements

| Element | Value |
|---|---|
| Section vertical padding | 80–96px (`--section-padding`) |
| Container max-width | 1200px, centered |
| Card inner padding | 32px |
| Nav height | 64px |

### Container

```css
.container {
  max-width: var(--container-max);
  margin-inline: auto;
  padding-inline: var(--space-lg);
}

.section {
  padding-block: var(--section-padding);
}
```

---

## Components

### 1. Glass Panel

The foundational surface. Used by cards, nav, code editor, architecture nodes.

```css
.glass {
  background: var(--glass-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--glass-radius);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  transition: border-color var(--duration-fast) var(--ease-default);
}

.glass:hover {
  border-color: var(--color-border-hover);
}
```

---

### 2. Blueprint Grid Background

Applied to `body` or a full-page wrapper. Static — no animation.

```css
.blueprint-grid {
  background-image:
    repeating-linear-gradient(
      0deg,
      var(--grid-color) 0px,
      var(--grid-color) 1px,
      transparent 1px,
      transparent var(--grid-size)
    ),
    repeating-linear-gradient(
      90deg,
      var(--grid-color) 0px,
      var(--grid-color) 1px,
      transparent 1px,
      transparent var(--grid-size)
    );
  background-color: var(--color-bg);
}
```

---

### 3. Button — Primary

```css
.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
  background: var(--color-accent-primary);
  color: var(--color-base);
  padding: 12px 28px;
  border: none;
  border-radius: 8px;
  font-weight: var(--weight-semibold);
  font-size: var(--text-body);
  cursor: pointer;
  transition:
    filter var(--duration-fast) var(--ease-default),
    transform var(--duration-fast) var(--ease-default);
}

.btn-primary:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
}
```

### 4. Button — Ghost

```css
.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
  background: transparent;
  color: var(--color-text-primary);
  padding: 12px 28px;
  border: 1px solid var(--color-border-hover);
  border-radius: 8px;
  font-weight: var(--weight-semibold);
  font-size: var(--text-body);
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease-default),
    transform var(--duration-fast) var(--ease-default);
}

.btn-ghost:hover {
  background: rgba(77, 128, 255, 0.1);
  transform: translateY(-1px);
}
```

---

### 5. Nav Bar

```html
<nav class="nav glass">
  <div class="container nav-inner">
    <div class="nav-left">
      <img src="logo.svg" class="nav-logo" alt="Syntropic137" />
      <span class="nav-brand">SYNTROPIC137</span>
    </div>
    <div class="nav-right">
      <a href="#docs" class="nav-link">Docs</a>
      <a href="#architecture" class="nav-link">Architecture</a>
      <a href="https://github.com/..." class="nav-link">GitHub</a>
      <span class="badge">MIT</span>
    </div>
  </div>
</nav>
```

```css
.nav {
  position: sticky;
  top: 0;
  z-index: 100;
  height: var(--nav-height);
  background: var(--nav-bg);
  border-bottom: 1px solid var(--nav-border);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}

.nav-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.nav-logo { width: 32px; height: 32px; }

.nav-brand {
  font-size: var(--text-nav);
  font-weight: var(--weight-bold);
  color: var(--color-text-accent);
  letter-spacing: 0.05em;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
}

.nav-link {
  font-size: var(--text-nav);
  font-weight: var(--weight-medium);
  color: rgba(230, 242, 255, 0.7);
  text-decoration: none;
  transition: color var(--duration-fast);
}

.nav-link:hover { color: var(--color-text-primary); }

.badge {
  font-size: var(--text-badge);
  font-weight: var(--weight-semibold);
  color: var(--color-text-accent);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 4px 10px;
  border: 1px solid var(--color-accent-primary);
  border-radius: 4px;
}
```

---

### 6. Install Command Block

```html
<div class="install-cmd">
  <span class="install-prefix">$ </span>
  <span class="install-text">npx syntropic137 init</span>
  <button class="install-copy" aria-label="Copy command">📋</button>
</div>
```

```css
.install-cmd {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
  background: rgba(77, 128, 255, 0.1);
  border: 1px solid rgba(77, 128, 255, 0.2);
  border-radius: 8px;
  padding: 10px 20px;
  font-family: var(--font-mono);
  font-size: var(--text-code);
}

.install-prefix { color: var(--color-text-secondary); }
.install-text   { color: var(--color-text-accent); }

.install-copy {
  background: none;
  border: none;
  cursor: pointer;
  opacity: 0;
  transition: opacity var(--duration-fast);
  font-size: 14px;
}

.install-cmd:hover .install-copy { opacity: 0.7; }
.install-copy:hover { opacity: 1 !important; }
```

---

### 7. Code Editor Panel

```html
<div class="code-editor glass">
  <div class="code-titlebar">
    <div class="code-dots">
      <span class="dot dot-red"></span>
      <span class="dot dot-yellow"></span>
      <span class="dot dot-green"></span>
    </div>
    <span class="code-filename">agent.ts</span>
  </div>
  <pre class="code-body"><code>...</code></pre>
</div>
```

```css
.code-editor {
  max-width: 800px;
  margin-inline: auto;
  overflow: hidden;
}

.code-titlebar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: rgba(15, 15, 26, 0.9);
  border-bottom: 1px solid var(--color-border);
}

.code-dots { display: flex; gap: 6px; }

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.dot-red    { background: var(--dot-red); }
.dot-yellow { background: var(--dot-yellow); }
.dot-green  { background: var(--dot-green); }

.code-filename {
  font-family: var(--font-mono);
  font-size: var(--text-code);
  color: var(--color-text-secondary);
  margin-left: var(--space-sm);
}

.code-body {
  padding: var(--space-lg);
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-code);
  line-height: 1.6;
  overflow-x: auto;
}

/* Syntax classes */
.syn-keyword    { color: var(--syn-keyword); }
.syn-string     { color: var(--syn-string); }
.syn-comment    { color: var(--syn-comment); font-style: italic; }
.syn-function   { color: var(--syn-function); }
.syn-property   { color: var(--syn-property); }
.syn-punctuation { color: var(--syn-punctuation); }
```

---

### 8. Value Prop Card

```html
<div class="cards-grid">
  <div class="card glass">
    <div class="card-icon">🧠</div>
    <h3 class="card-title">Persistent Memory</h3>
    <p class="card-desc">Agents that remember context across sessions.</p>
  </div>
  <!-- repeat ×3 -->
</div>
```

```css
.cards-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-lg);
}

.card { padding: var(--card-padding); }

.card-icon {
  font-size: 40px;
  margin-bottom: var(--space-md);
  /* If SVG: width: 40px; height: 40px; color: var(--color-accent-secondary); */
}

.card-title {
  font-size: var(--text-card-title);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--space-sm);
}

.card-desc {
  font-size: var(--text-body);
  color: var(--color-text-secondary);
  line-height: 1.6;
}
```

---

### 9. Architecture Diagram

Three nodes in a horizontal row with arrows between them.

```html
<div class="arch-flow">
  <div class="arch-node glass">
    <div class="arch-icon">🤖</div>
    <div class="arch-title">Agent</div>
    <div class="arch-subtitle">Claude Code / Codex (plugins are Claude-only)</div>
  </div>
  <div class="arch-arrow">→</div>
  <div class="arch-node glass">
    <div class="arch-icon">🌍</div>
    <div class="arch-title">Environment</div>
    <div class="arch-subtitle">Runtime sandbox</div>
  </div>
  <div class="arch-arrow">→</div>
  <div class="arch-node glass">
    <div class="arch-icon">🔌</div>
    <div class="arch-title">Plugin</div>
    <div class="arch-subtitle">Tools & integrations</div>
  </div>
</div>
```

```css
.arch-flow {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-lg);
  flex-wrap: wrap;
}

.arch-node {
  padding: var(--space-lg) var(--space-xl);
  text-align: center;
  min-width: 180px;
}

.arch-icon { font-size: 32px; margin-bottom: var(--space-sm); }

.arch-title {
  font-size: var(--text-card-title);
  font-weight: var(--weight-semibold);
  color: var(--color-text-primary);
}

.arch-subtitle {
  font-size: var(--text-code);
  color: var(--color-text-secondary);
  margin-top: var(--space-xs);
}

.arch-arrow {
  font-size: 28px;
  color: var(--color-text-accent);
  font-weight: var(--weight-bold);
}
```

---

## Layout Sections

Page flows top-to-bottom in this order:

### 1. Nav
Sticky glass bar. Logo + brand left, links + badge right. See [Nav Bar](#5-nav-bar).

### 2. Hero
Split 50/50 on desktop, stacked on mobile (text first).

```css
.hero {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3xl);
  align-items: center;
  min-height: calc(100vh - var(--nav-height));
  padding-block: var(--section-padding);
}

.hero-text { display: flex; flex-direction: column; gap: var(--space-lg); }

.hero-visual {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-video {
  width: 100%;
  max-width: 500px;
  border-radius: var(--glass-radius);
}

/* Radial glow behind video */
.hero-visual::before {
  content: '';
  position: absolute;
  inset: -20%;
  background: radial-gradient(ellipse at center, var(--color-glow), transparent 70%);
  z-index: -1;
}
```

**Contents (left):**
- h1 headline with accent span
- Subtitle paragraph (secondary text)
- Install command block
- Two CTAs: primary + ghost buttons

**Contents (right):**
- `<video autoplay loop muted playsinline>` or 3D logo
- Radial glow behind it

### 3. Why Syntropic?
Section heading (h2 with accent pattern) + 3-column card grid. See [Value Prop Card](#8-value-prop-card).

### 4. Create an Agent
Section heading + centered code editor panel. See [Code Editor Panel](#7-code-editor-panel).

### 5. Architecture
Section heading + horizontal flow diagram. See [Architecture Diagram](#9-architecture-diagram).

### 6. Powered By
Centered text section.

```css
.powered-by {
  text-align: center;
  padding-block: var(--space-3xl);
}

.powered-by p {
  font-size: var(--text-body);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-md);
}
```

Content: "Runs Claude Code and Codex. More harnesses to come." + MIT badge.

### 7. Footer

```css
.footer {
  text-align: center;
  padding-block: var(--space-xl);
  border-top: 1px solid var(--color-border);
  font-size: var(--text-code);
  color: var(--color-text-secondary);
}
```

Content: `SYNTROPIC137 — The agentic engineering platform · MIT License · © 2026`

---

## Responsive Breakpoints

```css
/* Tablet: 768–1024px */
@media (max-width: 1024px) {
  .hero {
    grid-template-columns: 1fr;
    text-align: center;
  }

  .hero-text { align-items: center; }

  .cards-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* Mobile: <768px */
@media (max-width: 768px) {
  :root {
    --text-h1: 36px;
    --text-h2: 28px;
  }

  .cards-grid {
    grid-template-columns: 1fr;
  }

  .arch-flow {
    flex-direction: column;
  }

  .arch-arrow {
    transform: rotate(90deg);
  }

  .nav-right {
    gap: var(--space-md);
  }
}
```

| Breakpoint | Width | Hero | Cards | Fonts |
|---|---|---|---|---|
| Desktop | >1024px | 50/50 grid | 3 columns | h1: 48–56px, h2: 32–36px |
| Tablet | 768–1024px | Stacked (text first) | 2 columns | Same as desktop |
| Mobile | <768px | Stacked, full-width | 1 column | h1: 36px, h2: 28px |

---

## Animations

All animations are subtle and respect `prefers-reduced-motion`.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

### Scroll Fade-In (Glass Panels)

```css
.fade-in {
  opacity: 0;
  transform: translateY(20px);
  transition:
    opacity var(--duration-normal) var(--ease-default),
    transform var(--duration-normal) var(--ease-default);
}

.fade-in.visible {
  opacity: 1;
  transform: translateY(0);
}
```

Trigger via `IntersectionObserver`:

```js
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        observer.unobserve(e.target);
      }
    });
  },
  { threshold: 0.1 }
);

document.querySelectorAll('.fade-in').forEach((el) => observer.observe(el));
```

### Button Hover

Already defined in button styles: `transform: translateY(-1px)` over `0.2s`.

### Hero Video

```html
<video autoplay loop muted playsinline>
  <source src="hero.mp4" type="video/mp4" />
</video>
```

### Typing Animation (Optional — Install Command)

```css
.typing {
  overflow: hidden;
  white-space: nowrap;
  border-right: 2px solid var(--color-text-accent);
  animation:
    typing 1.5s steps(24) forwards,
    blink 0.7s step-end infinite;
}

@keyframes typing {
  from { width: 0; }
  to   { width: 100%; }
}

@keyframes blink {
  50% { border-color: transparent; }
}
```

### Blueprint Grid

Static. No animation.

---

## Code Syntax Theme

For use with any syntax highlighter (Prism, Shiki, Highlight.js) or hand-rolled `<span>` classes.

| Token | Class | Color |
|---|---|---|
| Keywords (`const`, `import`, `from`, `await`, `new`) | `.syn-keyword` | `#4D80FF` |
| Strings (quotes + content) | `.syn-string` | `#1A80B3` |
| Comments (`//`, `/* */`) | `.syn-comment` | `rgba(77, 128, 255, 0.4)` |
| Functions / method names | `.syn-function` | `#E6F2FF` |
| Object properties | `.syn-property` | `#3366E6` |
| Punctuation (`;`, `{}`, `()`, `.`) | `.syn-punctuation` | `rgba(230, 242, 255, 0.5)` |

### Shiki / Prism Theme Override Example

```css
/* Prism overrides */
.token.keyword    { color: var(--syn-keyword) !important; }
.token.string     { color: var(--syn-string) !important; }
.token.comment    { color: var(--syn-comment) !important; font-style: italic; }
.token.function   { color: var(--syn-function) !important; }
.token.property   { color: var(--syn-property) !important; }
.token.punctuation { color: var(--syn-punctuation) !important; }
```

---

## Global Reset (Recommended)

```css
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  scroll-behavior: smooth;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  font-family: var(--font-sans);
  font-size: var(--text-body);
  color: var(--color-text-secondary);
  background-color: var(--color-bg);
  line-height: 1.6;
}

h1, h2, h3 {
  color: var(--color-text-primary);
  line-height: 1.2;
}

a {
  color: var(--color-text-accent);
  text-decoration: none;
}

img, video {
  max-width: 100%;
  display: block;
}
```

---

*This document is the single source of truth for the Syntropic137 landing page visual language. Build from here.*
