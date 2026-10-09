<!--
  Floating feedback bubble (#1385), bottom right, above the dock on phones.
  Port of the React widget's WidgetButton. The bubble is the trigger of a
  DropdownMenu (Quick note, Pin to element, Recent feedback); Recent opens a
  panel above the bubble with the list and one item's detail. Shortcuts (`f`,
  and the React widget's Ctrl+Shift+Q / F / T) live in skyline-core's KEYMAP
  and are handled once, by shell/keyboard.ts; this file only reacts to them.
  Lazy-loaded by AppShell on a developer machine only.
-->
<script lang="ts">
  import ChevronLeft from '@lucide/svelte/icons/chevron-left'
  import List from '@lucide/svelte/icons/list'
  import MessageSquarePlus from '@lucide/svelte/icons/message-square-plus'
  import MousePointerClick from '@lucide/svelte/icons/mouse-pointer-click'
  import StickyNote from '@lucide/svelte/icons/sticky-note'
  import X from '@lucide/svelte/icons/x'
  import { getFeatures, getFeedbackStats, listFeedback, type FeedbackItem } from '@syn137/syn-ui-data'
  import { Button, DropdownMenu, type MenuEntry } from '@syn137/skyline-svelte-v5'
  import { Keycaps } from '@syn137/skyline-svelte-v5/patterns'
  import { FEEDBACK_UI_ATTR } from './feedback/element'
  import FeedbackDetail from './feedback/FeedbackDetail.svelte'
  import { APP_NAME, STATUS_LABEL, typeChoice } from './feedback/meta'
  import { feedbackUi, openFeedback } from './feedback.svelte'
  import { bindingCaps } from './keycaps'

  const NOTE_KEYS = bindingCaps('feedback')
  const PICK_KEYS = bindingCaps('feedback-pick')
  const RECENT_KEYS = bindingCaps('feedback-recent')

  let menuOpen = $state(false)
  /** The Recent panel: closed, the list, or one item. */
  let panel = $state<'none' | 'recent' | 'detail'>('none')
  let selected = $state<FeedbackItem | null>(null)
  let openCount = $state(0)
  let recent = $state<FeedbackItem[] | null>(null)
  let recentError = $state<string | null>(null)
  let root: HTMLDivElement | undefined = $state()
  let bubbleBtn: HTMLButtonElement | null = $state(null)
  let listEl: HTMLUListElement | undefined = $state()
  let panelEl: HTMLDivElement | undefined = $state()
  /** Row to refocus when the detail view backs out. */
  let lastIndex = 0

  $effect(() => {
    const ctl = new AbortController()
    getFeatures(ctl.signal)
      .then((f) => {
        feedbackUi.enabled = f.ui_feedback === true
        if (feedbackUi.enabled) void refreshCount()
      })
      .catch(() => (feedbackUi.enabled = false))
    return () => ctl.abort()
  })

  // Recount after each submit (the dialog bumps `sent`).
  $effect(() => {
    if (feedbackUi.sent > 0) void refreshCount()
  })

  async function refreshCount() {
    try {
      openCount = (await getFeedbackStats(APP_NAME)).by_status?.open ?? 0
    } catch {
      openCount = 0
    }
  }

  async function loadRecent() {
    recentError = null
    try {
      recent = (await listFeedback({ app: APP_NAME, limit: 8 })).items
    } catch (e: unknown) {
      recentError = e instanceof Error ? e.message : 'Could not load feedback.'
    }
  }

  function closePanel(refocus = true) {
    panel = 'none'
    selected = null
    if (refocus) bubbleBtn?.focus()
  }

  function showRecent() {
    menuOpen = false
    selected = null
    panel = 'recent'
    void loadRecent()
    queueMicrotask(() => panelEl?.querySelector<HTMLElement>('button')?.focus())
  }

  // The Recent feedback shortcut (KEYMAP `feedback-recent`) bumps this.
  let seenRecent = feedbackUi.recentRequest
  $effect(() => {
    if (feedbackUi.recentRequest === seenRecent) return
    seenRecent = feedbackUi.recentRequest
    showRecent()
  })

  const items: MenuEntry[] = $derived([
    { label: 'Quick note', icon: noteIcon, end: noteKeys, onSelect: () => openFeedback('note') },
    { label: 'Pin to element', icon: pickIcon, end: pickKeys, onSelect: () => openFeedback('pick') },
    { label: 'Recent feedback', icon: listIcon, meta: openCount > 0 ? `${openCount} open` : undefined, end: recentKeys, onSelect: showRecent },
  ])

  function onKey(e: KeyboardEvent) {
    if (!feedbackUi.enabled || e.defaultPrevented || e.key !== 'Escape' || panel === 'none') return
    // Consumed, so the app keymap does not also go back. Steps out one view at a time.
    e.preventDefault()
    if (panel === 'detail') backToList()
    else closePanel()
  }

  function onDocClick(e: MouseEvent) {
    // composedPath: the clicked icon may already be swapped out of the DOM by the time this runs.
    if (panel !== 'none' && root && !e.composedPath().includes(root)) closePanel(false)
  }

  function openItem(item: FeedbackItem, index: number) {
    lastIndex = index
    selected = item
    panel = 'detail'
  }

  function backToList() {
    panel = 'recent'
    selected = null
    queueMicrotask(() => listEl?.querySelectorAll<HTMLButtonElement>('button')[lastIndex]?.focus())
  }

  function onListKey(e: KeyboardEvent) {
    const step = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0
    if (!step || !listEl) return
    e.preventDefault()
    const rows = [...listEl.querySelectorAll<HTMLButtonElement>('button')]
    const at = rows.findIndex((r) => r === document.activeElement)
    rows[(at + step + rows.length) % rows.length]?.focus()
  }

  function onItemChange(next: FeedbackItem) {
    recent = recent?.map((r) => (r.id === next.id ? next : r)) ?? null
    void refreshCount()
  }

  const firstLine = (c: string | null | undefined) => (c ?? '').split('\n')[0] || '(no comment)'
  const expanded = $derived(menuOpen || panel !== 'none')
</script>

{#snippet noteIcon()}<StickyNote size={15} aria-hidden="true" />{/snippet}
{#snippet pickIcon()}<MousePointerClick size={15} aria-hidden="true" />{/snippet}
{#snippet listIcon()}<List size={15} aria-hidden="true" />{/snippet}
{#snippet noteKeys()}<Keycaps keys={NOTE_KEYS} />{/snippet}
{#snippet pickKeys()}<Keycaps keys={PICK_KEYS} />{/snippet}
{#snippet recentKeys()}<Keycaps keys={RECENT_KEYS} />{/snippet}

<svelte:window onkeydown={onKey} />
<svelte:document onclick={onDocClick} />

{#if feedbackUi.enabled && !feedbackUi.open && !feedbackUi.picking}
  <div class="sky-fb-bubble" bind:this={root} {...{ [FEEDBACK_UI_ATTR]: '' }}>
    {#if panel !== 'none'}
      <div class="sky-fb-bubble__panel" bind:this={panelEl} role="dialog" aria-label={panel === 'detail' ? 'Feedback item' : 'Recent feedback'}>
        {#if panel === 'detail' && selected}
          <FeedbackDetail item={selected} onback={backToList} onchange={onItemChange} />
        {:else}
          <div class="sky-fb-bubble__recent">
            <div class="sky-fb-bubble__recent-head">
              <Button size="sm" variant="ghost" onclick={() => closePanel()}>
                {#snippet icon()}<ChevronLeft size={14} aria-hidden="true" />{/snippet}
                Back
              </Button>
              <span class="sky-fb-bubble__label">Recent from {APP_NAME}</span>
            </div>
            {#if recentError}
              <p class="sky-fb-bubble__muted sky-fb-bubble__note" role="alert">{recentError}</p>
            {:else if recent === null}
              <p class="sky-fb-bubble__muted sky-fb-bubble__note">Loading</p>
            {:else if recent.length === 0}
              <p class="sky-fb-bubble__muted sky-fb-bubble__note">Nothing filed yet.</p>
            {:else}
              <!-- svelte-ignore a11y_no_noninteractive_element_interactions: arrow keys move between the row buttons -->
              <ul class="sky-fb-bubble__list" bind:this={listEl} onkeydown={onListKey} aria-label="Recent feedback">
                {#each recent as item, i (item.id)}
                  <li>
                    <button type="button" class="sky-fb-bubble__row" style:--fb-color={typeChoice(item.feedback_type).color} onclick={() => openItem(item, i)}>
                      <span class="sky-fb-bubble__dot" aria-hidden="true"></span>
                      <span class="sky-fb-bubble__row-text">
                        <span class="sky-fb-bubble__row-title">{firstLine(item.comment)}</span>
                        <span class="sky-fb-bubble__muted">{typeChoice(item.feedback_type).label} · {item.priority} · {STATUS_LABEL[item.status]} · <code>{item.route ?? item.url}</code></span>
                      </span>
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
    <DropdownMenu bind:open={menuOpen} {items} label="Feedback" side="top" align="end" width="17.5rem">
      {#snippet trigger(props)}
        <button
          {...props}
          bind:this={bubbleBtn}
          type="button"
          class="sky-fb-bubble__btn"
          aria-label="Send feedback"
          aria-expanded={expanded}
          title="Feedback (F)"
          onclick={(e) => (panel !== 'none' ? closePanel() : props.onclick?.(e))}
        >
          {#if expanded}<X size={18} aria-hidden="true" />{:else}<MessageSquarePlus size={18} aria-hidden="true" />{/if}
        </button>
      {/snippet}
    </DropdownMenu>
    {#if openCount > 0 && !expanded}<span class="sky-fb-bubble__badge" aria-label="{openCount} open">{openCount}</span>{/if}
  </div>
{/if}

<style>
  .sky-fb-bubble {
    position: fixed;
    right: var(--sky-gutter);
    bottom: calc(var(--ds-space-6) + var(--sky-dock-clearance) + env(safe-area-inset-bottom));
    z-index: var(--sky-z-overlay);
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--ds-space-2);
  }
  .sky-fb-bubble__btn {
    display: grid;
    place-items: center;
    box-sizing: border-box;
    width: var(--sky-size-feedback-bubble);
    height: var(--sky-size-feedback-bubble);
    padding: 0;
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    cursor: pointer;
    box-shadow: var(--sky-shadow-float);
    transition:
      background-color var(--sky-duration-fast) var(--sky-ease-out),
      border-color var(--sky-duration-fast) var(--sky-ease-out),
      color var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-fb-bubble__btn:hover,
  .sky-fb-bubble__btn:focus-visible,
  .sky-fb-bubble__btn[aria-expanded='true'] {
    border-color: var(--sky-color-border-hover);
    background: var(--sky-color-control-hover);
    color: var(--ds-color-accent);
  }
  .sky-fb-bubble__btn:focus-visible,
  .sky-fb-bubble__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-fb-bubble__badge {
    position: absolute;
    right: calc(var(--ds-space-1) * -1);
    bottom: calc(var(--sky-size-feedback-bubble) - var(--ds-space-2-5));
    display: grid;
    place-items: center;
    box-sizing: border-box;
    min-width: var(--ds-space-4);
    height: var(--ds-space-4);
    padding: 0 var(--ds-space-1);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--ds-color-bg);
    background: var(--ds-color-accent);
    color: var(--ds-color-accent-contrast);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-variant-numeric: tabular-nums;
    line-height: 1;
    pointer-events: none;
  }
  /* The Recent panel: the DropdownMenu surface (radius, border, shadow, 6px padding). */
  .sky-fb-bubble__panel {
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
    width: min(20rem, calc(100vw - 2 * var(--sky-gutter)));
    max-height: 60vh;
    overflow: auto;
    padding: var(--ds-space-1-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
  }
  .sky-fb-bubble__recent {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  /* 6 panel + 12 = 18px content inset, as DropdownMenu items. The ghost Back keeps its own padding. */
  .sky-fb-bubble__recent-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-2);
    padding: 0 var(--ds-space-3) var(--ds-space-1) 0;
  }
  .sky-fb-bubble__label {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-fb-bubble__note {
    padding: var(--ds-space-2) var(--ds-space-3);
  }
  .sky-fb-bubble__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-fb-bubble__row {
    display: flex;
    gap: var(--ds-space-2-5);
    box-sizing: border-box;
    width: 100%;
    padding: var(--ds-space-2) var(--ds-space-3);
    border: 0;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .sky-fb-bubble__row:hover {
    background: var(--ds-color-overlay);
  }
  .sky-fb-bubble__row:focus-visible {
    outline-offset: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-fb-bubble__dot {
    flex: none;
    width: var(--ds-space-2);
    height: var(--ds-space-2);
    /* Centred on the title's first line. */
    margin-top: calc((var(--ds-line-height-normal) * 1em - var(--ds-space-2)) / 2);
    border-radius: 50%;
    background: var(--fb-color);
    font-size: var(--sky-text-control);
  }
  .sky-fb-bubble__row-text {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    min-width: 0;
  }
  .sky-fb-bubble__row-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--sky-text-control);
    line-height: var(--ds-line-height-normal);
  }
  .sky-fb-bubble__muted {
    margin: 0;
    color: var(--ds-color-text-subtle);
    font-size: var(--ds-text-xs);
    overflow-wrap: anywhere;
  }
  .sky-fb-bubble__muted code {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
</style>
