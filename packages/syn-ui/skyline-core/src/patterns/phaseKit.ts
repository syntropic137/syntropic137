/**
 * Phase Kit and Skill Ref (PhaseKit board): what a phase gets (model, tools,
 * skills), declared on a workflow or pinned when a run starts.
 */
import { formatCostPrecise } from '../format/cost'
import { formatTokens } from '../format/tokens'

export interface SkillRefProps {
  name: string
  /** "./skills/vendored-scribe" or "syntropic137/syn-mkt-validation". */
  source: string
  /** Ref shown after "@" as declared: "main", a commit sha, or a vendored digest "sha256-db8ee61…". */
  ref?: string | null
  /** Link to the source at that ref. */
  href?: string | null
  /** Content digest once pinned at run start: "sha256:db8ee61…". */
  digest?: string | null
}

export interface SkillRefDisplay {
  name: string
  source: string
  /** Short ref: a 40-char sha becomes 7 chars, a branch stays. */
  ref: string | null
  href: string | null
  /** "sha256:db8ee61" (7 hex digits), or null when not pinned. */
  digest: string | null
  /** "Source of remote-herald at main". */
  linkLabel: string | null
  /** Hover text: the URL it opens, or why there is no link ("Vendored in the workflow package: no public source"). */
  title: string
}

export interface SkillSource {
  href: string | null
  /** Why `href` is null; null when there is a link. */
  reason: string | null
}

const GITHUB_URL = /^(?:https?:\/\/)?(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/i
const GITHUB_SHORT = /^([\w.-]+)\/([\w.-]+)(?:\/([\w.-]+))?$/

/**
 * Link to a skill's SKILL.md at its pinned ref (feedback 28e8baea).
 * The API carries source repo, name and version but no path, so the path
 * follows the skills repo convention the CLI resolves second
 * (skill-tree.ts: `<name>/`, `skills/<name>/`, root): `skills/<name>`,
 * or the repo root when the name is the repo (a single-skill repo).
 */
export function skillSourceHref(s: { name: string; source: string; ref?: string | null }): SkillSource {
  const src = s.source.trim()
  if (src.startsWith('.') || src.startsWith('/')) return { href: null, reason: 'Vendored in the workflow package: no public source to link' }
  const m = GITHUB_URL.exec(src) ?? GITHUB_SHORT.exec(src)
  if (!m) return { href: null, reason: 'Source is not a GitHub repository' }
  if (!s.ref) return { href: null, reason: 'No pinned version: the link would not show the skill this phase runs' }
  const [, owner, repo, folder] = m
  const name = folder ?? s.name
  const path = name && name !== repo ? `skills/${name}/SKILL.md` : 'SKILL.md'
  return { href: `https://github.com/${owner}/${repo}/blob/${encodeURIComponent(s.ref)}/${path}`, reason: null }
}

const HEX = /^[0-9a-f]{12,}$/i

/** Shorten a digest or sha for display, keeping its algorithm prefix: "sha256:db8ee61…" -> "sha256:db8ee61". */
export function shortDigest(value: string | null | undefined, length = 7): string | null {
  if (!value) return null
  const m = /^([a-z0-9]+)([:-])([0-9a-f]+)$/i.exec(value)
  if (m) return `${m[1]}${m[2]}${m[3]!.slice(0, length)}`
  return HEX.test(value) ? value.slice(0, length) : value
}

export function skillRefDisplay(s: SkillRefProps): SkillRefDisplay {
  const ref = shortDigest(s.ref ?? null)
  const derived = s.href ? { href: s.href, reason: null } : skillSourceHref(s)
  return {
    name: s.name,
    source: s.source,
    ref,
    href: derived.href,
    digest: shortDigest(s.digest ?? null),
    linkLabel: derived.href ? `Source of ${s.name}${ref ? ` at ${ref}` : ''}` : null,
    title: derived.href ?? `${s.source}${ref ? `@${ref}` : ''}: ${derived.reason ?? 'no link'}`,
  }
}

export type AgentKind = 'claude' | 'codex' | 'other'

export interface PhaseKitModel {
  agent: string
  agentKind?: AgentKind
  /** "haiku → claude-haiku-4-5-20251001", "haiku requested". */
  resolution?: string
}

/**
 * A kit value is either known, or one of the stated absences. Each absence
 * reads differently on the board, so they stay distinct:
 * - 'default': nothing restricted (tools) - "Harness default"
 * - 'none': declared empty (skills) - "None declared"
 * - 'not-recorded': run older than start pins - "Not recorded"
 * - 'not-reported': the harness does not report it yet - "Not reported yet"
 */
export type KitAbsence = 'default' | 'none' | 'not-recorded' | 'not-reported'

export interface PhaseKitProps {
  /** "Declared on a workflow · two skills", "Pinned when a run starts". */
  eyebrow?: string
  /** "Skills Matrix › Both Kinds". */
  title?: string
  model?: PhaseKitModel | 'not-recorded'
  tools: readonly string[] | KitAbsence
  /** Shown beside "Harness default": "no restriction declared". */
  toolsNote?: string
  skills: readonly SkillRefProps[] | KitAbsence
  /** Which skills the agent actually used; omitted rows are not drawn. */
  used?: readonly string[] | KitAbsence
}

export const ABSENCE_TEXT: Record<KitAbsence, string> = {
  default: 'Harness default',
  none: 'None declared',
  'not-recorded': 'Not recorded',
  'not-reported': 'Not reported yet',
}

export type KitChipTone = 'neutral' | 'accent' | 'dashed'

export interface KitChip {
  label: string
  tone: KitChipTone
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** Phase card footer chips: "claude-haiku-4-5", "5 tools", "1 skill" or "no skills". */
export function phaseKitChips(kit: Pick<PhaseKitProps, 'tools' | 'skills'> & { model?: string | null }): KitChip[] {
  const chips: KitChip[] = []
  if (kit.model) chips.push({ label: kit.model, tone: 'neutral' })
  const tools = toolsChip(kit.tools)
  if (tools) chips.push(tools)
  const skills = skillsChip(kit.skills)
  if (skills) chips.push(skills)
  return chips
}

function toolsChip(tools: PhaseKitProps['tools']): KitChip | null {
  if (Array.isArray(tools)) return { label: plural(tools.length, 'tool', 'tools'), tone: 'neutral' }
  return tools === 'not-recorded' ? { label: 'tools not recorded', tone: 'dashed' } : null
}

const SKILL_ABSENCE_CHIP: Partial<Record<KitAbsence, KitChip>> = {
  none: { label: 'no skills', tone: 'dashed' },
  'not-recorded': { label: 'skills not recorded', tone: 'dashed' },
}

function skillsChip(skills: PhaseKitProps['skills']): KitChip | null {
  if (typeof skills === 'string') {
    const chip = SKILL_ABSENCE_CHIP[skills]
    return chip ? { ...chip } : null
  }
  return skills.length ? { label: plural(skills.length, 'skill', 'skills'), tone: 'accent' } : { label: 'no skills', tone: 'dashed' }
}

/** One line on a phone: "31.8K tok · $0.0170 · 2 skills". */
export function phaseKitLine(tokens: number | null | undefined, costUsd: number | null | undefined, skills: PhaseKitProps['skills']): string {
  const parts = [`${formatTokens(tokens ?? null, { case: 'upper' })} tok`, formatCostPrecise(costUsd ?? null)]
  if (Array.isArray(skills)) parts.push(skills.length ? plural(skills.length, 'skill', 'skills') : 'no skills')
  else if (skills === 'none') parts.push('no skills')
  return parts.join(' · ')
}
