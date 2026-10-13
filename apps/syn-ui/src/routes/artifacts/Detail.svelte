<!--
  Artifact (boards: Artifact, PhoneArtifact). Header with the type, format,
  size and lineage (workflow -> execution -> phase -> session), Copy and
  Download; the content as Rendered or Raw; a side column with the outline,
  the other files from the same execution and the details. From 64rem the
  side column sits beside the content; on a phone it stacks under it.

  Rendering: a small markdown subset (headings, paragraphs, lists, quotes,
  fenced code, tables, bold and inline code) parsed into blocks and drawn
  as Svelte nodes. No {@html}, so artifact content can never inject markup.
-->
<script module lang="ts">
  type Inline = { kind: 'text' | 'strong' | 'code'; text: string }
  type Block =
    | { kind: 'h'; level: 1 | 2 | 3 | 4; text: Inline[]; anchor: string }
    | { kind: 'p'; text: Inline[] }
    | { kind: 'ul' | 'ol'; items: Inline[][] }
    | { kind: 'quote'; text: Inline[] }
    | { kind: 'code'; lang: string; text: string }
    | { kind: 'table'; head: Inline[][]; rows: Inline[][][] }

  function inline(src: string): Inline[] {
    const out: Inline[] = []
    const re = /\*\*([^*]+)\*\*|`([^`]+)`/g
    let last = 0
    for (let m = re.exec(src); m; m = re.exec(src)) {
      if (m.index > last) out.push({ kind: 'text', text: src.slice(last, m.index) })
      out.push(m[1] !== undefined ? { kind: 'strong', text: m[1] } : { kind: 'code', text: m[2] ?? '' })
      last = m.index + m[0].length
    }
    if (last < src.length) out.push({ kind: 'text', text: src.slice(last) })
    return out
  }

  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()))

  function parseMarkdown(src: string): Block[] {
    const lines = src.replace(/\r\n/g, '\n').split('\n')
    const blocks: Block[] = []
    const used = new Map<string, number>()
    let i = 0
    while (i < lines.length) {
      const line = lines[i] ?? ''
      if (!line.trim()) {
        i++
        continue
      }
      const fence = /^```(\S*)/.exec(line)
      if (fence) {
        const body: string[] = []
        i++
        while (i < lines.length && !(lines[i] ?? '').startsWith('```')) body.push(lines[i++] ?? '')
        i++
        blocks.push({ kind: 'code', lang: fence[1] ?? '', text: body.join('\n') })
        continue
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(line)
      if (h) {
        const text = h[2] ?? ''
        const base = slug(text) || 'section'
        const n = used.get(base) ?? 0
        used.set(base, n + 1)
        blocks.push({ kind: 'h', level: (h[1]?.length ?? 1) as 1 | 2 | 3 | 4, text: inline(text), anchor: n ? `${base}-${n}` : base })
        i++
        continue
      }
      if (line.trim().startsWith('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] ?? '')) {
        const head = cells(line)
        const rows: Inline[][][] = []
        i += 2
        while (i < lines.length && (lines[i] ?? '').trim().startsWith('|')) rows.push(cells(lines[i++] ?? ''))
        blocks.push({ kind: 'table', head, rows })
        continue
      }
      const list = /^\s*([-*]|\d+\.)\s+/.exec(line)
      if (list) {
        const ordered = /\d/.test(list[1] ?? '')
        const items: Inline[][] = []
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i] ?? '')) items.push(inline((lines[i++] ?? '').replace(/^\s*([-*]|\d+\.)\s+/, '')))
        blocks.push({ kind: ordered ? 'ol' : 'ul', items })
        continue
      }
      if (line.startsWith('>')) {
        const body: string[] = []
        while (i < lines.length && (lines[i] ?? '').startsWith('>')) body.push((lines[i++] ?? '').replace(/^>\s?/, ''))
        blocks.push({ kind: 'quote', text: inline(body.join(' ')) })
        continue
      }
      const para: string[] = []
      while (i < lines.length && (lines[i] ?? '').trim() && !/^(#{1,4}\s|```|>|\s*([-*]|\d+\.)\s|\s*\|)/.test(lines[i] ?? '')) para.push(lines[i++] ?? '')
      if (!para.length) para.push(lines[i++] ?? '')
      blocks.push({ kind: 'p', text: inline(para.join(' ')) })
    }
    return blocks
  }
