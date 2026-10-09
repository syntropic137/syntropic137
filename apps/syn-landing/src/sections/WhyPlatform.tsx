import SectionHead from "./SectionHead";
import { WHY_PLATFORM_COPY } from "../data/copy";
import "./WhyPlatform.css";

const Check = () => (
  <svg className="why__check" width="14" height="14" viewBox="0 0 16 16" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3.5 8.5l3 3 6-7" />
  </svg>
);

/**
 * Why a platform: a real <table> (row headers, column headers kept for
 * screen readers). Phones stack each row (question, the by-hand way struck
 * through, the Syntropic137 way), as on the phone board; the explicit roles
 * keep the table semantics when CSS changes the display of its parts.
 */
export default function WhyPlatform() {
  const c = WHY_PLATFORM_COPY;
  return (
    <section className="p7-section why" data-ground="band" aria-labelledby="why-title">
      <div className="p7-section__inner why__inner">
        <div className="why__head">
          <SectionHead id="why-title" eyebrow={c.eyebrow} title={c.title} lede={c.lede} />
        </div>
        <table className="why__table" role="table">
          <caption className="p7-sr-only">{c.caption}</caption>
          <thead className="p7-sr-only" role="rowgroup">
            <tr role="row">
              <th scope="col" role="columnheader">{c.columns.question}</th>
              <th scope="col" role="columnheader">{c.columns.without}</th>
              <th scope="col" role="columnheader">{c.columns.with}</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {c.rows.map((row) => (
              <tr key={row.question} className="why__row" role="row">
                <th scope="row" role="rowheader" className="why__q">
                  {row.question}
                </th>
                <td role="cell" className="why__without">
                  {row.without}
                </td>
                <td role="cell" className="why__with">
                  <Check />
                  {row.with}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
