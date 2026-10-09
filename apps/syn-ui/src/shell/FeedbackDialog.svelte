<!--
  Feedback dialog (#1385), the React widget's FeedbackModal ported: one box (the
  comment, as typed), with type and priority chips, the page, a pinned element
  and screenshots collapsed under Details (owner: "a simple single feedback
  section"). Defaults Other / Medium, so the comment is the only input. Files through createFeedback(), then uploads
  each screenshot with uploadFeedbackMedia(). Loaded lazily by AppShell.

  FeedbackCreate carries the location (url, route, viewport, css_selector,
  xpath, click point, subject) and environment (app_version, git_commit,
  user_agent, hostname); what it has no field for (element text and box,
  theme) is appended to the comment under a `---` line.
-->
<script lang="ts">
  import Camera from '@lucide/svelte/icons/camera'
  import ImageUp from '@lucide/svelte/icons/image-up'
  import MousePointerClick from '@lucide/svelte/icons/mouse-pointer-click'
  import SquareDashed from '@lucide/svelte/icons/square-dashed'
  import X from '@lucide/svelte/icons/x'
  import {
    ApiError,
    FEEDBACK_IMAGE_TYPES,
    FEEDBACK_MAX_UPLOAD_BYTES,
    createFeedback,
    getBuildInfo,
    uploadFeedbackMedia,
    type FeedbackItem,
    type FeedbackPriority,
    type FeedbackType,
  } from '@syn137/syn-ui-data'
  import { Button, Callout, Dialog, Textarea } from '@syn137/skyline-svelte-v5'
  import { untrack } from 'svelte'
  import { router } from '../lib/router'
  import AreaSelect from './feedback/AreaSelect.svelte'
  import { captureViewport, fromFile, type Area, type Shot } from './feedback/capture'
  import { pageContext, subjectOf } from './feedback/context'
  import ElementPicker from './feedback/ElementPicker.svelte'
  import { FEEDBACK_UI_ATTR, type PinnedElement } from './feedback/element'
  import { APP_NAME, DEFAULT_PRIORITY, DEFAULT_TYPE, PRIORITY_CHOICES, TYPE_CHOICES, type Choice } from './feedback/meta'
  import { APPLE } from './overlays.svelte'
  import { feedbackUi } from './feedback.svelte'
  import { buildView } from '@syn137/skyline-core/screens/version'
  import { UI_VERSION } from './build.svelte'

  type Phase = { kind: 'editing' } | { kind: 'sending' } | { kind: 'sent'; item: FeedbackItem; media: number; mediaFailed: number } | { kind: 'failed'; message: string }
  type Overlay = 'none' | 'element' | 'area'

  let type = $state<FeedbackType>(DEFAULT_TYPE)
  let priority = $state<FeedbackPriority>(DEFAULT_PRIORITY)
  let comment = $state('')
  let detailsOpen = $state(false)
  let commentTouched = $state(false)
  let closeTimer: ReturnType<typeof setTimeout> | undefined
  let element = $state<PinnedElement | null>(null)
  let shots = $state<Shot[]>([])
  let phase = $state<Phase>({ kind: 'editing' })
  let overlay = $state<Overlay>('none')
  let shotError = $state<string | null>(null)
  let capturing = $state(false)
  let dragging = $state(false)
  let fileInput: HTMLInputElement | undefined = $state()

  const commentMissing = $derived(comment.trim() === '')
  const sending = $derived(phase.kind === 'sending')
  const route = $derived(router.path)
  const subject = $derived(subjectOf(route))
  const build = $derived.by(() => {
    void feedbackUi.request
    return getBuildInfo().catch(() => null)
  })

  // Each open request: a fresh form after a sent item; `pick` goes straight to the picker.
  $effect(() => {
    void feedbackUi.request
    untrack(() => {
      if (phase.kind === 'sent') reset()
      if (feedbackUi.start === 'pick') beginOverlay('element')
    })
  })

  function reset() {
    for (const s of shots) URL.revokeObjectURL(s.previewUrl)
    type = DEFAULT_TYPE
    priority = DEFAULT_PRIORITY
    clearTimeout(closeTimer)
    comment = ''
    detailsOpen = false
    element = null
    shots = []
    commentTouched = false
    shotError = null
    phase = { kind: 'editing' }
  }

  function beginOverlay(kind: Exclude<Overlay, 'none'>) {
    overlay = kind
    feedbackUi.picking = true
    feedbackUi.open = false
  }
  function endOverlay() {
    overlay = 'none'
    feedbackUi.picking = false
    feedbackUi.open = true
  }

  function onPick(p: PinnedElement) {
    element = p
    endOverlay()
  }
  function onPickCancel() {
    // Cancelled straight from the bubble with nothing drafted: back to the page.
    const empty = !element && commentMissing && shots.length === 0
    if (empty && feedbackUi.start === 'pick' && phase.kind !== 'failed') {
      overlay = 'none'
      feedbackUi.picking = false
      return
    }
    endOverlay()
  }

  const nextFrame = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())))

  async function shoot(area: Area | null) {
    shotError = null
    capturing = true
    feedbackUi.picking = true
    feedbackUi.open = false
    overlay = 'none'
    await nextFrame()
    try {
      shots = [...shots, await captureViewport(area)]
    } catch (e: unknown) {
      shotError = e instanceof Error ? `Screenshot failed: ${e.message}` : 'Screenshot failed.'
    } finally {
      capturing = false
      feedbackUi.picking = false
      feedbackUi.open = true
    }
  }

  async function addFiles(files: Iterable<File>) {
    shotError = null
    for (const f of files) {
      if (!(FEEDBACK_IMAGE_TYPES as readonly string[]).includes(f.type)) {
        shotError = `${f.name || 'That file'} is not a PNG, JPEG or WebP image.`
        continue
      }
      try {
        const s = await fromFile(f)
        if (s.blob.size > FEEDBACK_MAX_UPLOAD_BYTES) shotError = `${f.name} is over 10 MB.`
        else shots = [...shots, s]
      } catch {
        shotError = `${f.name || 'That image'} could not be read.`
      }
    }
  }

  function removeShot(i: number) {
    const s = shots[i]
    if (s) URL.revokeObjectURL(s.previewUrl)
    shots = shots.filter((_, j) => j !== i)
  }

  function onPaste(e: ClipboardEvent) {
    const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith('image/'))
    if (files.length === 0) return
    e.preventDefault()
    void addFiles(files)
  }
  function onDrop(e: DragEvent) {
    e.preventDefault()
    dragging = false
    void addFiles(e.dataTransfer?.files ?? [])
  }

  function messageOf(e: unknown): string {
    if (e instanceof ApiError && e.status === 404) return 'Feedback is switched off on this API (SYN_UI_FEEDBACK_ENABLED).'
    if (e instanceof Error && e.message) return e.message
    return 'The feedback could not be sent.'
  }

  function contextFooter(theme: string, buildText: string): string {
    const lines: string[] = [buildText]
    if (element) {
      const b = element.box
      lines.push(`element: ${element.label} at ${b.x},${b.y} ${b.width}x${b.height}`)
    }
    lines.push(`theme: ${theme}`)
    return `\n\n---\n${lines.join('\n')}`
  }

  async function submit(e?: Event) {
    e?.preventDefault()
    commentTouched = true
    if (commentMissing || sending) return
    phase = { kind: 'sending' }
    const page = pageContext(route)
    const info = await build
    const body = comment.trim()
    try {
      const item = await createFeedback({
        url: page.url,
        route: page.route,
        viewport_width: page.viewportWidth,
        viewport_height: page.viewportHeight,
        click_x: element?.clickX,
        click_y: element?.clickY,
        css_selector: element?.selector,
        xpath: element?.xpath,
        subject_kind: page.subject?.kind,
        subject_id: page.subject?.id,
        feedback_type: type,
        priority,
        comment: body + contextFooter(page.theme, buildView(info, UI_VERSION).text),
        app_name: APP_NAME,
        app_version: info?.version ?? undefined,
        git_commit: info?.commit ?? undefined,
        user_agent: page.userAgent,
        environment: import.meta.env.DEV ? 'development' : import.meta.env.MODE,
        hostname: page.hostname,
      })
      let media = 0
      let mediaFailed = 0
      for (const s of shots) {
        try {
          await uploadFeedbackMedia(item.id, s.blob, 'screenshot', s.fileName)
          media += 1
        } catch {
          mediaFailed += 1
        }
      }
      phase = { kind: 'sent', item, media, mediaFailed }
      feedbackUi.sent += 1
      // A failed upload stays open so it can be read; otherwise the dialog closes itself.
      if (mediaFailed === 0) closeTimer = setTimeout(closeDialog, 1000)
    } catch (err: unknown) {
      phase = { kind: 'failed', message: messageOf(err) }
    }
  }

  function isTextEntry(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false
    return t.isContentEditable || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement || (t instanceof HTMLInputElement && t.type !== 'radio' && t.type !== 'checkbox' && t.type !== 'button')
  }

  /** Single-key hotkeys while focus is not in a text field; Cmd/Ctrl+Enter submits from anywhere. */
  function onKey(e: KeyboardEvent) {
    if (phase.kind === 'sent' || sending) return
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void submit()
      return
    }
    if (e.ctrlKey || e.metaKey || e.altKey || isTextEntry(e.target)) return
    const k = e.key.toLowerCase()
    const t = TYPE_CHOICES.find((c) => c.key === k)
    const p = PRIORITY_CHOICES.find((c) => c.key === k)
    if (t) type = t.value
    else if (p) priority = p.value
    else if (k === 'e') beginOverlay('element')
    else if (k === 's') void shoot(null)
    else if (k === 'a') beginOverlay('area')
    else if (k === 'c') document.getElementById('sky-feedback-comment')?.focus()
    else return
    e.preventDefault()
  }

  /** Footer Cancel / Done: the footer has no `close`, and a parent-side close skips onOpenChange. */
  function closeDialog() {
    feedbackUi.open = false
    reset()
  }

  function onOpenChange(next: boolean) {
    // A user close (Esc, X, Cancel, Done). Closing for the picker sets `open` directly and never lands here.
    if (!next) reset()
  }

  function initialFocus(): HTMLElement | null {
    return document.getElementById('sky-feedback-comment')
  }

  function onChipKey<V extends string>(e: KeyboardEvent, list: readonly Choice<V>[], current: V, set: (v: V) => void) {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (step === 0) return
    e.preventDefault()
    const i = list.findIndex((c) => c.value === current)
    const next = list[(i + step + list.length) % list.length]!
    set(next.value)
    const group = (e.currentTarget as HTMLElement).closest('[role="radiogroup"]')
    queueMicrotask(() => group?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus())
  }
