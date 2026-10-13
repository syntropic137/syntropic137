<!-- /dev/components, board CompNav: tabs, pagination, breadcrumbs, the capsule nav and every overlay. -->
<script lang="ts">
  import {
    AlertDialog,
    Breadcrumbs,
    Button,
    Command,
    CommandDialog,
    Dialog,
    DropdownMenu,
    NavigationMenu,
    Pagination,
    Popover,
    Tabs,
    ToggleGroup,
    Tooltip,
  } from '@syn137/skyline-svelte-v5'
  import type { CommandGroup } from '@syn137/skyline-svelte-v5'

  let tab = $state('transcript')
  let page = $state(1)
  let pagesPage = $state(4)
  let nav = $state('executions')
  let paletteOpen = $state(false)
  let last = $state('nothing yet')
  let status = $state<string[]>(['completed'])

  const navItems = [
    { value: 'overview', label: 'Overview', href: '#navigation' },
    { value: 'executions', label: 'Executions', href: '#navigation' },
    { value: 'evals', label: 'Evals', href: '#navigation' },
    { value: 'workflows', label: 'Workflows', href: '#navigation' },
  ]
  const moreItems = [
    { value: 'sessions', label: 'Sessions', href: '#navigation', meta: '108' },
    { value: 'triggers', label: 'Triggers', href: '#navigation', meta: '6' },
  ]
  const groups: CommandGroup[] = [
    {
      heading: 'Workflows',
      items: [
        { id: 'wf-1', label: 'Research Workflow', meta: 'research-workflow-v2', keywords: ['research-workflow-v2'] },
        { id: 'wf-2', label: 'Research with Prompt Files', meta: 'research-with-prompts-v1' },
      ],
    },
    {
      heading: 'Actions',
      items: [
        { id: 'act-1', label: 'Copy agent prompt for Research Workflow' },
        { id: 'act-2', label: 'Go to Evals', shortcut: 'G E' },
      ],
    },
  ]
</script>

