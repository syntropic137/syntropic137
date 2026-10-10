import { SectionIntro } from "../components/PillarHeader";
import { USE_CASES_COPY } from "../data/copy";
import "./UseCases.css";

/** What people build with it: six use-case cards, each with the event or entry point that starts it. */
export default function UseCases() {
  return (
    <section className="page-section use-cases" data-ground="band" aria-labelledby="use-cases-title">
      <div className="page-section__inner">
        <SectionIntro
          titleId="use-cases-title"
          eyebrow={USE_CASES_COPY.eyebrow}
          title={USE_CASES_COPY.title}
          lede={USE_CASES_COPY.lede}
          align="center-wide"
        />
        <ul className="use-cases__grid">
          {USE_CASES_COPY.cards.map((card) => (
            <li key={card.title} className="use-cases__card">
              <h3 className="use-cases__title">{card.title}</h3>
              <p className="use-cases__body">{card.body}</p>
              <span className="use-cases__trigger">{card.trigger}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
