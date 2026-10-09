import type { ReactNode } from "react";
import "./PillarHeader.css";

export interface PillarPoint {
  title: string;
  body: string;
}

interface SectionIntroProps {
  eyebrow: string;
  title: string;
  lede: string;
  /** Centred on every width ("What is Syntropic137?"), or start-aligned (pillars). */
  align?: "center" | "start";
  /** id for the h2, so the section can be labelled by it. */
  titleId?: string;
}

/** Eyebrow, gradient display title and lede: the head of every section on the v4 boards. */
export function SectionIntro({ eyebrow, title, lede, align = "start", titleId }: SectionIntroProps) {
  return (
    <div className="section-intro" data-align={align}>
      <span className="section-intro__eyebrow">{eyebrow}</span>
      <h2 id={titleId} className="section-intro__title glow-text">
        {title}
      </h2>
      <p className="section-intro__lede">{lede}</p>
    </div>
  );
}

interface PillarHeaderProps extends Omit<SectionIntroProps, "align"> {
  /** "01" to "04", set in the wordmark face with a short rule. */
  num: string;
  points: readonly PillarPoint[];
}

/** A pillar's text column: number, intro and a checked list of points. */
export default function PillarHeader({ num, points, ...intro }: PillarHeaderProps) {
  return (
    <div className="pillar-header">
      <span className="pillar-header__num" aria-hidden="true">
        {num}
        <span className="pillar-header__rule" />
      </span>
      <SectionIntro {...intro} />
      <ul className="pillar-header__points">
        {points.map((p) => (
          <li key={p.title}>
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path d="M3.5 8.5l3 3 6-7" />
            </svg>
            <span>
              <strong>{p.title}</strong>
              <span>{p.body}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface PillarProps extends PillarHeaderProps {
  /** Section anchor the nav links to (#workflows, #harnesses, #observability, #evals). */
  id: string;
  /** Section label for assistive tech (the board's aria-label). */
  label: string;
  visual: ReactNode;
  /** Visual on the left from 64rem (02 Any harness); the text always comes first on phones. */
  reverse?: boolean;
  /** The accent wash on the right (01 and 03). */
  tinted?: boolean;
}

/** A pillar section: text column (440px) beside its visual, stacked on phones. */
export function Pillar({ id, label, visual, reverse = false, tinted = false, ...header }: PillarProps) {
  return (
    <section id={id} aria-label={label} className="pillar" data-tinted={tinted || undefined}>
      <div className="pillar__inner" data-reverse={reverse || undefined}>
        <PillarHeader {...header} />
        <div className="pillar__visual">{visual}</div>
      </div>
    </section>
  );
}
