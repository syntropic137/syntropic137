import "./SectionHead.css";

/**
 * P7-local section header (eyebrow, display title, lede), as on the v4
 * boards. P6 owns the shared PillarHeader (src/components/PillarHeader.tsx);
 * this copy exists only until the two branches merge, then it folds into
 * that one.
 */
export interface SectionHeadProps {
  id: string;
  eyebrow?: string;
  title: string;
  lede?: string;
  align?: "start" | "center";
  /** "closing" is the larger headline of the call to action. */
  size?: "section" | "closing";
}

export default function SectionHead({ id, eyebrow, title, lede, align = "start", size = "section" }: SectionHeadProps) {
  return (
    <div className="p7-head" data-align={align}>
      {eyebrow ? <p className="p7-head__eyebrow">{eyebrow}</p> : null}
      <h2 id={id} className="p7-head__title" data-size={size}>
        {title}
      </h2>
      {lede ? <p className="p7-head__lede">{lede}</p> : null}
    </div>
  );
}
