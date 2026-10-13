<!--
  One feedback item inside the bubble panel: full comment, type and priority
  chips, status with Open / Resolved toggling (PATCH /feedback/{id}), created
  time as the API sends it, route and URL, the pinned element, and
  screenshots that open full size. Back (or Esc, handled by the bubble)
  returns to the list.
-->
<script lang="ts">
  import { feedbackMediaSrc, getFeedback, updateFeedback, type FeedbackItem, type FeedbackItemWithMedia } from '@syn137/syn-ui-data'
  import ChevronLeft from '@lucide/svelte/icons/chevron-left'
  import { Button } from '@syn137/skyline-svelte-v5'
  import { onDestroy, onMount } from 'svelte'
  import { parseComment } from './comment'
  import { PRIORITY_CHOICES, STATUS_LABEL, typeChoice } from './meta'

  let { item, onback, onchange }: { item: FeedbackItem; onback: () => void; onchange: (i: FeedbackItem) => void } = $props()

  let full = $state<FeedbackItemWithMedia | null>(null)
  let srcs = $state<string[]>([])
  let voices = $state<string[]>([])
  let error = $state<string | null>(null)
  let saving = $state(false)
  let current = $derived<FeedbackItem>(full ?? item)
  let head: HTMLDivElement | undefined = $state()
  const created = $derived(new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(current.created_at)))

  const parsed = $derived(parseComment(current.comment))
  const type = $derived(typeChoice(current.feedback_type))
  const priority = $derived(PRIORITY_CHOICES.find((p) => p.value === current.priority) ?? PRIORITY_CHOICES[0]!)
  const resolved = $derived(current.status === 'resolved')

  $effect(() => {
    const ctl = new AbortController()
    const id = item.id
    void (async () => {
      try {
        const f = await getFeedback(id, ctl.signal)
        full = f
        srcs = await Promise.all((f.media ?? []).filter((m) => m.media_type === 'screenshot').map((m) => feedbackMediaSrc(id, m.id, ctl.signal)))
        voices = await Promise.all((f.media ?? []).filter((m) => m.media_type === 'voice_note').map((m) => feedbackMediaSrc(id, m.id, ctl.signal)))
      } catch (e: unknown) {
        if (!ctl.signal.aborted) error = e instanceof Error ? e.message : 'Could not load this item.'
      }
    })()
    return () => ctl.abort()
  })

  onMount(() => head?.querySelector<HTMLElement>('button')?.focus())

  onDestroy(() => {
    for (const s of [...srcs, ...voices]) if (s.startsWith('blob:')) URL.revokeObjectURL(s)
  })

  async function toggle() {
    saving = true
    error = null
    try {
      const next = await updateFeedback(current.id, { status: resolved ? 'open' : 'resolved' })
      full = full ? { ...full, ...next } : null
      onchange(next)
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : 'Could not update the status.'
    } finally {
      saving = false
    }
  }
</script>