<section class="demo" aria-labelledby="demo-tabs">
  <header>
    <h3 id="demo-tabs">Tabs and Pagination</h3>
    <p class="demo__contract">TabsRootContract · PaginationContract</p>
    <p>Tabs switch views in place; every list ends with the count shown and the two buttons.</p>
  </header>
  <Tabs
    label="Session"
    items={[{ value: 'transcript', label: 'Transcript' }, { value: 'tools', label: 'Tools' }, { value: 'tokens', label: 'Tokens' }, { value: 'off', label: 'Raw', disabled: true }]}
    value={tab}
    onValueChange={(v) => (tab = v)}
  >
    {#snippet children(active)}<p class="demo__panel">Showing the {active} tab.</p>{/snippet}
  </Tabs>
  <figure class="demo__wide"><Pagination page={page} pageCount={3} summary={`Showing 12 of 27 workflows`} onPageChange={(p) => (page = p)} /><figcaption>pagination · compact</figcaption></figure>
  <figure class="demo__wide"><Pagination mode="pages" page={pagesPage} pageCount={9} onPageChange={(p) => (pagesPage = p)} /><figcaption>pagination · pages</figcaption></figure>
</section>

<section class="demo" aria-labelledby="demo-nav">
  <header>
    <h3 id="demo-nav">Navigation and Breadcrumbs</h3>
    <p class="demo__contract">NavigationMenuRootContract · pattern · Breadcrumb Trail</p>
    <p>The capsule from 48rem up; the phone hides the middle of the trail behind an ellipsis button.</p>
  </header>
  <figure class="demo__wide">
    <NavigationMenu aria-label="Demo capsule" items={navItems.map((i) => ({ ...i, current: i.value === nav }))} more={moreItems} value={nav} onValueChange={(v) => (nav = v)} />
    <figcaption>capsule</figcaption>
  </figure>
  <figure class="demo__wide">
    <Breadcrumbs
      collapse="never"
      homeHref="#navigation"
      items={[{ label: 'Workflows', href: '#navigation' }, { label: 'Research Workflow', href: '#navigation' }, { label: 'Execution', id: '66e14f23' }]}
    />
    <figcaption>desktop</figcaption>
  </figure>
  <figure class="demo__wide">
    <Breadcrumbs
      collapse="auto"
      homeHref="#navigation"
      items={[{ label: 'Workflows', href: '#navigation' }, { label: 'Research Workflow', href: '#navigation' }, { label: 'Execution', id: '66e14f23' }]}
    />
    <figcaption>auto, collapses on phones</figcaption>
  </figure>
</section>

<section class="demo" aria-labelledby="demo-overlays">
  <header>
    <h3 id="demo-overlays">Overlays</h3>
    <p class="demo__contract">Command · DropdownMenu · Dialog · AlertDialog · Popover · Tooltip</p>
    <p>One raised surface for all of them; the page behind dims to 60%. Last action: <span class="demo__mono">{last}</span></p>
  </header>
  <figure class="demo__wide">
    <Command aria-label="Command demo" {groups} placeholder="Search workflows and actions" escHint={false} onSelect={(i) => (last = i.label)} />
    <figcaption>command, inline</figcaption>
  </figure>
  <div class="demo__row">
    <figure>
      <Button variant="outline" onclick={() => (paletteOpen = true)}>Open ⌘K</Button>
      <CommandDialog aria-label="Command palette" {groups} open={paletteOpen} onOpenChange={(o) => (paletteOpen = o)} onSelect={(i) => { last = i.label; paletteOpen = false }} />
      <figcaption>command dialog</figcaption>
    </figure>
    <figure>
      <DropdownMenu
        label="More"
        items={[
          { type: 'label', label: 'Go to' },
          { label: 'Evals', meta: '65' },
          { label: 'Triggers', meta: '6' },
          { label: 'Sessions', meta: '108' },
          { type: 'separator' },
          { label: 'Delete', tone: 'danger' },
        ]}
        onSelect={(i) => (last = i.label)}
      >
        {#snippet trigger(props)}<Button variant="outline" {...props}>More</Button>{/snippet}
      </DropdownMenu>
      <figcaption>dropdown</figcaption>
    </figure>
    <figure>
      <Popover label="Status filter" heading="Status">
        {#snippet trigger(props)}<Button variant="outline" {...props}>Filter</Button>{/snippet}
        {#snippet children({ close })}
          <ToggleGroup type="multiple" variant="chips" aria-label="Status" items={[{ value: 'completed', label: 'Completed', count: 50 }, { value: 'failed', label: 'Failed', count: 23 }, { value: 'cancelled', label: 'Cancelled', count: 2 }]} value={status} onValueChange={(v) => (status = v)} />
          <Button variant="ghost" size="sm" onclick={close}>Done</Button>
        {/snippet}
      </Popover>
      <figcaption>popover</figcaption>
    </figure>
    <figure>
      <Dialog title="Transcript 2fd5ec12" size="md">
        {#snippet trigger(props)}<Button variant="outline" {...props}>Transcript</Button>{/snippet}
        {#snippet children()}<pre class="demo__pre">{'{"type":"system","subtype":"init","cwd":"/workspace","session_id":"35468ba1"}\n{"type":"assistant","message":…}'}</pre>{/snippet}
      </Dialog>
      <figcaption>dialog</figcaption>
    </figure>
    <figure>
      <AlertDialog
        title="Delete this trigger?"
        description="check_run.completed stops starting Self-Heal PR. Its firing log is kept."
        confirmLabel="Delete trigger"
        tone="danger"
        onConfirm={() => { last = 'deleted trigger' }}
      >
        {#snippet trigger(props)}<Button variant="outline" tone="danger" {...props}>Delete trigger</Button>{/snippet}
      </AlertDialog>
      <figcaption>alert dialog</figcaption>
    </figure>
    <figure>
      <Tooltip content="exec-66e14f235942" hint="Click to copy the full ID" mono>
        {#snippet trigger(props)}<button type="button" class="demo__id" {...props}>66e14f23</button>{/snippet}
      </Tooltip>
      <figcaption>tooltip</figcaption>
    </figure>
  </div>
</section>

<style>
  .demo {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
  }
  .demo header {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
  }
  .demo h3 {
    margin: 0;
    font-size: var(--ds-text-lg);
    font-weight: var(--ds-font-weight-semibold);
  }
  .demo p {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .demo .demo__contract {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .demo__row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--ds-space-4) var(--ds-space-5);
  }
  figure {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ds-space-2);
    margin: 0;
    min-width: 0;
  }
  .demo__wide {
    flex: 1 1 100%;
    align-items: stretch;
  }
  figcaption {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .demo__panel {
    padding-top: var(--ds-space-3);
  }
  .demo__mono,
  .demo__pre,
  .demo__id {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
  }
  .demo__pre {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .demo__id {
    padding: var(--ds-space-1) var(--ds-space-2);
    border: var(--ds-border-width) solid var(--ds-color-border);
    border-radius: var(--ds-radius-sm);
    background: var(--ds-color-bg);
    cursor: pointer;
  }
  .demo__id:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .demo__id {
      min-height: var(--sky-size-touch);
    }
  }
</style>
