import { useEffect, useRef, useState } from "react";
import SectionHead from "./SectionHead";
import { useNearViewport } from "./useNearViewport";
import { EVALS_COPY } from "../data/copy";
import { EVAL_SAMPLE } from "../data/sample/evals";
import "./Evals.css";

const ArrowRight = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 8h10M9 4l4 4-4 4" />
  </svg>
);

/**
 * P7-local window chrome (three dots and an address), as on the board. P6
 * owns the shared CodeWindow (src/components/CodeWindow.tsx); fold this into
 * it at merge.
 */
function EvalWindow({ url, children }: { url: string; children: React.ReactNode }) {
  return (
    <div className="eval-window">
      <div className="eval-window__frame">
        <div className="eval-window__bar">
          <span className="eval-window__dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="eval-window__url">{url}</span>
        </div>
        <div className="eval-window__body">{children}</div>
      </div>
    </div>
  );
}

/**
 * 04 Compounding improvement (#evals): the eval explorer on sample data in
 * window chrome, then the Capture / Replay / Judge / Decide strip. The
 * <sky-eval-explorer> element loads when the section nears the viewport;
 * until then the window keeps its height so nothing shifts.
 */
export default function Evals() {
  const ref = useRef<HTMLElement>(null);
  const near = useNearViewport(ref);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!near) return;
    let live = true;
    import("@syn137/skyline-svelte-v5/elements/eval-explorer").then(() => {
      if (live) setReady(true);
    });
    return () => {
      live = false;
    };
  }, [near]);

  return (
    <section id="evals" ref={ref} className="p7-section evals" aria-labelledby="evals-title">
      <div className="p7-section__inner evals__inner">
        <div className="evals__head">
          <SectionHead id="evals-title" eyebrow={EVALS_COPY.eyebrow} title={EVALS_COPY.title} lede={EVALS_COPY.lede} />
          <a className="evals__guide" href={EVALS_COPY.guide.href} target="_blank" rel="noopener noreferrer">
            {EVALS_COPY.guide.label} <ArrowRight />
          </a>
        </div>

        <EvalWindow url={EVALS_COPY.windowUrl}>
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
        </EvalWindow>

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