<div class="sky-fb-detail" data-testid="feedback-detail">
  <div class="sky-fb-detail__head" bind:this={head}>
    <Button size="sm" variant="ghost" onclick={onback}>
      {#snippet icon()}<ChevronLeft size={14} aria-hidden="true" />{/snippet}
      Back
    </Button>
    <span class="sky-fb-detail__chip" style:--fb-color={type.color}><span class="sky-fb-detail__dot"></span>{type.label}</span>
    <span class="sky-fb-detail__chip" style:--fb-color={priority.color}><span class="sky-fb-detail__dot"></span>{priority.label}</span>
    <span class="sky-fb-detail__status" data-status={current.status}>{STATUS_LABEL[current.status]}</span>
  </div>

  <p class="sky-fb-detail__comment" data-testid="feedback-detail-comment">{parsed.body || '(no comment)'}</p>

  <dl class="sky-fb-detail__meta">
    <dt>Created</dt>
    <dd><time datetime={current.created_at} title={current.created_at}>{created}</time></dd>
    <dt>Page</dt>
    <dd><code>{current.route ?? '-'}</code></dd>
    <dt>URL</dt>
    <dd class="sky-fb-detail__url">{current.url}</dd>
    {#if current.css_selector}
      <dt>Element</dt>
      <dd><code class="sky-fb-detail__pill" title={current.css_selector}>{parsed.element ?? current.css_selector}</code> <code class="sky-fb-detail__sel">{current.css_selector}</code></dd>
    {/if}
    <dt>Id</dt>
    <dd><code class="sky-fb-detail__sel">{current.id}</code></dd>
  </dl>

  {#each voices as src, i (src)}
    <audio class="sky-fb-detail__audio" controls {src} aria-label="Voice note {i + 1}" data-testid="feedback-detail-voice"></audio>
  {/each}

  {#if srcs.length > 0}
    <ul class="sky-fb-detail__shots" aria-label="Screenshots">
      {#each srcs as src, i (src)}
        <li><a href={src} target="_blank" rel="noopener" aria-label="Open screenshot {i + 1} full size"><img {src} alt="Screenshot {i + 1}" /></a></li>
      {/each}
    </ul>
  {:else if current.media_count > 0 && !full}
    <p class="sky-fb-detail__muted">Loading {current.media_count} attachment{current.media_count === 1 ? '' : 's'}</p>
  {/if}

  {#if error}<p class="sky-fb-detail__error" role="alert">{error}</p>{/if}

  <div class="sky-fb-detail__actions">
    <Button size="sm" variant="outline" loading={saving} onclick={toggle}>{resolved ? 'Reopen' : 'Mark resolved'}</Button>
  </div>
</div>

<style>
  /* Panel 6 + 12 = 18px inset, as the menu and list; the ghost Back sits at the panel edge like the list's. */
  .sky-fb-detail {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
    padding: 0 var(--ds-space-3) var(--ds-space-3);
  }
  .sky-fb-detail__head {
    display: flex;
    margin-left: calc(var(--ds-space-3) * -1);
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5);
  }
  .sky-fb-detail__chip {
    display: inline-flex;
    align-items: center;
    box-sizing: border-box;
    height: var(--ds-space-6);
    gap: var(--ds-space-1-5);
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--fb-color);
    background: color-mix(in oklab, var(--fb-color) 16%, transparent);
    font-size: var(--ds-text-xs);
  }
  .sky-fb-detail__dot {
    width: var(--ds-space-2);
    height: var(--ds-space-2);
    border-radius: 50%;
    background: var(--fb-color);
  }
  .sky-fb-detail__status {
    margin-left: auto;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-muted);
  }
  .sky-fb-detail__status[data-status='resolved'] {
    color: var(--ds-color-success);
  }
  .sky-fb-detail__comment {
    max-height: 12rem;
    margin: 0;
    overflow: auto;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: var(--sky-text-control);
  }
  .sky-fb-detail__meta {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--ds-space-1) var(--ds-space-2);
    margin: 0;
    font-size: var(--ds-text-xs);
  }
  .sky-fb-detail__meta dt {
    color: var(--ds-color-text-subtle);
  }
  .sky-fb-detail__meta dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .sky-fb-detail__meta code {
    font-family: var(--ds-font-mono);
  }
  /* One line, never split across lines (ellipsis; the full selector is in the title). */
  .sky-fb-detail__pill {
    display: inline-block;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: bottom;
    padding: 0 var(--ds-space-1-5);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
  }
  .sky-fb-detail__sel,
  .sky-fb-detail__url,
  .sky-fb-detail__muted {
    color: var(--ds-color-text-muted);
  }
  .sky-fb-detail__muted {
    margin: 0;
    font-size: var(--ds-text-xs);
  }
  .sky-fb-detail__shots {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-fb-detail__shots img {
    display: block;
    width: var(--sky-size-feedback-thumb-w);
    height: var(--sky-size-feedback-thumb-h);
    object-fit: cover;
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
  }
  .sky-fb-detail__audio {
    width: 100%;
    height: var(--sky-size-control-sm);
  }
  .sky-fb-detail__error {
    margin: 0;
    color: var(--ds-color-danger);
    font-size: var(--ds-text-sm);
  }
  .sky-fb-detail__actions {
    display: flex;
    justify-content: flex-end;
  }
</style>
