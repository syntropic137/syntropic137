import CodeWindow from "../components/CodeWindow";
import HarnessChip from "../components/HarnessChip";
import { SectionIntro } from "../components/PillarHeader";
import UsageBand from "../components/UsageBand";
import WorkflowYaml from "../components/WorkflowYaml";
import { WHAT_IS } from "../data/copy";
import { RECORDED_RUN } from "../data/sample/observability";
import { RUN_COMMAND, RUN_PHASES, WORKFLOW_FILE } from "../data/sample/workflows";
import "./WhatIs.css";

/** Section 2, "What is Syntropic137?": three steps, each with a window (v4 boards). */
export default function WhatIs() {
  const [write, run, compound] = WHAT_IS.steps;
  return (
    <section className="what-is" aria-labelledby="what-is-title">
      <SectionIntro align="center" titleId="what-is-title" eyebrow={WHAT_IS.eyebrow} title={WHAT_IS.title} lede={WHAT_IS.lede} />
      <ol className="what-is__steps">
        <li className="what-is__step">
          <h3>{write.title}</h3>
          <p>{write.body}</p>
          <CodeWindow title={WORKFLOW_FILE} pad="code">
            <WorkflowYaml />
          </CodeWindow>
        </li>
        <li className="what-is__step">
          <h3>{run.title}</h3>
          <p>{run.body}</p>
          <CodeWindow title={RUN_COMMAND}>
            {RUN_PHASES.map((p) => (
              <div key={p.name} className="what-is__phase">
                <span className="what-is__phase-head">
                  <span className="what-is__phase-name">{p.name}</span>
                  <HarnessChip provider={p.provider} label={p.model} />
                </span>
                <span className="what-is__phase-meta">
                  <span>{p.container}</span>
                  <span>{p.status}</span>
                </span>
                <span className="what-is__progress" role="img" aria-label={`${p.progress}% done`}>
                  <span style={{ width: `${p.progress}%` }} />
                </span>
              </div>
            ))}
          </CodeWindow>
        </li>
        <li className="what-is__step">
          <h3>{compound.title}</h3>
          <p>{compound.body}</p>
          <CodeWindow title={RECORDED_RUN.host}>
            <div className="what-is__cost">
              <span className="what-is__cost-value">{RECORDED_RUN.cost}</span>
              <span className="what-is__cost-detail">{RECORDED_RUN.detail}</span>
            </div>
            <UsageBand tokens={RECORDED_RUN.tokens} size="sm" />
            <div className="what-is__score">
              <span>{WHAT_IS.scoreLabel}</span>
              <span className="what-is__score-value">
                {RECORDED_RUN.score}
                <span>/{RECORDED_RUN.scoreMax}</span>
              </span>
            </div>
            <span className="what-is__verdict">{RECORDED_RUN.verdict}</span>
          </CodeWindow>
        </li>
      </ol>
    </section>
  );
}
