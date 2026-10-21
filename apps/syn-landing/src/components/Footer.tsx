import GitHubIcon from "./GitHubIcon";
import SMark from "./SMark";
import { XIcon, YouTubeIcon } from "./SocialIcons";
import Wordmark from "./Wordmark";
import { FOOTER_COLUMNS, FOOTER_TAGLINE, isExternal, type FooterLink } from "../data/copy";

const ICONS: Record<NonNullable<FooterLink["icon"]>, typeof XIcon> = {
  github: GitHubIcon,
  x: XIcon,
  youtube: YouTubeIcon,
};

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
              {col.links.map((link) => {
                const Icon = link.icon && ICONS[link.icon];
                return (
                  <a
                    key={link.label}
                    href={link.href}
                    className="site-footer__link"
                    data-social={Icon ? "" : undefined}
                    {...(isExternal(link.href) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                  >
                    {Icon && <Icon size={16} />}
                    {link.label}
                  </a>
                );
              })}
            </nav>
          ))}
        </div>
      </div>
    </footer>
  );
}
