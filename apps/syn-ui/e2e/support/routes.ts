/**
 * Every route under test, as data. Specs loop over this table, so adding a
 * screen is one entry here.
 *
 * Headings accept both apps' wording (Skyline "Overview", React "Dashboard").
 * `fixtureText` and `fixtureHeading` are values from
 * packages/syn-ui/data/src/fixtures (catalog.ts and friends) and only apply
 * when E2E_DATA=fixtures.
 */

export type IdKind = 'workflow' | 'execution' | 'eval' | 'session' | 'artifact' | 'trigger'

/**
 * Stable fixture IDs (fakeId() is deterministic): RUNS[2] is the completed
 * Research Workflow run; its first phase owns the session and artifact.
 */
export const FIXTURE_IDS: Record<IdKind, string> = {
  workflow: 'research-workflow',
  execution: '90add202f4da',
  eval: 'eval-shared-esp-stream-1',
  session: '5c7b25772d23',
  artifact: '9520cefb0f9d',
  trigger: 'tr-a17e40c1',
}

/** Href shape of a detail link on a list page, used to discover live IDs. */
export const DETAIL_LINK: Record<IdKind, RegExp> = {
  workflow: /\/workflows\/([^/?#]+)$/,
  execution: /\/executions\/([^/?#]+)$/,
  eval: /\/evals\/([^/?#]+)$/,
  session: /\/sessions\/([^/?#]+)$/,
  artifact: /\/artifacts\/([^/?#]+)$/,
  trigger: /\/triggers\/([^/?#]+)$/,
}

export interface CrumbExpectation {
  /** Link text of a parent crumb (anchored regex, so apps may differ). */
  label: RegExp
  /** App path that crumb links to (matched at the end of the href). */
  href: RegExp
}

const crumb = (label: string, href: string): CrumbExpectation => ({ label: new RegExp(`^${label}$`), href: new RegExp(`${href}$`) })

export interface RouteCase {
  name: string
  /** App path; `:id` is replaced with the resolved ID. */
  path: string
  /** Which ID `:id` stands for. */
  id?: IdKind
  /** List page to discover the ID from (live data) and to start navigation tests on. */
  listPath?: string
  /** Primary nav label that owns this route. */
  nav: string
  heading: RegExp
  /** Document title (Skyline only; React keeps one title for every page). */
  title?: RegExp
  /** Stricter heading on fixtures. */
  fixtureHeading?: RegExp
  /** Text that must appear on fixtures. */
  fixtureText: (string | RegExp)[]
  /** Breadcrumb parents on desktop; [] means no trail (Overview). */
  crumbs: CrumbExpectation[]
  /** The current crumb (Skyline renders it with aria-current="page"). */
  current?: RegExp
}

export const ROUTES: RouteCase[] = [
  {
    name: 'overview',
    path: '/',
    nav: 'Overview',
    // Skyline's Overview heading is a status line ("All quiet."), not the page name.
    heading: /\S/,
    title: /Overview/,
    fixtureText: ['Research Workflow'],
    crumbs: [],
  },
  {
    name: 'workflows list',
    path: '/workflows',
    nav: 'Workflows',
    heading: /Workflow/i,
    fixtureText: ['Research Workflow', 'Skills Matrix', 'PR Review'],
    crumbs: [],
    current: /Workflows/,
  },
  {
    name: 'workflow detail',
    path: '/workflows/:id',
    id: 'workflow',
    listPath: '/workflows',
    nav: 'Workflows',
    heading: /\S/,
    fixtureHeading: /Research Workflow/,
    fixtureText: ['Research', 'Synthesize', 'Report'],
    crumbs: [crumb('Workflows', '/workflows')],
  },
  {
    name: 'workflow runs',
    path: '/workflows/:id/runs',
    id: 'workflow',
    listPath: '/workflows',
    nav: 'Workflows',
    heading: /Runs|Research Workflow|Execution/i,
    fixtureText: [/Completed/i],
    crumbs: [crumb('Workflows', '/workflows')],
    current: /Runs/,
  },
  {
    name: 'executions list',
    path: '/executions',
    nav: 'Executions',
    heading: /Executions/i,
    fixtureText: ['Research Workflow', 'PR Review', /Failed/i],
    crumbs: [],
    current: /Executions/,
  },
  {
    name: 'execution detail',
    path: '/executions/:id',
    id: 'execution',
    listPath: '/executions',
    nav: 'Executions',
    heading: /\S/,
    fixtureHeading: /Research Workflow|Execution|one sentence on sorting/,
    fixtureText: ['Research', 'Synthesis', 'Report'],
    // Skyline may file a run under its workflow (CONVENTIONS example); React files it under Executions.
    crumbs: [{ label: /^(Executions|Workflows)$/, href: /\/(executions|workflows)$/ }],
  },
  {
    name: 'evals list',
    path: '/evals',
    nav: 'Evals',
    heading: /Evals/i,
    fixtureText: ['shared-esp-stream', 'codex-cost-limit'],
    crumbs: [],
    current: /Evals/,
  },
  {
    name: 'eval detail',
    path: '/evals/:id',
    id: 'eval',
    listPath: '/evals',
    nav: 'Evals',
    heading: /\S/,
    fixtureHeading: /shared-esp-stream/,
    fixtureText: ['claude-opus-5-5'],
    crumbs: [crumb('Evals', '/evals')],
  },
  {
    name: 'sessions list',
    path: '/sessions',
    nav: 'Sessions',
    heading: /Sessions/i,
    fixtureText: ['Research Workflow', 'claude-sonnet-4-5'],
    crumbs: [],
    current: /Sessions/,
  },
  {
    name: 'session detail',
    path: '/sessions/:id',
    id: 'session',
    listPath: '/sessions',
    nav: 'Sessions',
    heading: /\S/,
    fixtureText: ['claude-sonnet-4-5', 'Research'],
    // React files a session under its workflow and execution; Skyline may do the same.
    crumbs: [{ label: /^(Sessions|Execution)\b/, href: /\/(sessions|executions\/[^/]+)$/ }],
  },
  {
    name: 'artifacts list',
    path: '/artifacts',
    nav: 'Artifacts',
    heading: /Artifacts/i,
    fixtureText: ['deliverable.md', 'report.md'],
    crumbs: [],
    current: /Artifacts/,
  },
  {
    name: 'artifact detail',
    path: '/artifacts/:id',
    id: 'artifact',
    listPath: '/artifacts',
    nav: 'Artifacts',
    heading: /\S/,
    fixtureHeading: /\.md$/,
    fixtureText: ['Findings'],
    crumbs: [crumb('Artifacts', '/artifacts')],
  },
  {
    name: 'triggers list',
    path: '/triggers',
    nav: 'Triggers',
    heading: /Triggers/i,
    fixtureText: ['check_run.completed', 'PR Review'],
    crumbs: [],
    current: /Triggers/,
  },
  {
    name: 'trigger detail',
    path: '/triggers/:id',
    id: 'trigger',
    listPath: '/triggers',
    nav: 'Triggers',
    heading: /\S/,
    fixtureHeading: /Triggers|Review requested changes/,
    fixtureText: ['pull_request_review.submitted', 'PR Review'],
    crumbs: [crumb('Triggers', '/triggers')],
  },
  {
    name: 'repos',
    path: '/repos',
    nav: 'Repos',
    heading: /Repos/i,
    fixtureText: [/syntropic137/],
    crumbs: [],
    current: /Repos/,
  },
]

/** The eight primary sections and the label each app gives them. */
export const SECTIONS: { path: string; label: RegExp; heading: RegExp }[] = [
  { path: '/', label: /^(Overview|Dashboard)$/, heading: /\S/ },
  { path: '/workflows', label: /^Workflows$/, heading: /Workflow/i },
  { path: '/executions', label: /^Executions$/, heading: /Executions/i },
  { path: '/evals', label: /^Evals$/, heading: /Evals/i },
  { path: '/sessions', label: /^Sessions$/, heading: /Sessions/i },
  { path: '/artifacts', label: /^Artifacts$/, heading: /Artifacts/i },
  { path: '/triggers', label: /^Triggers$/, heading: /Triggers/i },
  { path: '/repos', label: /^Repos$/, heading: /Repos/i },
]

/** Phone dock slots (spec, Platforms) and what sits behind More. */
export const DOCK = ['Overview', 'Executions', 'Evals', 'Workflows'] as const
export const MORE = ['Sessions', 'Artifacts', 'Triggers', 'Repos'] as const
