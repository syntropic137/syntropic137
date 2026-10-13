/**
 * Workflow-definition detail for fixtures (Workflows and Workflow boards):
 * phase descriptions, prompts, tools, timeouts and declared skills, plus
 * the board's never-run definitions so the list shows its full 27.
 * Owned by the Workflows screen. Runs stay in catalog.ts.
 */
import type { CatalogPhase, CatalogWorkflow } from './catalog'

export interface FixtureSkill {
  name: string
  source: string
  ref: string | null
}

export interface PhaseDetail {
  description?: string
  prompt?: string
  tools?: string[]
  timeout?: number
  modelDisplay?: string
  skills?: FixtureSkill[]
}

const claude = (id: string, name: string, model = 'claude-sonnet-4-5'): CatalogPhase => ({ id, name, model, provider: 'claude' })
const codex = (id: string, name: string, model = 'gpt-5-codex'): CatalogPhase => ({ id, name, model, provider: 'codex' })
const wf = (id: string, name: string, type: string, description: string, phases: CatalogPhase[]): CatalogWorkflow => ({ id, name, type, description, phases })

const DISCOVERY_PROMPT = `You are a research assistant conducting initial exploration and scoping.

## Your Task
$ARGUMENTS

## How to Approach This
- Identify key areas of interest related to this topic
- Gather relevant context from the codebase or available sources
- Define 3-5 research questions to guide deeper investigation
- Note any assumptions or constraints

Output a structured research scope with your initial questions.`

const skill = (name: string, source: string, ref: string | null = 'main'): FixtureSkill => ({ name, source, ref })

/** Keyed `${workflowId}/${phaseId}`. */
export const PHASE_DETAILS: Record<string, PhaseDetail> = {
  'research-workflow/research': {
    description: 'Initial exploration and scoping. Identify key areas of interest, gather context, and define research questions.',
    prompt: DISCOVERY_PROMPT,
    timeout: 300,
    modelDisplay: 'default → opus → claude-opus-5-5',
  },
  'research-workflow/synthesize': {
    description: 'In-depth investigation of identified areas. Analyze code patterns, documentation, and dependencies.',
    prompt: `You are a research analyst doing a deep dive.\n\n## Your Task\n$ARGUMENTS\n\n## How to Approach This\n- Answer each research question from the discovery phase\n- Cite files and line numbers for every claim\n- Flag contradictions between sources\n\nOutput findings grouped by question.`,
    timeout: 600,
    modelDisplay: 'default → opus → claude-opus-5-5',
  },
  'research-workflow/report': {
    description: 'Consolidate findings into actionable documentation. Produce recommendations and next steps.',
    prompt: `You are a technical writer consolidating research.\n\n## Your Task\n$ARGUMENTS\n\n## How to Approach This\n- Summarise the findings in one page\n- List recommendations in priority order\n- Close with open questions\n\nWrite deliverable.md.`,
    timeout: 300,
    modelDisplay: 'default → opus → claude-opus-5-5',
  },
  'skills-matrix/inventory': { description: 'List every declared skill and where it came from.', tools: ['Read', 'Glob'], skills: [skill('vendored-scribe', './skills/vendored-scribe', 'sha256-db8ee61a90c2')] },
  'skills-matrix/probe': {
    description: 'Invoke each skill once with a marker input.',
    tools: ['Read', 'Bash', 'Skill'],
    skills: [skill('vendored-scribe', './skills/vendored-scribe', 'sha256-db8ee61a90c2'), skill('remote-herald', 'syntropic137/remote-herald')],
  },
  'skills-matrix/verify': { description: 'Check each marker came back from the right skill.', tools: ['Read', 'Grep'] },
  'skills-matrix/summarize': { description: 'Write the matrix of skill, loaded, invoked.', tools: ['Write'] },
  'skill-probe/setup': { description: 'Prepare the workspace for the probe.', tools: ['Bash'], skills: [skill('alpha-marker', './skills/alpha-marker')] },
  'skill-probe/probe': { description: 'Call each pinned skill.', skills: [skill('beta-marker', './skills/beta-marker'), skill('gamma-marker', './skills/gamma-marker')] },
  'starter-research/research': { description: 'Research the task with the co-authoring skill.', skills: [skill('doc-coauthoring', 'anthropics/skills/doc-coauthoring')] },
  'starter-pr-review/review': {
    description: 'Review the diff against the repo conventions.',
    tools: ['Read', 'Grep', 'Bash'],
    skills: [skill('repo-conventions', './skills/repo-conventions')],
  },
  'pr-review/review': { description: 'Read the diff and write findings ranked by severity.', tools: ['Read', 'Grep', 'Bash'] },
  'multi-agent/plan': { description: 'Claude writes the implementation plan.', modelDisplay: 'opus → claude-opus-4-1' },
  'multi-agent/implement': { description: 'Codex implements the plan.', modelDisplay: 'gpt-codex → gpt-5-codex' },
}

