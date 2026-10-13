import { useRef, type CSSProperties } from "react";
import CodeWindow, { LiveDot, Tile } from "../components/CodeWindow";
import { Pillar } from "../components/PillarHeader";
import { useElement } from "../components/useElement";
import { ANY_HARNESS } from "../data/copy";
import { HARNESSES } from "../data/harnesses";
import { LANES_TITLE, LANE_FACTS, LANE_PHASES } from "../data/sample/anyHarness";
import "./Harnesses.css";

const loadLanes = () => import("@syn137/skyline-svelte-v5/elements/harness-lanes");

/** Lanes per harness in HARNESSES order: the fallback until <sky-harness-lanes> is defined. */
function LanesFallback() {
  return (
    <div className="harness-lanes__fallback" aria-label={ANY_HARNESS.lanesLabel} role="img">
      {HARNESSES.map((h) => (
        <div key={h.id} className="harness-lanes__lane">
          <span className="harness-lanes__name">
            <span className="harness-lanes__dot" style={{ background: h.color }} />
            {h.id}
          </span>
          <span className="harness-lanes__cells">
            {LANE_PHASES.map((p) => (
              <span
                key={p.name}
                className="harness-lanes__cell"
                data-on={p.provider === h.id || undefined}
                style={{ flexGrow: p.span ?? 1, "--lane": h.color } as CSSProperties}
              >
                {p.provider === h.id ? p.name : ""}
              </span>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Section 4, "02 Any harness" (#harnesses): one workflow, a lane per harness. */
export default function Harnesses() {
  const ref = useRef<HTMLDivElement>(null);
  const ready = useElement("sky-harness-lanes", loadLanes, "near", ref);
  return (
    <Pillar
      id="harnesses"
      label={ANY_HARNESS.eyebrow}
      reverse
      num={ANY_HARNESS.num}
      eyebrow={ANY_HARNESS.eyebrow}
      title={ANY_HARNESS.title}
      lede={ANY_HARNESS.lede}
      points={ANY_HARNESS.points}
      visual={
        <CodeWindow pad="roomy">
          <span className="panel-meta harness-lanes__meta">
            <span>{LANES_TITLE}</span>
            <LiveDot />
          </span>
          <div ref={ref} className="harness-lanes">
            {ready ? <sky-harness-lanes phases={LANE_PHASES} label={ANY_HARNESS.lanesLabel} /> : <LanesFallback />}
          </div>
          <div className="harness-lanes__facts">
            {LANE_FACTS.map((f) => (
              <Tile key={f.label} label={f.label}>
                <span className="harness-lanes__fact">{f.value}</span>
              </Tile>
            ))}
          </div>
        </CodeWindow>
      }
    />
  );
}
