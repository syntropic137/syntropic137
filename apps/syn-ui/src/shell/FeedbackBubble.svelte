<!--
  Floating feedback bubble (#1385), bottom right, above the dock on phones.
  Port of the React widget's WidgetButton: a menu with Quick note, Pin to
  element and Recent feedback, and an open-count badge. Shortcuts (`f`, and
  the React widget's Ctrl+Shift+Q / F / T) live in skyline-core's KEYMAP and
  are handled once, by shell/keyboard.ts; this file only reacts to them.
  Lazy-loaded by AppShell on a developer machine only.
-->
<script lang="ts">
  import List from '@lucide/svelte/icons/list'
  import MessageSquarePlus from '@lucide/svelte/icons/message-square-plus'
  import MousePointerClick from '@lucide/svelte/icons/mouse-pointer-click'
  import StickyNote from '@lucide/svelte/icons/sticky-note'
  import X from '@lucide/svelte/icons/x'
  import { getFeatures, getFeedbackStats, listFeedback, type FeedbackItem } from '@syn137/syn-ui-data'
  import { Keycaps } from '@syn137/skyline-svelte-v5/patterns'
  import { FEEDBACK_UI_ATTR } from './feedback/element'
  import FeedbackDetail from './feedback/FeedbackDetail.svelte'
  import { bindingCaps } from './keycaps'
  import { APP_NAME, STATUS_LABEL, typeChoice } from './feedback/meta'
  import { feedbackUi, openFeedback } from './feedback.svelte'

  let menu = $state(false)
  let view = $state<'menu' | 'recent' | 'detail'>('menu')
  let selected = $state<FeedbackItem | null>(null)
  let listEl: HTMLUListElement | undefined = $state()
  /** Row to refocus when the detail view backs out. */
  let lastIndex = 0

  const NOTE_KEYS = bindingCaps('feedback')
  const PICK_KEYS = bindingCaps('feedback-pick')
  const RECENT_KEYS = bindingCaps('feedback-recent')
  let openCount = $state(0)
  let recent = $state<FeedbackItem[] | null>(null)
  let recentError = $state<string | null>(null)
  let root: HTMLDivElement | undefined = $state()
  let trigger: HTMLButtonElement | undefined = $state()

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

  function close() {
    menu = false
    view = 'menu'
  }
  function note() {
    close()
    openFeedback('note')
  }
  function pick() {
    close()
    openFeedback('pick')
  }
  function showRecent() {
    menu = true
    view = 'recent'
    selected = null
    void loadRecent()
  }

  // The Recent feedback shortcut (KEYMAP `feedback-recent`) bumps this.
  let seenRecent = feedbackUi.recentRequest
  $effect(() => {
    if (feedbackUi.recentRequest === seenRecent) return
    seenRecent = feedbackUi.recentRequest
    showRecent()
  })

  function onKey(e: KeyboardEvent) {
    if (!feedbackUi.enabled || e.defaultPrevented) return
    if (e.key === 'Escape' && menu) {
      // Consumed, so the app keymap does not also go back. Steps out one view at a time.
      e.preventDefault()
      if (view === 'detail') backToList()
      else if (view === 'recent') view = 'menu'
      else {
        close()
        trigger?.focus()
      }
    }
  }

  function onDocClick(e: MouseEvent) {
    // composedPath: the clicked icon may already be swapped out of the DOM by the time this runs.
    if (menu && root && !e.composedPath().includes(root)) close()
  }

  function openItem(item: FeedbackItem, index: number) {
    lastIndex = index
    selected = item
    view = 'detail'
  }

  function backToList() {
    view = 'recent'
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
</script>

<svelte:window onkeydown={onKey} />
<svelte:document onclick={onDocClick} />

{#if feedbackUi.enabled && !feedbackUi.open && !feedbackUi.picking}
  <div class="sky-fb-bubble" bind:this={root} {...{ [FEEDBACK_UI_ATTR]: '' }}>
    {#if menu}
      <div class="sky-fb-bubble__panel" role={view === 'menu' ? 'menu' : 'dialog'} aria-label={view === 'menu' ? 'Feedback' : view === 'detail' ? 'Feedback item' : 'Recent feedback'}>
        {#if view === 'menu'}
          <button type="button" role="menuitem" class="sky-fb-bubble__item" onclick={note}>
            <StickyNote size={15} aria-hidden="true" /><span>Quick note</span><Keycaps keys={NOTE_KEYS} />
          </button>
          <button type="button" role="menuitem" class="sky-fb-bubble__item" onclick={pick}>
            <MousePointerClick size={15} aria-hidden="true" /><span>Pin to element</span><Keycaps keys={PICK_KEYS} />
          </button>
          <button type="button" role="menuitem" class="sky-fb-bubble__item" onclick={showRecent}>
            <List size={15} aria-hidden="true" /><span>Recent feedback</span>
            {#if openCount > 0}<span class="sky-fb-bubble__count">{openCount} open</span>{/if}<Keycaps keys={RECENT_KEYS} />
          </button>
        {:else if view === 'detail' && selected}
          <FeedbackDetail item={selected} onback={backToList} onchange={onItemChange} />
        {:else}
          <div class="sky-fb-bubble__recent">
            <div class="sky-fb-bubble__recent-head">
              <button type="button" class="sky-fb-bubble__back" onclick={() => (view = 'menu')}>Back</button>
              <span>Recent from {APP_NAME}</span>
            </div>
            {#if recentError}
              <p class="sky-fb-bubble__muted" role="alert">{recentError}</p>
            {:else if recent === null}
              <p class="sky-fb-bubble__muted">Loading</p>
            {:else if recent.length === 0}
              <p class="sky-fb-bubble__muted">Nothing filed yet.</p>
            {:else}
              <!-- svelte-ignore a11y_no_noninteractive_element_interactions: arrow keys move between the row buttons -->
              <ul class="sky-fb-bubble__list" bind:this={listEl} onkeydown={onListKey} aria-label="Recent feedback">
                {#each recent as item, i (item.id)}
                  <li>
                    <button type="button" class="sky-fb-bubble__row" style:--fb-color={typeChoice(item.feedback_type).color} onclick={() => openItem(item, i)}>
                      <span class="sky-fb-bubble__dot" aria-hidden="true"></span>
                      <span class="sky-fb-bubble__row-text">
                        <span class="sky-fb-bubble__row-title">{firstLine(item.comment)}</span>
                        <span class="sky-fb-bubble__muted">{typeChoice(item.feedback_type).label} · {item.priority} · {STATUS_LABEL[item.status]} · {item.route ?? item.url}</span>
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
    <button
      bind:this={trigger}
      type="button"
      class="sky-fb-bubble__btn"
      aria-label="Send feedback"
      aria-haspopup="menu"
      aria-expanded={menu}
      title="Feedback (F)"
      onclick={() => (menu ? close() : (menu = true))}
    >
      {#if menu}<X size={18} aria-hidden="true" />{:else}<MessageSquarePlus size={18} aria-hidden="true" />{/if}
    </button>
    {#if openCount > 0 && !menu}<span class="sky-fb-bubble__badge" aria-label="{openCount} open">{openCount}</span>{/if}
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
    width: var(--sky-size-feedback-bubble);
    height: var(--sky-size-feedback-bubble);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--ds-color-border);
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
  .sky-fb-bubble__item:focus-visible,
  .sky-fb-bubble__back:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-fb-bubble__badge {
    position: absolute;
    right: calc(var(--ds-space-1) * -1);
    bottom: calc(var(--sky-size-feedback-bubble) - var(--ds-space-2-5));
    min-width: var(--ds-space-4);
    padding: 0 var(--ds-space-1);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--ds-color-bg);
    background: var(--ds-color-accent);
    color: var(--ds-color-accent-contrast);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    font-variant-numeric: tabular-nums;
    line-height: 1.45;
    text-align: center;
    pointer-events: none;
  }
  .sky-fb-bubble__panel {
    display: flex;
    flex-direction: column;
    width: min(20rem, calc(100vw - 2 * var(--sky-gutter)));
    max-height: 60vh;
    overflow: auto;
    padding: var(--ds-space-1-5);
    border-radius: var(--ds-radius-lg);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
  }
  .sky-fb-bubble__item {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-height: var(--sky-size-nav-item);
    padding: 0 var(--ds-space-2-5);
    border: 0;
    border-radius: var(--ds-radius-md);
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .sky-fb-bubble__item:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-fb-bubble__item span:first-of-type {
    flex: 1;
  }
  .sky-fb-bubble__count {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-accent);
  }
  .sky-fb-bubble__recent-head {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    padding: var(--ds-space-1) var(--ds-space-1) var(--ds-space-2);
    color: var(--ds-color-text-muted);
    font-size: var(--sky-text-label);
  }
  .sky-fb-bubble__back {
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--ds-radius-md);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    font: inherit;
    padding: 0 var(--ds-space-2);
    cursor: pointer;
  }
  .sky-fb-bubble__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-fb-bubble__row {
    display: flex;
    gap: var(--ds-space-2);
    width: 100%;
    padding: var(--ds-space-1-5) var(--ds-space-1);
    border: 0;
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
    border-radius: var(--ds-radius-sm);
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .sky-fb-bubble__row:hover {
    background: var(--sky-color-control-hover);
  }
  .sky-fb-bubble__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: calc(var(--sky-focus-ring-width) * -1);
  }
  .sky-fb-bubble__dot {
    flex: none;
    width: var(--ds-space-2);
    height: var(--ds-space-2);
    margin-top: var(--ds-space-1-5);
    border-radius: 50%;
    background: var(--fb-color);
  }
  .sky-fb-bubble__row-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .sky-fb-bubble__row-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-fb-bubble__muted {
    margin: 0;
    color: var(--ds-color-text-subtle);
    font-size: var(--ds-text-xs);
    overflow-wrap: anywhere;
  }
</style>
