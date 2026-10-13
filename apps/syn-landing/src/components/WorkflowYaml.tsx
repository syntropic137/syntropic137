import { HARNESSES } from "../data/harnesses";
import { WORKFLOW_YAML, type YamlLine } from "../data/sample/workflows";
import "./WorkflowYaml.css";

const colour = (id: string) => HARNESSES.find((h) => h.id === id)?.color;

function Line({ l, last }: { l: YamlLine; last: boolean }) {
  const pad = "  ".repeat(l.indent - (l.dash ? 1 : 0)) + (l.dash ? "  - " : "");
  return (
    <>
      {pad}
      <span className="yaml-key">{l.key}:</span>
      {l.value !== undefined && ` ${l.value}`}
      {l.agent && (
        <>
          {" { "}
          <span className="yaml-key">provider:</span>{" "}
          <span style={{ color: colour(l.agent.provider) }}>{l.agent.provider}</span>
          {", "}
          <span className="yaml-key">model:</span> {l.agent.model}
          {" }"}
        </>
      )}
      {last ? null : "\n"}
    </>
  );
}

/** The sample workflow file (src/data/sample/workflows.ts), keys dimmed, providers in their harness colour. */
export default function WorkflowYaml() {
  return (
    <pre className="workflow-yaml">
      <code>
        {WORKFLOW_YAML.map((l, i) => (
          <Line key={i} l={l} last={i === WORKFLOW_YAML.length - 1} />
        ))}
      </code>
    </pre>
  );
}
