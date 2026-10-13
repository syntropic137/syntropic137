import CodeWindow, { LiveDot, Tile } from "../components/CodeWindow";
import { Pillar } from "../components/PillarHeader";
import WorkflowYaml from "../components/WorkflowYaml";
import { WORKFLOWS } from "../data/copy";
import { TRIGGER, WORKFLOW_FILE } from "../data/sample/workflows";
import "./Workflows.css";

/** Section 3, "01 Repeatable workflows" (#workflows): the YAML, ways to start it, and a trigger rule. */
export default function Workflows() {
  return (
    <Pillar
      id="workflows"
      label={WORKFLOWS.eyebrow}
      tinted
      num={WORKFLOWS.num}
      eyebrow={WORKFLOWS.eyebrow}
      title={WORKFLOWS.title}
      lede={WORKFLOWS.lede}
      points={WORKFLOWS.points}
      visual={
        <div className="workflows__visual">
          <CodeWindow title={WORKFLOW_FILE} pad="code">
            <WorkflowYaml />
          </CodeWindow>
          <div className="workflows__starts">
            {WORKFLOWS.startFrom.map((s) => (
              <Tile key={s.label} label={s.label}>
                <code>{s.code}</code>
              </Tile>
            ))}
          </div>
          <CodeWindow>
            <span className="panel-meta">
              <LiveDot />
              {TRIGGER.meta}
            </span>
            <p className="workflows__rule">
              {TRIGGER.rule.map((part, i) => (
                <span key={i}>
                  {"word" in part && <span className="workflows__rule-word">{part.word}</span>}
                  {"workflow" in part && <span className="workflows__rule-name">{part.workflow}</span>}
                  {part.text}
                </span>
              ))}
            </p>
          </CodeWindow>
        </div>
      }
    />
  );
}
