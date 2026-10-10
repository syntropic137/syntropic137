<!--
  /dev/patterns: every Skyline pattern with sample data from the canvas
  boards (Main, Execution, Session, Workflow, Evals, Triggers, Artifact,
  PhaseKit, UsageMeter, CompPatterns). A living sheet for review at
  1440, 390 and 320px; not linked from the nav.
-->
<script lang="ts">
  import {
    AgentPromptButton,
    CopyButton,
    DayReadout,
    LineageTrail,
    ObjectIcon,
    OperationTimeline,
    OutcomeRing,
    PageHeader,
    PhaseBlocks,
    PhaseKit,
    PhaseKitChips,
    ProvenanceStrip,
    RuleSentence,
    RunRow,
    RunTiles,
    SkillRef,
    IsoCity,
    Skyline,
    StatusBadge,
    UsageMeter,
    VerdictBlock,
    VerdictBoard,
    VerdictSparkline,
  } from '@syn137/skyline-svelte-v5/patterns'
  import type { SkylineDay } from '@syn137/skyline-core/geometry'
  import { OBJECT_KINDS, phaseTone } from '@syn137/skyline-core/geometry'
  import {
    buildRuleClauses,
    cellKey,
    operationsToText,
    phaseKitLine,
    runBarPercent,
    runSegments,
    runSubline,
    type Operation,
    type Verdict,
    type VerdictCell,
    type VerdictMatrix,
    type Verifier,
  } from '@syn137/skyline-core/patterns'
  import { href } from '../../lib/router'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'

  let { params: _params }: PageProps = $props()
  setPage({ title: 'Patterns', crumbs: [{ label: 'Dev' }, { label: 'Patterns' }] })

  // ---- Skyline (Main board, 2026) --------------------------------------
  const RAW: [string, number, number, number, number, number, number, number][] = [
    ['2026-07-25', 8, 6, 0.2769, 73903, 8458, 60299, 828266],
    ['2026-07-28', 4, 3, 0.1737, 41859, 7150, 30391, 568180],
    ['2026-08-06', 1, 1, 0, 0, 0, 0, 0],
    ['2026-08-08', 5, 4, 0.043, 17, 279, 29892, 29688],
    ['2026-08-10', 5, 5, 0.1793, 78954, 7729, 0, 617216],
    ['2026-08-17', 3, 2, 0.1258, 29972, 4808, 30385, 326031],
    ['2026-08-21', 10, 6, 0.1324, 62, 4626, 69736, 139626],
    ['2026-08-22', 5, 2, 0.2159, 950, 5038, 70631, 204525],
    ['2026-08-26', 5, 2, 0.1266, 50, 5760, 66436, 82410],
    ['2026-08-27', 19, 11, 0.661, 37111, 21117, 154563, 953286],
    ['2026-08-28', 43, 23, 4.9849, 464027, 137651, 517201, 4556030],
  ]
  const days: SkylineDay[] = RAW.map(([date, sessions, executions, costUsd, input, output, cacheWrite, cacheRead]) => ({
    date,
    sessions,
    executions,
    commits: 0,
    costUsd,
    tokens: { input, output, cacheWrite, cacheRead },
  }))
  // 2025 gets a quieter, made-up spread so the year toggle has something to show.
  // Iso City story: the board days, plus two SAMPLE coral days (not real runs).
  const cityDays = $derived<SkylineDay[]>([
    ...days.map((d) => ({ ...d, failed: 0 })),
    { date: '2026-08-12', sessions: 3, executions: 2, failed: 2 },
    { date: '2026-09-01', sessions: 6, executions: 4, failed: 3 },
  ])
  let cityOffset = $state(0)
  let cityPicked = $state<string | null>(null)

  const days2025: SkylineDay[] = Array.from({ length: 40 }, (_, i) => {
    const d = new Date(Date.UTC(2025, 0, 6 + i * 9))
    const s = 1 + ((i * 7) % 13)
    return { date: d.toISOString().slice(0, 10), sessions: s, executions: Math.ceil(s / 2), commits: i % 3, costUsd: s * 0.07, tokens: { input: s * 900, output: s * 400, cacheWrite: s * 3000, cacheRead: s * 21000 } }
  })
  let year = $state(2026)
  let picked = $state<string | null>(null)

  // ---- Run rows (Main board) --------------------------------------------
  const LONGEST = 227_000
  const runs = [
    { status: 'failed', name: 'Starter PR Review', done: 0, total: 2, repo: 'syntropic137/syntropic137', tokens: '0', cost: '$0.00', ms: 5_000, dur: '5s', when: '1w ago' },
    { status: 'failed', name: 'PR Review', done: 0, total: 3, repo: 'syntropic137/syntropic137', tokens: '0', cost: '$0.00', ms: 8_000, dur: '8s', when: '1w ago' },
    { status: 'completed', name: 'Codex delegates to Claude', done: 1, total: 1, repo: '', tokens: '261.7k', cost: '$0.33', ms: 62_000, dur: '1m 2s', when: '6w ago' },
    { status: 'running', name: 'Research Workflow', done: 1, total: 3, repo: '', tokens: '143.9k', cost: '$0.08', ms: 118_000, dur: '1m 58s', when: 'just now' },
    { status: 'cancelled', name: 'Research Workflow', done: 2, total: 3, repo: '', tokens: '156.6k', cost: '$0.17', ms: 200_000, dur: '3m 20s', when: '6w ago' },
    { status: 'completed', name: 'Research Workflow', done: 3, total: 3, repo: '', tokens: '396.8k', cost: '$0.21', ms: 227_000, dur: '3m 47s', when: '6w ago' },
  ]

  // ---- Execution (Execution board) ---------------------------------------
  const phases = [
    { name: 'Discovery Phase', short: 'Discovery', ms: 24_300, tokens: 93_428, cost: 0.0557, session: '10dfeb5d', size: '2.9 KB' },
    { name: 'Deep Dive Analysis', short: 'Deep Dive', ms: 118_900, tokens: 143_918, cost: 0.0798, session: '7288d417', size: '29.4 KB' },
    { name: 'Synthesis & Documentation', short: 'Synthesis', ms: 80_600, tokens: 159_445, cost: 0.0745, session: '3ef71a70', size: '19.8 KB' },
  ]
  const tok = (n: number) => `${(n / 1000).toFixed(1)}K`
  const blocks = phases.map((p) => ({
    name: p.name === 'Discovery Phase' ? 'Discovery' : p.name,
    durationMs: p.ms,
    tokens: p.tokens,
    meta: `${(p.ms / 1000).toFixed(1)}s · ${tok(p.tokens)} tokens · $${p.cost.toFixed(4)}`,
    metaShort: `${(p.ms / 1000).toFixed(1)}s`,
  }))
  const failedBlocks = [
    { name: 'Plan', durationMs: 31_000, tokens: 41_000, tone: phaseTone('completed'), meta: '31.0s · 41.0K tokens', metaShort: '31.0s' },
    { name: 'Implement', durationMs: 96_000, tokens: 120_000, tone: phaseTone('failed'), meta: '96.0s · 120.0K tokens · failed', metaShort: 'failed' },
    { name: 'Review', durationMs: null, tokens: null, tone: phaseTone('pending'), meta: 'not started', metaShort: '' },
  ]
  const runningBlocks = [
    { name: 'Discovery', durationMs: 24_300, tokens: 93_428, tone: phaseTone('completed'), meta: '24.3s', metaShort: '24.3s' },
    { name: 'Deep Dive Analysis', durationMs: 61_000, tokens: 60_000, tone: phaseTone('running'), meta: 'running · 61.0s', metaShort: 'running' },
    { name: 'Synthesis', durationMs: null, tokens: null, tone: phaseTone('pending'), meta: 'pending', metaShort: '' },
  ]

  // ---- Session (Session board) -------------------------------------------
  const ops: Operation[] = [
    { id: 'o1', time: '1:32:22 PM', tool: 'Bash', input: "sed -n '1,240p' /workspace/.agents/skills/delegating-to-claude-p/SKILL.md && printf '\\n--- AGENTS ---\\n' && se…", output: '---', status: 'ok' },
    { id: 'o2', time: '1:32:28 PM', tool: 'Bash', input: "find /workspace/artifacts/input -maxdepth 1 -type f -print -exec sed -n '1,240p' {} \\; ; find /workspace -maxdept…", output: '/workspace/skills-lock.json', status: 'ok' },
    { id: 'o3', time: '1:32:31 PM', tool: 'Edit', input: '/workspace/palindrome.py', status: 'ok' },
    { id: 'o4', time: '1:32:36 PM', tool: 'Bash', input: "python -m py_compile /workspace/palindrome.py && python - <<'PY' …", output: '/bin/bash: line 1: python: command not found', status: 'failed' },
    { id: 'o5', time: '1:32:42 PM', tool: 'Bash', input: "python3 -m py_compile /workspace/palindrome.py && python3 - <<'PY' …", output: '/bin/bash: line 1: python3: command not found', status: 'failed' },
    {
      id: 'o6',
      time: '1:32:46 PM',
      tool: 'Bash',
      input: 'claude -p --permission-mode bypassPermissions --output-format stream-json --verbose "Review /workspace/palindrome.py…',
      output: '{"type":"system","subtype":"init","cwd":"/workspace","session_id":"35468ba1-dca4-4f8c-9012-4fb500342e79","tools":["Task","Bash","CronCreate"…',
      status: 'ok',
      duration: '6s',
      delegated: { agent: 'Claude', agentKind: 'claude', label: 'Handed off to Claude · child session', id: '35468ba1', href: href('/sessions/35468ba1') },
    },
    { id: 'o7', time: '1:32:59 PM', tool: 'Edit', input: '/workspace/artifacts/output/deliverable.md', status: 'ok' },
    {
      id: 'o8',
      time: '1:33:03 PM',
      tool: 'Bash',
      input: "sed -n '1,120p' /workspace/palindrome.py && sed -n '1,200p' /workspace/artifacts/output/deliverable.md",
      output: ['"""Utilities for identifying palindromic strings."""', '', 'import re', '', '', 'def is_palindrome(text: str) -> bool:', '    cleaned = re.sub(r"[^a-z0-9]", "", text.lower())', '    return cleaned == cleaned[::-1]', '', '', '# Deliverable', '', 'One sentence on sorting.'].join('\n'),
      status: 'ok',
    },
    { id: 'o9', time: '1:33:08 PM', tool: 'Capture', input: 'Session captured', status: 'quiet' },
  ]
  let opFilter = $state<'all' | 'bash' | 'edit' | 'errors'>('all')
  let expandAll = $state(false)
  const shownOps = $derived(ops.filter((o) => (opFilter === 'all' ? true : opFilter === 'errors' ? o.status === 'failed' : o.tool.toLowerCase() === opFilter)))

  // ---- Evals (Evals board) -----------------------------------------------
  const CASES = [
    { id: 'shared-esp-stream', pr: 1574, sha: '6646da278d17' },
    { id: 'execution-id-as-eval-id', pr: 1649, sha: '7047b1c3daf1' },
    { id: 'binary-artifact-minio-key', pr: 1652, sha: 'b2f680f00b4e' },
    { id: 'codex-cost-limit', pr: 1654, sha: '123b25204fce' },
    { id: 'live-commits-unvalidated-sha', pr: 1679, sha: '4c16d8f95fca' },
    { id: 'repo-privacy-ignores-app', pr: 1680, sha: '4c16d8f95fca' },
  ]
  const cases = CASES.map((c) => ({ id: c.id, name: c.id, sub: `PR #${c.pr} · ${c.sha.slice(0, 7)}` }))
  const verifiers: Verifier[] = [
    { id: 'opus', agent: 'Claude', agentKind: 'claude', model: 'claude-opus-5-5', short: 'opus', workflow: 'eval-verify-pinned-v1' },
    { id: 'sonnet', agent: 'Claude', agentKind: 'claude', model: 'claude-sonnet-5-5', short: 'sonnet', workflow: 'eval-verify-pinned-sonnet-v1' },
    { id: 'sol', agent: 'Codex', agentKind: 'codex', model: 'gpt-5.6-sol', short: 'sol', workflow: 'eval-verify-pinned-codex-v1' },
    { id: 'terra', agent: 'Codex', agentKind: 'codex', model: 'gpt-5.6-terra', short: 'terra', workflow: 'eval-verify-pinned-codex-gpt-5-6-terra-v1' },
  ]
  const DATES = ['Oct 2, 2026', 'Oct 6, 2026', 'Oct 4, 2026', 'Oct 7, 2026, 5:31 PM']
  const P = 'pass', F = 'fail', E = 'error', U = 'unscored'
  const M: [Verdict, number, number][][] = [
    [[P, 1.04, 372], [P, 0.52, 245], [P, 0.66, 228], [U, 0.61, 190]],
    [[P, 0.97, 341], [F, 0.47, 228], [P, 0.59, 204], [U, 0.55, 176]],
    [[P, 1.28, 418], [P, 0.61, 276], [F, 0.71, 246], [U, 0.68, 214]],
    [[P, 0.9, 305], [P, 0.44, 214], [P, 0.49, 187], [U, 0.52, 168]],
    [[P, 1.12, 388], [F, 0.55, 251], [F, 0.63, 219], [U, 0.58, 195]],
    [[F, 1.19, 402], [F, 0.58, 263], [E, 0.6, 231], [U, 0.64, 201]],
  ]
  const FILES = ['ExecutionRequestAggregate.py', 'EvalAggregate.py', 'minio.py', 'CodexStreamProcessor.py', 'useEventFeed.ts', 'useRepoList.ts']
  const evidence = (v: Verdict, file: string, alt: boolean) =>
    v === 'pass'
      ? `Blocked the change. Names ${file} and matches every keyword group.`
      : v === 'fail'
        ? alt
          ? `Blocked, but the report never names ${file}.`
          : `Approved the change. The defect in ${file} went unreported.`
        : v === 'error'
          ? 'The scorer could not read a verdict from the verify report.'
          : 'Not scored yet. A verdict appears once the suite scorer has judged this run.'
  const cells: VerdictMatrix = {}
  CASES.forEach((c, i) =>
    verifiers.forEach((v, j) => {
      const [verdict, cost, secs] = M[i]![j]!
      const cell: VerdictCell = {
        verdict,
        costUsd: cost,
        durationMs: secs * 1000,
        date: DATES[j],
        evidence: evidence(verdict, FILES[i]!, (i + j) % 2 === 0),
        evalHref: href(`/evals/${c.id}-${v.id}`),
        runHref: href(`/executions/exec-${c.sha}`),
      }
      cells[cellKey(c.id, v.id)] = cell
    }),
  )
  let verdictPick = $state<string | null>(cellKey('shared-esp-stream', 'terra'))

  // ---- Triggers (Triggers board) -----------------------------------------
  const ruleInput = {
    event: 'check_run.completed',
    repository: 'syntropic137/syntropic137',
    conditions: [
      { field: 'check_run.conclusion', operator: 'eq', value: 'failure' },
      { field: 'check_run.pull_requests', operator: 'not_empty' },
    ],
    workflowName: 'Self-Heal PR',
    workflowHref: href('/workflows/self-heal-pr'),
    inputs: {
      repository: 'repository.full_name',
      pr_number: 'check_run.pull_requests[0].number',
      head_sha: 'check_run.head_sha',
      check_name: 'check_run.name',
      conclusion: 'check_run.conclusion',
      details_url: 'check_run.details_url',
      installation_id: 'installation.id',
    },
    caps: [
      { value: '3', label: 'max attempts' },
      { value: '20', label: 'runs per day' },
      { value: '300s', label: 'cooldown' },
      { value: '0s', label: 'debounce' },
    ],
    log: "Hasn't fired yet",
    logDetail: 'Each firing will list the event, the execution it started and the outcome.',
  }
  const fullRule = buildRuleClauses(ruleInput)
  const compactRule = buildRuleClauses({ ...ruleInput, repository: null, conditions: ruleInput.conditions.slice(0, 1), inputs: null, caps: [], log: '' }).map((c) =>
    c.key === 'then' ? { ...c, lines: [['Run ', { link: 'Self-Heal PR', href: ruleInput.workflowHref }, ' with 7 inputs']] } : c,
  )

  const STATUSES = ['completed', 'failed', 'cancelled', 'running', 'pending', 'queued', 'interrupted', 'skipped', 'waiting_for_review']
  const VERDICTS: Verdict[] = ['pass', 'fail', 'error', 'unscored']
