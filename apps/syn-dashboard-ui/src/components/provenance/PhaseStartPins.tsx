import type { PhaseStartConfig } from '../../types'
import './provenance.css'

/**
 * What a phase had when its execution started: model, tools, skills (#1454).
 *
 * `null` is "not recorded" - a run from before #1454 - and is never filled in
 * from the workflow as it stands now. An empty tool list is NOT "no tools":
 * the phase declared no restriction and ran with the harness's default set.
 */
export function PhaseStartPins({ pins }: { pins: PhaseStartConfig | null | undefined }) {
  if (pins == null) {
    return (
      <p
        className="provenance-pins provenance-muted"
        title="This execution started before phase configuration was pinned at start (#1454)"
      >
        Start config: not recorded
      </p>
    )
  }
  const tools = pins.allowed_tools ?? []
  const skills = pins.skills ?? []
  return (
    <details className="provenance-pins">
      <summary>
        At start: {pins.requested_model ?? `${pins.provider} default model`} &middot;{' '}
        {tools.length === 0 ? 'default tools' : `${tools.length} tools`} &middot; {skills.length}{' '}
        {skills.length === 1 ? 'skill' : 'skills'}
      </summary>
      <dl className="provenance-pins__list">
        <dt>Requested model</dt>
        <dd>{pins.requested_model ?? `none named (${pins.provider} default)`}</dd>
        <dt>Tools</dt>
        <dd>
          {tools.length === 0 ? (
            'no restriction declared (harness default)'
          ) : (
            <ul>
              {tools.map((t) => (
                <li key={t}>
                  <code>{t}</code>
                </li>
              ))}
            </ul>
          )}
        </dd>
        <dt>Skills</dt>
        <dd>
          {skills.length === 0 ? (
            'none'
          ) : (
            <ul>
              {skills.map((s) => (
                <li key={`${s.name}@${s.resolved_sha}`} title={`${s.source_url} @ ${s.resolved_sha}`}>
                  <code>{s.name}</code> <span className="provenance-muted">{s.version}</span>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
    </details>
  )
}
