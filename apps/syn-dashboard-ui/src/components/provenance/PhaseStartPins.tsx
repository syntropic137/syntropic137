import type { PhaseStartConfig, StartPinsStatus } from '../../types'
import { SkillRefList } from '../SkillRefList'
import './provenance.css'

/**
 * What a phase had when its execution started: model, tools, skills (#1454).
 *
 * Missing pins are never filled in from the workflow as it stands now, and
 * there are two ways to be missing. Only `status: 'not_recorded'` - the server
 * read the start event and it predates #1454 - says "not recorded". Anything
 * else, including a server that does not send a status, is "unavailable": the
 * start event was not read, so what it recorded is unknown. An empty tool list
 * is NOT "no tools": the phase declared no restriction and ran with the
 * harness's default set.
 */
export function PhaseStartPins({
  pins,
  status,
}: {
  pins: PhaseStartConfig | null | undefined
  status: StartPinsStatus | undefined
}) {
  if (pins == null && status !== 'not_recorded') {
    return (
      <p
        className="provenance-pins provenance-muted"
        title="The execution's start event could not be read just now; this says nothing about what it recorded"
      >
        Start config: unavailable
      </p>
    )
  }
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
          <SkillRefList skills={skills} />
        </dd>
        <dt>Skill use</dt>
        {/*
          TODO(#1269): which declared skills the agent actually invoked. The
          execution API does not report it yet (PR #1674 adds `skill_use`);
          once it is in the generated types, render it here by its status.
          Until then this says so, never "not used".
        */}
        <dd>use not recorded yet</dd>
      </dl>
    </details>
  )
}