</script>

<div class="dev-patterns">
  <header class="dev-patterns__intro">
    <h1>Patterns</h1>
    <p>Every Skyline pattern with sample data from the canvas boards. Resize to 390 and 320px to check the phone layouts.</p>
  </header>

  <section class="dev-patterns__sheet" aria-labelledby="p-iso-city">
    <h2 id="p-iso-city">Iso City</h2>
    <p class="dev-patterns__note">Main and PhoneOverview boards: the Overview heatmap. The 11 real board days plus two sample coral days (most runs failed). Month buttons, the week strip, drag, a horizontal wheel or the arrow keys on the focused city scroll it. Offset <code>{cityOffset}</code>, picked <code>{cityPicked ?? 'latest'}</code>.</p>
    <div class="dev-patterns__hero">
      <IsoCity days={cityDays} today="2026-09-04" bind:offset={cityOffset} bind:selected={cityPicked} runsHref={(d) => href(`/executions?day=${d.date}`)} badge="Sample history" />
    </div>
    <div class="dev-patterns__row">
      <div class="dev-patterns__phone"><IsoCity days={cityDays} today="2026-09-04" badge="Sample" /></div>
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-skyline">
    <h2 id="p-skyline">Skyline and Day Readout</h2>
    <p class="dev-patterns__note">Main and PhoneOverview boards. Point, focus, click or use the arrow keys on a bar. Picked: <code>{picked ?? 'latest'}</code>.</p>
    <div class="dev-patterns__hero">
      <Skyline
        days={year === 2026 ? days : days2025}
        today="2026-10-07"
        {year}
        years={[2025, 2026]}
        onyearchange={(y) => (year = y)}
        bind:selected={picked}
        runsHref={(d) => href(`/executions?day=${d.date}`)}
      />
    </div>
    <div class="dev-patterns__row">
      <div class="dev-patterns__fixed"><DayReadout day={days[10] ?? null} runsHref={href('/executions')} /></div>
      <div class="dev-patterns__fixed"><DayReadout day={days[2] ?? null} variant="card" position="3 of 11 active days" /></div>
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-icons">
    <h2 id="p-icons">Object Icon and Status Badge</h2>
    <div class="dev-patterns__row">
      {#each OBJECT_KINDS as k (k)}
        <figure class="dev-patterns__figure"><ObjectIcon kind={k} size={72} label={k} /><figcaption>{k}</figcaption></figure>
      {/each}
    </div>
    <div class="dev-patterns__row">
      {#each STATUSES as s (s)}<StatusBadge status={s} />{/each}
    </div>
    <div class="dev-patterns__row">
      {#each STATUSES.slice(0, 5) as s (s)}<StatusBadge status={s} shape="square" />{/each}
      {#each ['failed', 'completed'] as s (s)}<StatusBadge status={s} shape="glyph" />{/each}
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-header">
    <h2 id="p-header">Page Header</h2>
    <PageHeader
      kind="execution"
      eyebrow="exec-66e14f235942"
      status="completed"
      meta="3 of 3 phases · Aug 27, 2026, 2:59 AM"
      titleLabel="Task"
      title="one sentence on sorting"
      figures={[
        { label: 'Duration', value: '3m 47s' },
        { label: 'Cost', value: '$0.2100' },
        { label: 'Tokens', value: '396,791' },
        { label: 'Artifacts', value: '3' },
      ]}
    >
      {#snippet titleAction()}<CopyButton text="one sentence on sorting" label="Copy task" copiedLabel="Copied the task" />{/snippet}
      {#snippet actions()}
        <CopyButton variant="label" text="exec-66e14f235942" label="Copy run identity" copiedLabel="Copied run identity" />
        <a class="dev-patterns__primary" href={href('/workflows/research-workflow-v2')}>Run again</a>
      {/snippet}
    </PageHeader>
    <PageHeader
      kind="workflow"
      eyebrow="research-workflow-v2 · research · template"
      title="Research Workflow"
      description="A structured research workflow for investigating codebases, technologies, or concepts. Produces comprehensive documentation."
      figureColumns={3}
      figures={[
        { label: 'Runs', value: '12' },
        { label: 'Sessions', value: '32' },
        { label: 'Artifacts', value: '21' },
        { label: 'Tokens', value: '2.79M' },
        { label: 'Spend', value: '$1.4285' },
      ]}
    >
      <AgentPromptButton
        prompt={{
          workflowName: 'Research Workflow',
          workflowId: 'research-workflow-v2',
          inputs: [
            { name: 'task', required: true, description: 'fills $ARGUMENTS in the phase prompts.', placeholder: '<what to research>' },
            { name: 'topic', required: false, placeholder: '<short label>' },
          ],
          phases: ['Discovery Phase', 'Deep Dive Analysis', 'Synthesis & Documentation'],
        }}
      />
    </PageHeader>
    <PageHeader kind="artifact" eyebrow="text/markdown · 19.8 KB" title="Synthesis & Documentation">
      <LineageTrail
        steps={[
          { kind: 'Workflow', value: 'research-workflow-v2', href: href('/workflows/research-workflow-v2') },
          { kind: 'Execution', value: 'exec-66e14f23', href: href('/executions/exec-66e14f235942') },
          { kind: 'Phase', value: 'synthesis' },
          { kind: 'Session', value: '3ef71a70', href: href('/sessions/3ef71a70') },
        ]}
      />
    </PageHeader>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-runs">
    <h2 id="p-runs">Run Row and Outcome Ring</h2>
    <p class="dev-patterns__note">Bar length is duration, each block is a phase.</p>
    <div class="dev-patterns__list">
      {#each runs as r, i (i)}
        <RunRow
          href={href('/executions/exec-66e14f235942')}
          status={r.status}
          name={r.name}
          sub={runSubline(r.repo, r.done, r.total)}
          segments={runSegments({ status: r.status, done: r.done, total: r.total })}
          barPercent={runBarPercent(r.ms, LONGEST)}
          duration={r.dur}
          tokens={r.tokens}
          cost={r.cost}
          when={r.when}
        />
      {/each}
    </div>
    <div class="dev-patterns__row">
      <div class="dev-patterns__card"><OutcomeRing completed={50} failed={23} cancelled={2} /></div>
      <OutcomeRing completed={50} failed={23} cancelled={2} legend={false} size={110} />
      <OutcomeRing completed={0} failed={0} cancelled={0} legend={false} size={110} />
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-usage">
    <h2 id="p-usage">Usage Meter</h2>
    <UsageMeter
      cost="$0.2162"
      tokens={{ cacheRead: 144_128, cacheWrite: 0, output: 1_945, input: 29_924 }}
      costBy="model"
      rates={{ cacheRead: '0.1× rate' }}
      costRows={[{ label: 'gpt-5.6-sol', value: 0.2162 }]}
    />
    <div class="dev-patterns__split">
      <UsageMeter
        tokens={{ cacheRead: 313_560, cacheWrite: 64_884, output: 18_254, input: 93 }}
        costBy="phase"
        costRows={phases.map((p, i) => ({ label: `0${i + 1} ${p.short}`, value: p.cost }))}
        note="Model unknown: all three phases requested haiku, and the cost is not attributed to a model."
      />
      <div class="dev-patterns__narrow">
        <UsageMeter
          cost="$0.2162"
          tokens={{ cacheRead: 144_128, cacheWrite: 0, output: 1_945, input: 29_924 }}
          costBy="model"
          rates={{ cacheRead: '0.1× rate' }}
          costRows={[{ label: 'gpt-5.6-sol', value: 0.2162 }]}
        />
      </div>
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-phases">
    <h2 id="p-phases">Phase Blocks, Run Tiles and Provenance Strip</h2>
    <div class="dev-patterns__card">
      <p class="dev-patterns__note">Length is time, height is tokens. 223.8s inside phases.</p>
      <PhaseBlocks phases={blocks} />
      <div class="dev-patterns__phases">
        {#each phases as p, i (p.name)}
          <div class="dev-patterns__phase">
            <span class="dev-patterns__phase-name">0{i + 1} {p.name}</span>
            <RunTiles
              phase={p.name}
              session={{ id: p.session, note: 'platform session · no local transcript', href: href(`/sessions/${p.session}`) }}
              artifact={{ name: 'deliverable.md', size: p.size, href: href(`/artifacts/${p.session}`) }}
            />
          </div>
        {/each}
        <div class="dev-patterns__phase">
          <span class="dev-patterns__phase-name">Older run</span>
          <RunTiles phase="Review" session={null} artifact={null} />
        </div>
      </div>
      <ProvenanceStrip
        counts={{ platformSessions: 3, nativeTranscripts: 0, invocations: 0, gaps: 1 }}
        warning={{ lead: "Coverage can't be proven for this harness.", body: 'The three sessions above are real, but others may exist. Missing host registration affects all 3.' }}
        note="This run started before start config was pinned, so the tools and skills each phase had were not recorded. Which skills an agent actually used is not reported yet either."
        facts={['revision f82315509573…b742d4d5', 'reconstruction current', 'every section loaded', 'no parent sessions', 'remote replication off']}
        actionLabel="Load latest revision"
        onaction={() => undefined}
      />
    </div>
    <div class="dev-patterns__split">
      <div class="dev-patterns__card"><PhaseBlocks phases={failedBlocks} /></div>
      <div class="dev-patterns__card"><PhaseBlocks phases={runningBlocks} /></div>
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-kit">
    <h2 id="p-kit">Phase Kit and Skill Ref</h2>
    <div class="dev-patterns__grid">
      <PhaseKit
        eyebrow="Declared on a workflow · two skills"
        title="Skills Matrix › Both Kinds"
        model={{ agent: 'Claude', agentKind: 'claude', resolution: 'haiku → claude-haiku-4-5-20251001' }}
        tools="default"
        toolsNote="no restriction declared"
        skills={[
          { name: 'vendored-scribe', source: './skills/vendored-scribe', ref: 'sha256-db8ee61a90c2' },
          { name: 'remote-herald', source: 'syntropic137/syn-mkt-validation', ref: 'main', href: 'https://github.com/syntropic137/syn-mkt-validation/tree/main' },
        ]}
      />
      <PhaseKit
        eyebrow="Declared on a workflow · restricted tools"
        title="Starter Research › Investigate"
        model={{ agent: 'Claude', agentKind: 'claude', resolution: 'haiku → claude-haiku-4-5-20251001' }}
        tools={['Read', 'Glob', 'Grep', 'Bash', 'WebSearch']}
        skills={[
          {
            name: 'doc-coauthoring',
            source: 'anthropics/skills',
            ref: '3b3fad96af16a10759d930941b4520ba0c40edae',
            href: 'https://github.com/anthropics/skills/tree/3b3fad96af16a10759d930941b4520ba0c40edae',
          },
        ]}
      />
      <PhaseKit
        eyebrow="Declared on a workflow · no skills"
        title="Research Workflow › Discovery Phase"
        model={{ agent: 'Claude', agentKind: 'claude', resolution: 'default → opus → claude-opus-5-5' }}
        tools="default"
        toolsNote="no restriction declared"
        skills="none"
      />
      <PhaseKit
        eyebrow="Pinned when a run starts"
        title="Skills Matrix › Both Kinds"
        model={{ agent: 'Claude', agentKind: 'claude', resolution: 'haiku requested' }}
        tools="default"
        skills={[
          { name: 'vendored-scribe', source: './skills/vendored-scribe', digest: 'sha256:db8ee61a90c2' },
          { name: 'remote-herald', source: 'syntropic137/syn-mkt-validation', ref: 'main', href: 'https://github.com/syntropic137/syn-mkt-validation/tree/main', digest: 'sha256:5f79798ab12c' },
        ]}
        used="not-reported"
      />
      <PhaseKit
        eyebrow="Run older than start pins"
        title="exec-66e14f23 › Discovery Phase"
        model={{ agent: 'Claude', agentKind: 'claude', resolution: 'haiku requested' }}
        tools="not-recorded"
        skills="not-recorded"
        used="not-reported"
      />
      <div class="dev-patterns__card dev-patterns__stack">
        <span class="dev-patterns__label">Skill chip</span>
        <span class="dev-patterns__row-tight">
          <SkillRef variant="chip" name="vendored-scribe" source="./skills/vendored-scribe" />
          <SkillRef variant="chip" name="remote-herald" source="syntropic137/syn-mkt-validation" ref="main" />
        </span>
        <span class="dev-patterns__label">Phase card footer</span>
        <PhaseKitChips model="claude-haiku-4-5" tools={['Read', 'Glob', 'Grep', 'Bash', 'WebSearch']} skills={[{ name: 'doc-coauthoring', source: 'anthropics/skills' }]} />
        <PhaseKitChips tools="default" skills="none" />
        <span class="dev-patterns__label">One line, phone</span>
        <span class="dev-patterns__mono">{phaseKitLine(31_800, 0.017, [{ name: 'a', source: 'a' }, { name: 'b', source: 'b' }])}</span>
      </div>
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-ops">
    <h2 id="p-ops">Operation Timeline and Copy Buttons</h2>
    <div class="dev-patterns__card">
      <div class="dev-patterns__toolbar">
        <span class="dev-patterns__note">{opFilter === 'all' ? '8 tool calls from 16 recorded events, oldest first' : `${shownOps.length} of 9 tool calls shown`}</span>
        <div class="dev-patterns__row-tight" role="group" aria-label="Filter operations">
          {#each [['all', 'All'], ['bash', 'Bash 6'], ['edit', 'Edit 2'], ['errors', 'Errors 2']] as [k, l] (k)}
            <button class="dev-patterns__chip" type="button" aria-pressed={opFilter === k} onclick={() => (opFilter = k as typeof opFilter)}>{l}</button>
          {/each}
          <button class="dev-patterns__chip" type="button" aria-pressed={expandAll} onclick={() => (expandAll = !expandAll)}>Expand all</button>
          <CopyButton variant="label" text={() => operationsToText(shownOps)} label="Copy all" copiedLabel="Copied all" />
        </div>
      </div>
      <OperationTimeline operations={shownOps} expanded={expandAll} previewLines={6} />
    </div>
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-verdicts">
    <h2 id="p-verdicts">Verdict Block and Verdict Board</h2>
    <div class="dev-patterns__row">
      {#each VERDICTS as v (v)}
        <figure class="dev-patterns__figure"><VerdictBlock verdict={v} label={v} /><figcaption>{v}</figcaption></figure>
      {/each}
      <figure class="dev-patterns__figure"><VerdictSparkline verdicts={['pass', 'pass', 'fail', 'pass', 'unscored', 'pass', 'fail', 'pass']} /><figcaption>sparkline</figcaption></figure>
    </div>
    <VerdictBoard
      suite="verifier-seed-v1 · v2"
      description="Does the verifier block a change that carries a known escaped bug, and name the defect and the file it lives in? Six cases, each pinned to the commit before its fix, under four verifiers."
      {cases}
      {verifiers}
      {cells}
      bind:selected={verdictPick}
    />
  </section>

  <section class="dev-patterns__sheet" aria-labelledby="p-rule">
    <h2 id="p-rule">Rule Sentence and Lineage Trail</h2>
    <div class="dev-patterns__card"><RuleSentence clauses={compactRule} /></div>
    <div class="dev-patterns__card dev-patterns__flush"><RuleSentence clauses={fullRule} size="full" /></div>
    <LineageTrail
      steps={[
        { kind: 'Workflow', value: 'research-workflow-v2', href: href('/workflows/research-workflow-v2') },
        { kind: 'Execution', value: 'exec-66e14f23', href: href('/executions/exec-66e14f235942') },
        { kind: 'Session', value: '3ef71a70', href: href('/sessions/3ef71a70') },
      ]}
    />
  </section>

  <!-- Lazy: the landing patterns are a separate chunk, so this route stays inside the first-visit budget. -->
  {#await import('./parts/Landing.svelte') then landing}<landing.default />{/await}
</div>

<style>
  .dev-patterns {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-10);
    box-sizing: border-box;
    width: 100%;
    max-width: var(--sky-page-max);
    margin: 0 auto;
    padding: var(--ds-space-2) var(--sky-gutter) var(--ds-space-16);
  }
  .dev-patterns__intro h1 {
    margin: 0;
    font-size: var(--sky-text-page);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-display);
  }
  .dev-patterns__intro p,
  .dev-patterns__note {
    margin: 0;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .dev-patterns__sheet {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
  }
  .dev-patterns__sheet > h2 {
    margin: 0;
    font-size: var(--ds-text-xl);
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: var(--sky-tracking-title);
  }
  .dev-patterns__hero,
  .dev-patterns__card {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    padding: var(--ds-space-5);
    border-radius: var(--sky-radius-xl);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-surface);
    box-shadow: var(--sky-shadow-raised);
  }
  .dev-patterns__phone {
    width: 100%;
    max-width: 24.375rem;
  }
  .dev-patterns__hero {
    border-radius: var(--sky-radius-2xl);
    background:
      radial-gradient(60% 85% at 62% 108%, color-mix(in oklab, var(--ds-color-accent) 24%, transparent), transparent 72%),
      var(--ds-color-surface);
  }
  .dev-patterns__flush {
    padding: 0;
  }
  .dev-patterns__row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--ds-space-5) var(--ds-space-8);
  }
  .dev-patterns__row-tight {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .dev-patterns__fixed {
    width: min(100%, 15.25rem);
  }
  .dev-patterns__fixed:last-child {
    width: min(100%, 22rem);
  }
  .dev-patterns__figure {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--ds-space-2-5);
    margin: 0;
  }
  .dev-patterns__figure figcaption,
  .dev-patterns__label,
  .dev-patterns__mono {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .dev-patterns__label {
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
  }
  .dev-patterns__mono {
    color: var(--ds-color-text-muted);
  }
  .dev-patterns__list {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  @media (min-width: 48rem) {
    .dev-patterns__list {
      gap: 2px;
    }
  }
  .dev-patterns__split {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-5);
  }
  @media (min-width: 64rem) {
    .dev-patterns__split {
      grid-template-columns: minmax(0, 1fr) var(--sky-side-column);
    }
  }
  .dev-patterns__narrow {
    max-width: 22.375rem;
  }
  .dev-patterns__grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(20rem, 100%), 1fr));
    gap: var(--ds-space-4);
    align-items: start;
  }
  .dev-patterns__stack {
    gap: var(--ds-space-2-5);
  }
  .dev-patterns__phases {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    padding-top: var(--ds-space-3);
    border-top: var(--ds-border-width) solid var(--ds-color-border);
  }
  .dev-patterns__phase {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
  }
  .dev-patterns__phase-name {
    font-weight: var(--ds-font-weight-semibold);
  }
  .dev-patterns__toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
  }
  .dev-patterns__chip {
    height: var(--sky-size-control-sm);
    padding: 0 13px;
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-muted);
    background: transparent;
    color: var(--ds-color-text-muted);
    font-size: var(--sky-text-data);
    cursor: pointer;
  }
  .dev-patterns__chip[aria-pressed='true'] {
    border-color: var(--sky-color-border-hover);
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
  }
  .dev-patterns__primary {
    display: inline-flex;
    align-items: center;
    height: var(--sky-size-control-md);
    padding: 0 var(--ds-space-4);
    border-radius: var(--ds-radius-lg);
    background: var(--sky-color-accent-solid);
    box-shadow: var(--sky-shadow-glow);
    color: var(--sky-color-accent-solid-contrast);
    font-size: var(--ds-text-sm);
    font-weight: var(--ds-font-weight-semibold);
    text-decoration: none;
  }
  .dev-patterns__chip:focus-visible,
  .dev-patterns__primary:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .dev-patterns__chip,
    .dev-patterns__primary {
      min-height: var(--sky-size-touch);
    }
  }
</style>