</script>

<script lang="ts">
  import Download from '@lucide/svelte/icons/download'
  import { formatBytes, formatDateTime, shortId } from '@syn137/skyline-core/format'
  import { artifactName } from '@syn137/skyline-core/screens/artifacts'
  import { Button, Callout, EmptyState, Skeleton, ToggleGroup } from '@syn137/skyline-svelte-v5'
  import { CopyButton, LineageTrail, PageHeader } from '@syn137/skyline-svelte-v5/patterns'
  import type { LineageStep } from '@syn137/skyline-core/patterns'
  import { ApiError, getArtifact, listArtifacts } from '@syn137/syn-ui-data'
  import type { ArtifactSummary } from '@syn137/syn-ui-data/types'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import { href } from '../../lib/router'
  import type { PageProps } from '../../lib/routes'

  let { params }: PageProps = $props()

  const art = resource((signal) => getArtifact(params.artifactId ?? '', true, signal))

  const meta = $derived(art.data?.metadata ?? {})
  const str = (v: unknown): string | null => (typeof v === 'string' && v.length > 0 ? v : null)
  const phaseName = $derived(str(meta.phase_name))
  /** The title is often "<phase label>: <path>"; split it so the path reads as a path (board: Artifact). */
  const named = $derived(art.data ? artifactName(art.data.title, str(meta.path), shortId(art.data.id)) : null)
  const path = $derived(named?.path ?? null)
  const title = $derived(named ? (named.label ?? (named.path ? named.name : null) ?? phaseName ?? named.name) : '')
  const fileName = $derived(named?.name ?? '')

  const execOf = (a: ArtifactSummary): string | null => ('execution_id' in a && typeof a.execution_id === 'string' ? a.execution_id : null)

  /**
   * The run that wrote this file and its other files. The detail read has no
   * execution_id (only fixtures put one in metadata), so it comes from this
   * file's own list row; the siblings are then that execution's files, oldest first.
   */
  const run = resource(async (signal) => {
    const a = art.data
    if (!a) return { exec: null as string | null, files: [] as ArtifactSummary[] }
    let exec = str(a.metadata?.execution_id)
    if (!exec && a.workflow_id) {
      const page = await listArtifacts({ page: 1, page_size: 100 }, { workflow_id: a.workflow_id }, signal)
      const own = page.artifacts.find((r) => r.id === a.id)
      exec = own ? execOf(own) : null
    }
    if (!exec) return { exec: null, files: [] }
    const page = await listArtifacts({ page: 1, page_size: 100 }, { execution_id: exec }, signal)
    const files = [...page.artifacts].sort((x, y) => (x.created_at ?? '').localeCompare(y.created_at ?? ''))
    return { exec, files }
  })
  const executionId = $derived(run.data?.exec ?? str(meta.execution_id))
  const siblings = $derived(run.data?.files ?? [])

  $effect(() => {
    const a = art.data
    if (!a) return
    const crumbs: { label: string; href?: string; id?: string }[] = [{ label: 'Artifacts', href: '/artifacts' }]
    if (executionId) crumbs.push({ label: 'Execution', href: `/executions/${encodeURIComponent(executionId)}`, id: shortId(executionId) })
    if (a.session_id) crumbs.push({ label: phaseName ?? a.phase_id ?? 'Session', href: `/sessions/${encodeURIComponent(a.session_id)}` })
    else if (a.phase_id) crumbs.push({ label: phaseName ?? a.phase_id })
    crumbs.push({ label: fileName })
    setPage({ title, crumbs })
  })

  const lineage = $derived.by((): LineageStep[] => {
    const a = art.data
    if (!a) return []
    const steps: LineageStep[] = []
    if (a.workflow_id) steps.push({ kind: 'Workflow', value: a.workflow_id, href: href(`/workflows/${encodeURIComponent(a.workflow_id)}`) })
    if (executionId) steps.push({ kind: 'Execution', value: `exec-${shortId(executionId)}`, href: href(`/executions/${encodeURIComponent(executionId)}`) })
    if (a.phase_id) steps.push({ kind: 'Phase', value: a.phase_id })
    if (a.session_id) steps.push({ kind: 'Session', value: shortId(a.session_id), href: href(`/sessions/${encodeURIComponent(a.session_id)}`) })
    return steps
  })

  const content = $derived(art.data?.content ?? '')
  const isMarkdown = $derived(!!art.data && (/markdown/.test(art.data.content_type) || /\.md$/i.test(fileName)))
  let mode = $state<'rendered' | 'raw'>('rendered')
  const showRendered = $derived(isMarkdown && mode === 'rendered')
  const blocks = $derived(isMarkdown ? parseMarkdown(content) : [])
  const outline = $derived(blocks.filter((b): b is Extract<Block, { kind: 'h' }> => b.kind === 'h' && b.level === 2))

  const eyebrow = $derived(art.data ? [path, art.data.artifact_type].filter(Boolean).join(' · ') : '')
  const formatLine = $derived(art.data ? `${art.data.content_type} · ${formatBytes(art.data.size_bytes)}` : '')

  function download() {
    const a = art.data
    if (!a || a.content === null) return
    const url = URL.createObjectURL(new Blob([a.content], { type: a.content_type || 'text/plain' }))
    const link = document.createElement('a')
    link.href = url
    link.download = fileName || `${a.id}.txt`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }

  const textOf = (parts: Inline[]) => parts.map((p) => p.text).join('')

  function errorText(e: unknown): string {
    if (e instanceof ApiError) return e.status === 404 ? 'No artifact has this ID.' : typeof e.detail === 'string' ? e.detail : `The server answered ${e.status}.`
    return e instanceof Error ? e.message : String(e)
  }
