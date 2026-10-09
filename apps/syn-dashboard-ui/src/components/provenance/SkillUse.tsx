import { AlertTriangle } from 'lucide-react'

import type { ExecutionSkillUse, PhaseSkillUse } from '../../types'
import './provenance.css'

/**
 * Which declared skills an execution's agents actually invoked (#1269,
 * feedback 01308bcf).
 *
 * Every sentence comes from the server's `*_display` fields, which already
 * refuse the #1269 misreading: a phase whose use cannot be seen (codex has no
 * Skill tool) or was not recorded never reads as "0 used". So the lists below
 * are drawn only where the server says they are measurements - `invoked` and
 * `declared_not_invoked` on an `observed` phase - and nowhere else.
 */

/**
 * A server that predates `skill_use` sends no key at all. That is the same
 * answer the server gives a run it holds no record for, worded as it words it.
 */
const NO_RECORD = 'skill use unavailable: no record for this run'

function Names({ names }: { names: string[] }) {
  return (
    <ul className="skill-use__names">
      {names.map((n) => (
        <li key={n}>
          <code>{n}</code>
        </li>
      ))}
    </ul>
  )
}

function Invoked({ invoked }: { invoked: { name: string; count: number }[] }) {
  return (
    <ul className="skill-use__names">
      {invoked.map((s) => (
        <li key={s.name}>
          <code>{s.name}</code> &times;{s.count}
        </li>
      ))}
    </ul>
  )
}

/** One phase: what it declared, what it invoked, and what that status means. */
export function SkillUseLine({ use }: { use: PhaseSkillUse | undefined }) {
  if (use === undefined) {
    return <p className="skill-use provenance-muted" data-status="unavailable">{NO_RECORD}</p>
  }
  const declared = use.declared ?? []
  const invoked = use.invoked ?? []
  const missed = use.declared_not_invoked
  const observed = use.status === 'observed'
  return (
    <details className="skill-use" data-status={use.status}>
      <summary className={missed.length > 0 ? 'skill-use--warn' : undefined}>
        {missed.length > 0 && <AlertTriangle className="skill-use__icon" aria-hidden="true" />}
        {use.summary_display}
      </summary>
      <dl className="provenance-pins__list">
        <dt>Skill use</dt>
        <dd>{use.status_display}</dd>
        <dt>Declared</dt>
        <dd>{declared.length === 0 ? 'none' : <Names names={declared} />}</dd>
        {observed && (
          <>
            <dt>Invoked</dt>
            <dd>{invoked.length === 0 ? 'none' : <Invoked invoked={invoked} />}</dd>
          </>
        )}
        {missed.length > 0 && (
          <>
            <dt className="skill-use--warn">Not invoked</dt>
            <dd className="skill-use--warn" data-testid="skill-use-not-invoked">
              <Names names={missed} />
            </dd>
          </>
        )}
      </dl>
    </details>
  )
}

/** The whole execution: every declared skill, and which were used anywhere. */
export function SkillUseOverview({ use }: { use: ExecutionSkillUse | undefined }) {
  if (use === undefined) {
    return (
      <section className="provenance-card skill-use-overview" aria-label="Skill use">
        <h2 className="provenance-card__title">Skills</h2>
        <p className="provenance-muted">{NO_RECORD}</p>
      </section>
    )
  }
  const declared = use.declared ?? []
  const invoked = use.invoked ?? []
  const never = use.never_invoked ?? []
  const unknown = use.not_known ?? []
  return (
    <section className="provenance-card skill-use-overview" aria-label="Skill use">
      <h2 className="provenance-card__title">Skills</h2>
      <p className="skill-use-overview__summary">{use.summary_display}</p>
      <dl className="provenance-pins__list">
        <dt>Declared</dt>
        <dd data-testid="skill-use-declared">
          {declared.length === 0 ? 'none' : <Names names={declared} />}
        </dd>
        {invoked.length > 0 && (
          <>
            <dt>Invoked</dt>
            <dd>
              <Invoked invoked={invoked} />
            </dd>
          </>
        )}
        {never.length > 0 && (
          <>
            <dt className="skill-use--warn">Never invoked</dt>
            <dd className="skill-use--warn" data-testid="skill-use-never-invoked">
              <Names names={never} />
            </dd>
          </>
        )}
        {unknown.length > 0 && (
          <>
            <dt>Use unknown</dt>
            <dd title="Declared on a phase whose skill use cannot be observed or was not recorded">
              <Names names={unknown} />
            </dd>
          </>
        )}
      </dl>
    </section>
  )
}
