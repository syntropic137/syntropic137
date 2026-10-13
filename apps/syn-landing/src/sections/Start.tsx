import { SectionIntro } from "../components/PillarHeader";
import InstallTerminal from "../components/InstallTerminal";
import SMark from "../components/SMark";
import { START_COPY } from "../data/copy";
import "./Start.css";

/**
 * Closing call to action (#start): the headline, the copy-command box, the
 * three steps, and the S over the outlined wordmark at the foot.
 */
export default function Start() {
  const c = START_COPY;
  return (
    <section id="start" className="page-section start" aria-labelledby="start-title">
      <div className="start__inner">
        <div className="start__main">
          <SectionIntro titleId="start-title" title={c.title} lede={c.lede} size="closing" />
          <div className="start__install">
            <InstallTerminal caret />
            <p className="start__note">{c.note}</p>
          </div>
        </div>
        <ol className="start__steps" aria-label={c.stepsLabel}>
          {c.steps.map((step, i) => (
            <li key={step.label} className="start__step">
              <span className="start__num" aria-hidden="true">
                {i + 1}
              </span>
              <span className="start__label">{step.label}</span>
              <code className="start__code">{step.code}</code>
            </li>
          ))}
        </ol>
      </div>
      <div className="start__brand" aria-hidden="true">
        {/* Two fixed sizes: SMark takes a pixel width, and the phone board uses 54px, the desktop 150px. */}
        <span className="start__mark" data-size="phone">
          <SMark size={54} label="" />
        </span>
        <span className="start__mark" data-size="desktop">
          <SMark size={150} label="" />
        </span>
        <span className="start__wordmark">{c.wordmark}</span>
      </div>
    </section>
  );
}
