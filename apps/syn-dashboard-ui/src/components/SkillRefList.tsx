/**
 * A list of skills: name, source repo, version, and a link to the source at
 * that version (#772, #1454).
 *
 * One component for both the skills a workflow DECLARES and the skills an
 * execution was PINNED to at start, so the two pages cannot drift into
 * describing the same skill differently. A pinned skill carries the SHA its
 * version resolved to, and that SHA is what is shown and linked: the version
 * may be a tag that has moved since.
 */

import { ExternalLink } from 'lucide-react'

import { shortRef, sourceRepoLabel, sourceUrlAtRef } from '../utils/skillRefs'

/** Structurally both `PhaseRefResponse` (declared) and `PinnedSkillInfo` (pinned). */
export interface SkillRefLike {
  name?: string | null
  source_url?: string | null
  version?: string | null
  /** Pinned skills only: the commit `version` resolved to at start. */
  resolved_sha?: string
  /** Declared skills only: the shorthand as written, e.g. a local `./skills/x`. */
  raw?: string | null
}

function SkillRefItem({ skill }: { skill: SkillRefLike }) {
  const name = skill.name ?? skill.raw ?? 'unnamed skill'
  const ref = skill.resolved_sha ?? skill.version ?? null
  const href = skill.source_url && ref ? sourceUrlAtRef(skill.source_url, ref) : null
  return (
    <li className="flex flex-col" data-testid="skill-ref">
      <code className="text-[var(--color-text-primary)]">{name}</code>
      {skill.source_url ? (
        <span className="flex flex-wrap items-center gap-1 text-[var(--color-text-muted)]" title={`${skill.source_url}${ref ? ` @ ${ref}` : ''}`}>
          {sourceRepoLabel(skill.source_url)}
          {ref && <> @ <code>{shortRef(ref)}</code></>}
          {skill.resolved_sha && skill.version && skill.version !== skill.resolved_sha && (
            <> ({skill.version})</>
          )}
          {href && (
            <a
              className="text-[var(--color-accent)] hover:underline"
              href={href}
              target="_blank"
              rel="noreferrer"
              aria-label={`Source of ${name} at ${shortRef(ref ?? '')}`}
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </span>
      ) : (
        <span className="text-[var(--color-text-muted)]">local to the workflow</span>
      )}
    </li>
  )
}

export function SkillRefList({ skills }: { skills: readonly SkillRefLike[] }) {
  if (skills.length === 0) return <span className="text-[var(--color-text-muted)]">none</span>
  return (
    <ul className="flex flex-col gap-1">
      {skills.map((s, i) => (
        <SkillRefItem key={`${s.source_url ?? ''}|${s.name ?? s.raw ?? ''}|${i}`} skill={s} />
      ))}
    </ul>
  )
}