/** Definitions on the Workflows board that have never run. */
export const EXTRA_WORKFLOWS: CatalogWorkflow[] = [
  wf('ci-fix-workflow', 'CI Failure Self-Healing', 'implementation', 'Reads a failing check and pushes a fix.', [claude('fix', 'Fix')]),
  wf('code-review', 'Code Review', 'review', 'Two-pass review of a change.', [claude('read', 'Read'), claude('review', 'Review')]),
  wf('fix-review-workflow', 'Fix Review Comments', 'implementation', 'Addresses review comments on a PR.', [claude('fix', 'Fix')]),
  wf('github-pr-workflow', 'GitHub PR Workflow', 'implementation', 'Implements a change and opens a PR.', [claude('implement', 'Implement'), claude('open-pr', 'Open PR')]),
  wf('implementation-workflow-v1', 'Implementation Workflow', 'implementation', 'Plan, implement, test, review and ship a change.', [
    claude('plan', 'Plan'),
    claude('implement', 'Implement'),
    claude('test', 'Test'),
    claude('review', 'Review'),
    claude('ship', 'Ship'),
  ]),
  wf('multi-agent-claude-then-codex-v2', 'Multi-agent shared workspace (claude writes / codex reads)', 'research', 'Claude writes a file; Codex reads it back.', [claude('write', 'Write'), codex('read', 'Read')]),
  wf('multi-agent-markers', 'Multi-agent shared workspace (claude marker → codex marker)', 'research', 'Each agent leaves a marker for the other.', [claude('mark', 'Mark'), codex('check', 'Check')]),
  wf('reply-ok-interactive', 'Reply OK (interactive-tmux)', 'research', 'Smoke test for the interactive harness.', [claude('reply', 'Reply')]),
  wf('research-with-prompts-v1', 'Research with Prompt Files', 'research', 'Research driven by prompt files in the repo.', [claude('research', 'Research'), claude('report', 'Report')]),
  wf('sdlc-ci-fix', 'CI Self-Healing', 'implementation', 'Diagnose, fix and verify a red build.', [claude('diagnose', 'Diagnose'), claude('fix', 'Fix'), claude('verify', 'Verify')]),
  wf('sdlc-release-prep', 'Release Preparation', 'deployment', 'Changelog, version bump and release notes.', [claude('changelog', 'Changelog'), claude('bump', 'Bump'), claude('notes', 'Notes')]),
  wf('self-heal-pr', 'Self-Heal PR', 'implementation', 'Fixes its own PR until checks pass.', [claude('heal', 'Heal')]),
  wf('skills-invocation-v1', 'Skills Invocation', 'research', 'Calls one skill and records the result.', [claude('invoke', 'Invoke'), claude('report', 'Report')]),
  wf('skillproof-research-v1', 'Starter Research', 'research', 'A two-phase research starter, skill-proofed.', [claude('research', 'Research'), claude('report', 'Report')]),
  wf('skillproof-pr-review-v1', 'Starter PR Review', 'review', 'A two-phase PR review starter, skill-proofed.', [claude('review', 'Review'), claude('comment', 'Comment')]),
  wf('write-then-read-headless', 'Multi-agent shared workspace (claude writes / codex reads)', 'research', 'Headless variant of the shared-workspace demo.', [claude('write', 'Write'), codex('read', 'Read')]),
]

Object.assign(PHASE_DETAILS, {
  'skills-invocation-v1/invoke': { skills: [skill('furlong-converter', './skills/furlong-converter')] },
  'skillproof-research-v1/research': { skills: [skill('doc-coauthoring', 'anthropics/skills/doc-coauthoring')] },
  'skillproof-pr-review-v1/review': { skills: [skill('repo-conventions', './skills/repo-conventions')] },
} satisfies Record<string, PhaseDetail>)