</script>

{#snippet inlines(parts: Inline[])}{#each parts as p, i (i)}{#if p.kind === 'strong'}<strong>{p.text}</strong>{:else if p.kind === 'code'}<code>{p.text}</code>{:else}{p.text}{/if}{/each}{/snippet}

<div class="sky-art">
  {#if art.error && !art.data}
    <Callout tone="danger" title="This artifact did not load." role="alert">
      {errorText(art.error)}
      {#snippet action()}<Button size="sm" onclick={() => art.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !art.data}
    <Skeleton variant="block" height="10rem" label="Loading artifact" />
    <Skeleton variant="text" lines={8} />
  {:else}
    {@const a = art.data}
    <PageHeader kind="artifact" {eyebrow} {title} meta={formatLine}>
      {#if lineage.length}<LineageTrail steps={lineage} />{/if}
      {#snippet actions()}
        <CopyButton variant="label" text={() => content} label="Copy" copiedLabel="Copied" disabled={!content} />
        <Button size="sm" variant="primary" onclick={download} disabled={a.content === null}>
          {#snippet icon()}<Download size={14} aria-hidden="true" />{/snippet}
          Download
        </Button>
      {/snippet}
    </PageHeader>

    <div class="sky-art__split">
      <section class="sky-art__content" aria-label="Content">
        <div class="sky-art__bar">
          <span class="sky-art__file">{fileName}</span>
          {#if isMarkdown}
            <ToggleGroup
              type="single"
              variant="segmented"
              aria-label="View mode"
              items={[
                { value: 'rendered', label: 'Rendered' },
                { value: 'raw', label: 'Raw' },
              ]}
              value={[mode]}
              onValueChange={(v) => (mode = v[0] === 'raw' ? 'raw' : 'rendered')}
            />
          {/if}
        </div>
        {#if !content}
          <EmptyState title="No content stored" description="The artifact record exists but its body was not captured." level={3} bare />
        {:else if showRendered}
          <article class="sky-art__doc">
            {#each blocks as b, i (i)}
              {#if b.kind === 'h'}
                <svelte:element this={`h${Math.min(6, b.level + 1)}`} id={b.anchor}>{@render inlines(b.text)}</svelte:element>
              {:else if b.kind === 'p'}
                <p>{@render inlines(b.text)}</p>
              {:else if b.kind === 'ul'}
                <ul>{#each b.items as it, j (j)}<li>{@render inlines(it)}</li>{/each}</ul>
              {:else if b.kind === 'ol'}
                <ol>{#each b.items as it, j (j)}<li>{@render inlines(it)}</li>{/each}</ol>
              {:else if b.kind === 'quote'}
                <blockquote>{@render inlines(b.text)}</blockquote>
              {:else if b.kind === 'code'}
                <pre class="sky-art__pre" data-lang={b.lang || null}><code>{b.text}</code></pre>
              {:else if b.kind === 'table'}
                <div class="sky-art__table-wrap">
                  <table>
                    <thead><tr>{#each b.head as c, j (j)}<th scope="col">{@render inlines(c)}</th>{/each}</tr></thead>
                    <tbody>
                      {#each b.rows as r, j (j)}<tr>{#each r as c, k (k)}<td>{@render inlines(c)}</td>{/each}</tr>{/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            {/each}
          </article>
        {:else}
          <pre class="sky-art__pre sky-art__raw">{content}</pre>
        {/if}
      </section>

      <aside class="sky-art__side">
        {#if showRendered && outline.length}
          <section class="sky-art__card" aria-label="Outline">
            <h2>Outline</h2>
            <ul class="sky-art__links">
              {#each outline as h (h.anchor)}
                <li><a href={`#${h.anchor}`} data-sky-reload>{textOf(h.text)}</a></li>
              {/each}
            </ul>
          </section>
        {/if}
        {#if siblings.length > 1}
          <section class="sky-art__card" aria-label="From the same execution">
            <h2>From the same execution</h2>
            <ul class="sky-art__links">
              {#each siblings as s, i (s.id)}
                <li>
                  {#if s.id === a.id}
                    <div class="sky-art__sib" aria-current="true">
                      <span class="sky-art__n">{String(i + 1).padStart(2, '0')}</span><span class="sky-art__sib-name">{artifactName(s.title, null, shortId(s.id)).name}</span><span class="sky-art__n">{formatBytes(s.size_bytes)}</span>
                    </div>
                  {:else}
                    <a class="sky-art__sib" href={href(`/artifacts/${encodeURIComponent(s.id)}`)}>
                      <span class="sky-art__n">{String(i + 1).padStart(2, '0')}</span><span class="sky-art__sib-name">{artifactName(s.title, null, shortId(s.id)).name}</span><span class="sky-art__n">{formatBytes(s.size_bytes)}</span>
                    </a>
                  {/if}
                </li>
              {/each}
            </ul>
          </section>
        {/if}
        <section class="sky-art__card" aria-label="Details">
          <h2>Details</h2>
          <dl class="sky-art__dl">
            {#if path}<dt>Path</dt><dd>{path}</dd>{/if}
            <dt>Type</dt><dd>{a.artifact_type}</dd>
            <dt>Format</dt><dd>{a.content_type}</dd>
            <dt>Size</dt><dd>{formatBytes(a.size_bytes)}</dd>
            {#if a.created_at}<dt>Made</dt><dd>{formatDateTime(a.created_at)}</dd>{/if}
            {#if a.is_primary_deliverable}<dt>Role</dt><dd>Primary deliverable</dd>{/if}
            {#if a.derived_from.length}<dt>Derived from</dt><dd>{a.derived_from.map((d) => shortId(d)).join(', ')}</dd>{/if}
            <dt>ID</dt><dd class="sky-art__id">{a.id}<CopyButton text={a.id} label="Copy the artifact ID" /></dd>
          </dl>
        </section>
      </aside>
    </div>
  {/if}
</div>

<style>
  .sky-art {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-art__split {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-5);
    min-width: 0;
  }
  .sky-art__content {
    display: flex;
    flex-direction: column;
    min-width: 0;
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
    overflow: hidden;
  }
  .sky-art__bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
    padding: var(--ds-space-3) var(--ds-space-4);
    border-bottom: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-art__file {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }

  /* ---- rendered markdown ---- */
  .sky-art__doc {
    padding: var(--ds-space-5) var(--ds-space-4) var(--ds-space-6);
    min-width: 0;
    font-size: var(--sky-text-body);
    line-height: 1.65;
    color: var(--ds-color-fg);
    overflow-wrap: anywhere;
  }
  .sky-art__doc :global(h2) {
    margin: 0 0 var(--ds-space-4);
    font-size: var(--ds-text-xl);
    line-height: var(--ds-line-height-tight);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .sky-art__doc :global(h3),
  .sky-art__doc :global(h4),
  .sky-art__doc :global(h5) {
    margin: var(--ds-space-6) 0 var(--ds-space-2);
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
    scroll-margin-top: var(--ds-space-10);
  }
  .sky-art__doc p,
  .sky-art__doc ul,
  .sky-art__doc ol,
  .sky-art__doc blockquote {
    margin: 0 0 var(--ds-space-3);
    color: var(--ds-color-text-muted);
  }
  .sky-art__doc ul,
  .sky-art__doc ol {
    padding-left: var(--ds-space-5);
  }
  .sky-art__doc strong {
    color: var(--ds-color-fg);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-art__doc code {
    padding: 0 var(--ds-space-1);
    border-radius: var(--ds-radius-sm);
    background: var(--ds-color-surface-raised);
    font-family: var(--ds-font-mono);
    font-size: 0.9em;
    color: var(--sky-color-text-code);
  }
  .sky-art__doc blockquote {
    padding-left: var(--ds-space-3);
    border-left: 3px solid var(--sky-color-accent-ring);
  }
  .sky-art__table-wrap {
    margin: 0 0 var(--ds-space-4);
    overflow-x: auto;
  }
  .sky-art__doc table {
    border-collapse: collapse;
    font-size: var(--ds-text-sm);
  }
  .sky-art__doc th,
  .sky-art__doc td {
    padding: var(--ds-space-1-5) var(--ds-space-3);
    border-bottom: var(--ds-border-width) solid var(--sky-color-divider);
    text-align: left;
  }
  .sky-art__doc th {
    color: var(--ds-color-text-subtle);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-art__pre {
    margin: 0 0 var(--ds-space-4);
    padding: var(--ds-space-3) var(--ds-space-4);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-bg);
    overflow-x: auto;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    line-height: 1.6;
    color: var(--sky-color-text-code);
  }
  .sky-art__pre code {
    padding: 0;
    background: none;
  }
  .sky-art__raw {
    margin: 0;
    border-radius: 0;
    padding: var(--ds-space-4);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  /* ---- side column ---- */
  .sky-art__side {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .sky-art__card {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    padding: var(--ds-space-4) var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
  }
  .sky-art__card h2 {
    margin: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-weight: var(--ds-font-weight-regular);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-art__links {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-art__links a {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-2);
    border-radius: var(--ds-radius-md);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
    text-decoration: none;
  }
  .sky-art__links a:hover {
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
  }
  .sky-art__links a:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-art__sib {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-2);
    border-radius: var(--ds-radius-md);
    font-size: var(--ds-text-sm);
  }
  .sky-art__sib[aria-current='true'] {
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
  }
  .sky-art__sib-name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-art__n {
    flex-shrink: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-subtle);
  }
  .sky-art__dl {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    gap: var(--ds-space-2) var(--ds-space-4);
    margin: 0;
    font-size: var(--ds-text-sm);
  }
  .sky-art__dl dt {
    color: var(--ds-color-text-subtle);
  }
  .sky-art__dl dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    color: var(--ds-color-fg);
  }
  .sky-art__id {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1);
  }

  @media (pointer: coarse) {
    .sky-art__links a,
    .sky-art__sib {
      min-height: var(--sky-size-touch);
    }
  }

  @media (min-width: 48rem) {
    .sky-art__doc {
      padding: var(--ds-space-8) var(--ds-space-10) var(--ds-space-10);
    }
    .sky-art__doc :global(h2) {
      font-size: var(--ds-text-2xl);
    }
  }

  @media (min-width: 64rem) {
    .sky-art__split {
      flex-direction: row;
      align-items: flex-start;
    }
    .sky-art__content {
      flex: 1 1 0;
    }
    .sky-art__side {
      flex: 0 0 var(--sky-side-column);
      position: sticky;
      top: var(--ds-space-6);
    }
  }
</style>
