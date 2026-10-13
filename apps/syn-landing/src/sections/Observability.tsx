import { useRef } from "react";
import CodeWindow, { LiveDot } from "../components/CodeWindow";
import { Pillar } from "../components/PillarHeader";
import UsageBand from "../components/UsageBand";
import { useElement } from "../components/useElement";
import { OBSERVABILITY } from "../data/copy";
import { LIVE_RUN, TOOL_ROWS } from "../data/sample/observability";
import "./Observability.css";

const loadLog = () => import("@syn137/skyline-svelte-v5/elements/tool-log");

/** The tool-log ticker; it plays only while on screen and stops after about 20s (the element's own rule). */
function ToolLog() {
  const ref = useRef<HTMLDivElement>(null);
  const ready = useElement("sky-tool-log", loadLog, "near", ref);
  return (
    <div ref={ref} className="tool-log">
      {ready ? (
        <sky-tool-log rows={TOOL_ROWS} label={OBSERVABILITY.toolLogLabel} />
      ) : (
        <ol className="tool-log__fallback" aria-label={OBSERVABILITY.toolLogLabel}>
          {TOOL_ROWS.map((r, i) => (
            <li key={i}>
              <span className="tool-log__time">{r.time}</span>
              <span className="tool-log__tool">{r.tool}</span>
              <span className="tool-log__target">{r.target}</span>
              <span className="tool-log__duration">{r.duration}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Section 5, "03 Fully observable" (#observability): live cost, tokens by type, tool calls. */
export default function Observability() {
  return (
    <Pillar
      id="observability"
      label={OBSERVABILITY.eyebrow}
      tinted
      num={OBSERVABILITY.num}
      eyebrow={OBSERVABILITY.eyebrow}
      title={OBSERVABILITY.title}
      lede={OBSERVABILITY.lede}
      points={OBSERVABILITY.points}
      visual={
        <CodeWindow pad="roomy" glow>
          <span className="panel-meta">
            <LiveDot />
            {LIVE_RUN.meta}
          </span>
          <div className="observability__cost">
            <span className="observability__cost-value">{LIVE_RUN.cost}</span>
            <span className="observability__cost-detail">{LIVE_RUN.detail}</span>
          </div>
          <UsageBand tokens={LIVE_RUN.tokens} size="md" legend="compact" />
          <ToolLog />
        </CodeWindow>
      }
    />
  );
}
