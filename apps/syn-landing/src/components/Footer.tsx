import SMark from "./SMark";
import Wordmark from "./Wordmark";
import { FOOTER_COLUMNS, FOOTER_TAGLINE, isExternal } from "../data/copy";

/** Site footer (Landing and PhoneLanding boards): brand and tagline, then three link columns (two per row on phones). */
export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__brand">
          <span className="site-footer__mark">
            <SMark size={22} label="" />
            <Wordmark />
          </span>
          <p className="site-footer__tagline">{FOOTER_TAGLINE}</p>
        </div>
        <div className="site-footer__columns">
          {FOOTER_COLUMNS.map((col) => (
            <nav key={col.title} className="site-footer__col" aria-label={col.title}>
              <h2 className="site-footer__title">{col.title}</h2>
              {col.links.map((link) => (
                <a
                  key={link.label}
                  href={link.href}
                  className="site-footer__link"
                  {...(isExternal(link.href) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                >
                  {link.label}
                </a>
              ))}
            </nav>
          ))}
        </div>
      </div>
    </footer>
  );
}
