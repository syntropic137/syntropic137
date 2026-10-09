import SectionHead from "./SectionHead";
import { USE_CASES_COPY } from "../data/copy";
import "./UseCases.css";

/** What people build with it: six use-case cards, each with the event or entry point that starts it. */
export default function UseCases() {
  return (
    <section className="p7-section use-cases" data-ground="band" aria-labelledby="use-cases-title">
      <div className="p7-section__inner">
        <SectionHead
          id="use-cases-title"
          eyebrow={USE_CASES_COPY.eyebrow}
          title={USE_CASES_COPY.title}
          lede={USE_CASES_COPY.lede}
          align="center"
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
