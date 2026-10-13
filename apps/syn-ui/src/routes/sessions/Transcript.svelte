<!--
  Session transcript (CompNav "dialog · transcript"): the raw JSONL the
  agent wrote, one line per event, each expandable and copyable.
-->
<script lang="ts">
  import { shortId } from '@syn137/skyline-core/format'
  import { getConversationLog, type ConversationLine } from '@syn137/syn-ui-data'
  import { Button, Callout, Dialog, EmptyState, Skeleton } from '@syn137/skyline-svelte-v5'
  import { CopyButton } from '@syn137/skyline-svelte-v5/patterns'
  import { resource } from '../../lib/load.svelte'

  let { sessionId, open = $bindable(false) }: { sessionId: string; open?: boolean } = $props()

  const log = resource((signal) => getConversationLog(sessionId, { limit: 500 }, signal))
  let openLines = $state<number[]>([])

  const pretty = (l: ConversationLine) => {
    if (l.parsed) return JSON.stringify(l.parsed, null, 2)
    try {
      return JSON.stringify(JSON.parse(l.raw), null, 2)
    } catch {
      return l.raw
    }
  }
  const toggle = (n: number) => (openLines = openLines.includes(n) ? openLines.filter((x) => x !== n) : [...openLines, n])
  const allText = () => (log.data?.lines ?? []).map((l) => l.raw).join('\n')
</script>

<Dialog bind:open title="Session transcript" titleId={shortId(sessionId)} description={log.data ? `${log.data.total_lines} lines` : undefined} size="lg">
  {#snippet actions()}
    {#if log.data?.lines.length}<CopyButton variant="label" text={allText} label="Copy all" copiedLabel="Copied all" />{/if}
  {/snippet}
  {#if log.error}
    <Callout tone="danger" title="Couldn't load the transcript.">
      {log.error instanceof Error ? log.error.message : 'Unknown error'}
      {#snippet action()}<Button size="sm" onclick={() => log.refresh()}>Retry</Button>{/snippet}
    </Callout>
  {:else if !log.data}
    <Skeleton lines={6} label="Loading transcript" />
  {:else if log.data.lines.length === 0}
    <EmptyState bare level={3} title="No transcript for this session" description="The agent did not leave a transcript, or it has not been collected yet." />
  {:else}
    <ol class="sky-transcript">
      {#each log.data.lines as line (line.line_number)}
        {@const isOpen = openLines.includes(line.line_number)}
        <li class="sky-transcript__line">
          <button class="sky-transcript__head" type="button" aria-expanded={isOpen} onclick={() => toggle(line.line_number)}>
            <span class="sky-transcript__n">{line.line_number}</span>
            <span class="sky-transcript__type">{line.event_type ?? 'unknown'}</span>
            {#if line.tool_name}<span class="sky-transcript__tool">{line.tool_name}</span>{/if}
            <span class="sky-transcript__preview">{line.content_preview ?? ''}</span>
          </button>
          {#if isOpen}
            <div class="sky-transcript__body">
              <pre>{pretty(line)}</pre>
              <span class="sky-transcript__copy"><CopyButton text={() => pretty(line)} label={`Copy line ${line.line_number}`} copiedLabel={`Copied line ${line.line_number}`} /></span>
            </div>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</Dialog>

<style>
  .sky-transcript {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-transcript__line {
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface-raised);
  }
  .sky-transcript__head {
    display: flex;
    align-items: center;
    gap: var(--ds-space-3);
    width: 100%;
    min-height: var(--sky-size-control-md);
    padding: var(--ds-space-1-5) var(--ds-space-3);
    border: 0;
    border-radius: var(--sky-radius-control);
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .sky-transcript__head:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-transcript__head:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-transcript__n {
    flex-shrink: 0;
    width: 2rem;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-transcript__type {
    flex-shrink: 0;
    padding: 1px var(--ds-space-2);
    border-radius: var(--ds-radius-md);
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-transcript__tool {
    flex-shrink: 0;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-warning-soft-fg);
  }
  .sky-transcript__preview {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-transcript__body {
    position: relative;
    border-top: var(--ds-border-width) solid var(--ds-color-border);
  }
  .sky-transcript__body pre {
    max-height: 24rem;
    margin: 0;
    padding: var(--ds-space-3) 2.75rem var(--ds-space-3) var(--ds-space-3);
    overflow: auto;
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
    line-height: 1.5;
    color: var(--ds-color-text-muted);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .sky-transcript__copy {
    position: absolute;
    top: 5px;
    right: 6px;
  }
  @media (pointer: coarse) {
    .sky-transcript__head {
      min-height: var(--sky-size-touch);
    }
  }
</style>