</script>

{#snippet chips<V extends string>(name: string, list: readonly Choice<V>[], current: V, set: (v: V) => void)}
  {#each list as c (c.value)}
    <button
      type="button"
      role="radio"
      class="sky-fb__chip"
      aria-checked={c.value === current}
      tabindex={c.value === current ? 0 : -1}
      style:--fb-color={c.color}
      data-testid="feedback-{name}-{c.value}"
      disabled={sending}
      onclick={() => set(c.value)}
      onkeydown={(e) => onChipKey(e, list, current, set)}
    >
      <span class="sky-fb__chip-dot" aria-hidden="true"></span><span class="sky-fb__chip-text">{c.label}<kbd class="sky-fb__kbd" aria-hidden="true">{c.key.toUpperCase()}</kbd></span>
    </button>
  {/each}
{/snippet}

{#if overlay === 'element'}
  <ElementPicker onpick={onPick} oncancel={onPickCancel} />
{:else if overlay === 'area'}
  <AreaSelect onselect={(a) => void shoot(a)} oncancel={endOverlay} />
{/if}

<div {...{ [FEEDBACK_UI_ATTR]: '' }}>
  <Dialog bind:open={feedbackUi.open} {onOpenChange} {initialFocus} title="Send feedback" size="md">
    {#snippet children()}
      {#if phase.kind === 'sent'}
        <p class="sky-fb__sent" role="status">
          Sent <code class="sky-fb__id" data-testid="feedback-sent-id">{phase.item.id}</code>{#if phase.media > 0}&nbsp;with {phase.media} screenshot{phase.media === 1 ? '' : 's'}{/if}
        </p>
        {#if phase.mediaFailed > 0}
          <Callout tone="danger" title="Some screenshots did not upload.">{phase.mediaFailed} failed; the item itself was filed.</Callout>
        {/if}
      {:else}
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions: hotkeys, paste and drop are conveniences over the buttons below -->
        <form
          id="sky-fb-form"
          class="sky-fb"
          class:sky-fb--drag={dragging}
          onsubmit={submit}
          onkeydown={onKey}
          onpaste={onPaste}
          ondragover={(e) => {
            e.preventDefault()
            dragging = true
          }}
          ondragleave={() => (dragging = false)}
          ondrop={onDrop}
          novalidate
          aria-busy={sending}
        >
          <Textarea
            id="sky-feedback-comment"
            aria-label="Feedback"
            bind:value={comment}
            rows={5}
            placeholder="What's on your mind?"
            disabled={sending}
            invalid={commentTouched && commentMissing}
            message={commentTouched && commentMissing ? 'Write something first.' : undefined}
            messageTone={commentTouched && commentMissing ? 'danger' : undefined}
          />

          <div class="sky-fb__classify">
            <div class="sky-fb__chips" role="radiogroup" aria-label="Type">
              {@render chips('type', TYPE_CHOICES, type, (v) => (type = v))}
            </div>
            <div class="sky-fb__chips" role="radiogroup" aria-label="Priority">
              {@render chips('priority', PRIORITY_CHOICES, priority, (v) => (priority = v))}
            </div>
          </div>

          <details class="sky-fb__details" bind:open={detailsOpen}>
            <summary class="sky-fb__summary" data-testid="feedback-details">
              <span class="sky-fb__summary-label">Details</span>
              <span class="sky-fb__summary-chips">
                <code class="sky-fb__mini">{route}</code>
                {#if element}<code class="sky-fb__mini">{element.label}</code>{/if}
                {#if shots.length > 0}<span class="sky-fb__mini">{shots.length} screenshot{shots.length === 1 ? '' : 's'}</span>{/if}
              </span>
            </summary>
            <div class="sky-fb__details-body">
              <div class="sky-fb__group" data-testid="feedback-attached">
                <span class="sky-fb__chip-label">Attached to</span>
                <div class="sky-fb__attached">
                <code class="sky-fb__pill" title={location.href}>{route}</code>
                {#if subject}<span class="sky-fb__pill sky-fb__pill--soft">{subject.kind}</span>{/if}
                <span class="sky-fb__pill sky-fb__pill--soft">{innerWidth}×{innerHeight}</span>
                {#await build then info}{@const v = buildView(info, UI_VERSION)}{#if v.label}<span class="sky-fb__pill sky-fb__pill--soft" data-state={v.mismatch ? 'mismatch' : undefined}>{v.label}{v.commit ? ` · ${v.commit}` : ''}{v.mismatch ? ` · ui v${v.ui}` : ''}</span>{/if}{/await}
                </div>
              </div>

              <div class="sky-fb__group">
                <span class="sky-fb__chip-label">Element</span>
                {#if element}
                  <div class="sky-fb__element" data-testid="feedback-element">
                    <code class="sky-fb__pill" title={element.selector}>{element.label}</code>
                    <span class="sky-fb__muted">{element.box.width}×{element.box.height}</span>
                    <Button size="sm" variant="ghost" onclick={() => beginOverlay('element')} disabled={sending}>Re-pick</Button>
                    <Button size="sm" variant="ghost" aria-label="Remove pinned element" onclick={() => (element = null)} disabled={sending}>
                      {#snippet icon()}<X size={14} aria-hidden="true" />{/snippet}
                    </Button>
                  </div>
                {:else}
                  <Button size="sm" variant="outline" onclick={() => beginOverlay('element')} disabled={sending}>
                    {#snippet icon()}<MousePointerClick size={14} aria-hidden="true" />{/snippet}
                    {#snippet iconEnd()}<kbd class="sky-fb__kbd">E</kbd>{/snippet}
                    Pick element
                  </Button>
                {/if}
              </div>

              <div class="sky-fb__group">
                <span class="sky-fb__chip-label">Screenshots</span>
                <div class="sky-fb__shot-actions">
                  <Button size="sm" variant="outline" onclick={() => void shoot(null)} disabled={sending || capturing}>
                    {#snippet icon()}<Camera size={14} aria-hidden="true" />{/snippet}
                    {#snippet iconEnd()}<kbd class="sky-fb__kbd">S</kbd>{/snippet}
                    Take screenshot
                  </Button>
                  <Button size="sm" variant="outline" onclick={() => beginOverlay('area')} disabled={sending || capturing}>
                    {#snippet icon()}<SquareDashed size={14} aria-hidden="true" />{/snippet}
                    {#snippet iconEnd()}<kbd class="sky-fb__kbd">A</kbd>{/snippet}
                    Capture area
                  </Button>
                  <Button size="sm" variant="outline" onclick={() => fileInput?.click()} disabled={sending}>
                    {#snippet icon()}<ImageUp size={14} aria-hidden="true" />{/snippet}
                    Upload image
                  </Button>
                  <input
                    bind:this={fileInput}
                    class="sky-fb__file"
                    type="file"
                    accept={FEEDBACK_IMAGE_TYPES.join(',')}
                    multiple
                    aria-label="Upload image"
                    data-testid="feedback-file"
                    onchange={(e) => {
                      const input = e.currentTarget
                      void addFiles([...(input.files ?? [])]).then(() => (input.value = ''))
                    }}
                  />
                </div>
                <p class="sky-fb__muted sky-fb__drop-hint">Or paste or drop an image here.</p>
                {#if shots.length > 0}
                  <ul class="sky-fb__shots" aria-label="Screenshots to attach">
                    {#each shots as s, i (s.previewUrl)}
                      <li class="sky-fb__shot">
                        <img src={s.previewUrl} alt="Screenshot {i + 1}" />
                        <button type="button" class="sky-fb__icon sky-fb__shot-remove" aria-label="Remove screenshot {i + 1}" onclick={() => removeShot(i)} disabled={sending}><X size={14} aria-hidden="true" /></button>
                      </li>
                    {/each}
                  </ul>
                {/if}
                {#if shotError}<p class="sky-fb__error" role="alert">{shotError}</p>{/if}
              </div>

            </div>
          </details>

          {#if phase.kind === 'failed'}
            <Callout tone="danger" role="alert" title="Not sent.">{phase.message}</Callout>
          {/if}
        </form>
      {/if}
    {/snippet}
    {#snippet footer()}
      {#if phase.kind !== 'sent'}
        <span class="sky-fb__keys">{APPLE ? '⌘' : 'Ctrl'}+Enter send · Esc close · off the text box: B F U P Q O type, 1-4 priority, E pin, S shot, A area</span>
        <Button type="button" variant="ghost" onclick={closeDialog} disabled={sending}>Cancel</Button>
        <Button type="submit" form="sky-fb-form" variant="solid" loading={sending}>{sending ? 'Sending' : 'Send'}</Button>
      {/if}
    {/snippet}
  </Dialog>
</div>

<style>
  .sky-fb {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
  }
  .sky-fb--drag {
    outline: var(--sky-focus-ring-width) dashed var(--sky-feedback-pick);
    outline-offset: var(--ds-space-2);
  }
  .sky-fb__field,
  .sky-fb__group {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-fb__chip-label {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-fb__attached,
  .sky-fb__element,
  .sky-fb__chips,
  .sky-fb__shot-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5);
  }
  .sky-fb__pill {
    display: inline-flex;
    align-items: center;
    box-sizing: border-box;
    height: var(--ds-space-6);
    max-width: 100%;
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-fb__pill--soft {
    color: var(--ds-color-text-muted);
    border-color: var(--ds-color-border);
  }
  /* Type and priority: always visible, compact, one row each under the box. */
  .sky-fb__classify {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1-5);
    margin-top: calc(var(--ds-space-2) * -1);
  }
  .sky-fb__chips {
    gap: var(--ds-space-1);
  }
  .sky-fb__chip {
    display: inline-flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    box-sizing: border-box;
    height: var(--ds-space-6);
    padding: 0 var(--ds-space-2-5);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--sky-color-control);
    color: var(--ds-color-text-muted);
    font: inherit;
    font-size: var(--ds-text-xs);
    cursor: pointer;
  }
  /* Label and key letter share a baseline; the letter shows on hover or focus only. */
  .sky-fb__chip-text {
    display: inline-flex;
    align-items: baseline;
    gap: var(--ds-space-1);
  }
  .sky-fb__chip .sky-fb__kbd {
    display: none;
  }
  .sky-fb__chip:hover .sky-fb__kbd,
  .sky-fb__chip:focus-visible .sky-fb__kbd {
    display: inline;
  }
  @media (pointer: coarse) {
    .sky-fb__chip {
      height: var(--sky-size-control-sm);
    }
  }
  .sky-fb__chip:hover {
    border-color: var(--sky-color-border-hover);
    color: var(--ds-color-fg);
  }
  .sky-fb__chip[aria-checked='true'] {
    border-color: var(--fb-color);
    background: color-mix(in oklab, var(--fb-color) 16%, transparent);
    color: var(--ds-color-fg);
  }
  .sky-fb__chip:focus-visible,
  .sky-fb__icon:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-fb__chip-dot {
    width: var(--ds-space-2);
    height: var(--ds-space-2);
    border-radius: 50%;
    background: var(--fb-color);
  }
  /* One hint style for every in-dialog key letter (chips and buttons). */
  .sky-fb__kbd {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
  }
  .sky-fb__icon {
    display: grid;
    place-items: center;
    padding: 0;
    width: var(--ds-space-6);
    height: var(--ds-space-6);
    border: 0;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
    cursor: pointer;
  }
  /* One control height, one line: the pill shrinks (ellipsis) before anything wraps. */
  .sky-fb__element {
    flex-wrap: nowrap;
  }
  .sky-fb__element .sky-fb__pill {
    min-width: 0;
    flex: 0 1 auto;
  }
  .sky-fb__element .sky-fb__muted {
    flex: none;
  }
  .sky-fb__file {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
  .sky-fb__shots {
    display: flex;
    flex-wrap: wrap;
    gap: var(--ds-space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .sky-fb__shot {
    position: relative;
  }
  .sky-fb__shot img {
    display: block;
    width: var(--sky-size-feedback-thumb-w);
    height: var(--sky-size-feedback-thumb-h);
    object-fit: cover;
    border-radius: var(--ds-radius-md);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
  }
  .sky-fb__shot-remove {
    position: absolute;
    top: var(--ds-space-1);
    right: var(--ds-space-1);
  }
  .sky-fb__muted {
    margin: 0;
    color: var(--ds-color-text-subtle);
    font-size: var(--ds-text-xs);
  }
  /* Belongs to the buttons above: 4 above, 8 below. */
  .sky-fb__drop-hint {
    margin-top: calc(var(--ds-space-1) * -1);
  }
  .sky-fb__sent {
    margin: 0;
    color: var(--ds-color-fg);
    font-size: var(--sky-text-control);
  }
  .sky-fb__details {
    border-top: var(--ds-border-width) solid var(--sky-color-divider);
    padding-top: var(--ds-space-3);
  }
  .sky-fb__summary {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    min-width: 0;
    cursor: pointer;
    list-style: none;
  }
  .sky-fb__summary::-webkit-details-marker {
    display: none;
  }
  .sky-fb__summary::before {
    content: '▸';
    color: var(--ds-color-text-subtle);
    font-size: var(--ds-text-xs);
    transition: transform var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-fb__details[open] > .sky-fb__summary::before {
    transform: rotate(90deg);
  }
  .sky-fb__summary:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
    border-radius: var(--ds-radius-sm);
  }
  .sky-fb__summary-label {
    flex: none;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-fb__summary-chips {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    min-width: 0;
    overflow: hidden;
  }
  .sky-fb__mini {
    display: inline-flex;
    align-items: center;
    flex: none;
    gap: var(--ds-space-1-5);
    max-width: 12rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
  }
  code.sky-fb__mini {
    display: inline-block;
    font-family: var(--ds-font-mono);
  }
  .sky-fb__details-body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    padding-top: var(--ds-space-4);
  }
  .sky-fb__error {
    margin: 0;
    color: var(--ds-color-danger);
    font-size: var(--ds-text-sm);
  }
  /* Lives in the Dialog footer (flex, wrap, gap --ds-space-2): its own line above the buttons. */
  .sky-fb__keys {
    flex: 1 1 100%;
    color: var(--ds-color-text-subtle);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
  }
  @media (pointer: coarse) {
    .sky-fb__keys {
      display: none;
    }
  }
  .sky-fb__id {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    overflow-wrap: anywhere;
  }
</style>
