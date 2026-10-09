import { useRef } from "react";
import { SectionIntro } from "../components/PillarHeader";
import CodeWindow from "../components/CodeWindow";
import { useElement } from "../components/useElement";
import { EVALS_COPY } from "../data/copy";
import { EVAL_SAMPLE } from "../data/sample/evals";
import "./Evals.css";

const ArrowRight = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 8h10M9 4l4 4-4 4" />
  </svg>
);

const loadExplorer = () => import("@syn137/skyline-svelte-v5/elements/eval-explorer");

/**
 * 04 Compounding improvement (#evals): the eval explorer on sample data in
 * window chrome (inside the board's 1px gradient frame), then the Capture /
 * Replay / Judge / Decide strip. <sky-eval-explorer> loads as the section
 * nears the viewport; until then the window keeps its height.
 */
export default function Evals() {
  const ref = useRef<HTMLElement>(null);
  const ready = useElement("sky-eval-explorer", loadExplorer, "near", ref);

  return (
    <section id="evals" ref={ref} className="page-section evals" aria-labelledby="evals-title">
      <div className="page-section__inner evals__inner">
        <div className="evals__head">
          <SectionIntro titleId="evals-title" eyebrow={EVALS_COPY.eyebrow} title={EVALS_COPY.title} lede={EVALS_COPY.lede} />
          <a className="evals__guide" href={EVALS_COPY.guide.href} target="_blank" rel="noopener noreferrer">
            {EVALS_COPY.guide.label} <ArrowRight />
          </a>
        </div>

        <div className="evals__frame">
          <CodeWindow title={EVALS_COPY.windowUrl} pad="roomy" className="evals__window">
            {ready ? (
              <sky-eval-explorer
                className="evals__explorer"
                verifiers={EVAL_SAMPLE.verifiers}
                passAt={EVAL_SAMPLE.passAt}
                judge={EVAL_SAMPLE.judge}
                span={EVAL_SAMPLE.span}
                costMax={EVAL_SAMPLE.costMax}
                ticks={EVAL_SAMPLE.ticks}
              />
            ) : (
              <div className="evals__placeholder" aria-hidden="true" />
            )}
          </CodeWindow>
        </div>

        <ol className="evals__loop" aria-label={EVALS_COPY.loopLabel}>
          {EVALS_COPY.loop.map((step, i) => (
            <li key={step.title} className="evals__step">
              <span className="evals__step-head">
                <span className="evals__step-num" aria-hidden="true">
                  {i + 1}
                </span>
                <h3 className="evals__step-title">{step.title}</h3>
              </span>
              <p className="evals__step-body">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
