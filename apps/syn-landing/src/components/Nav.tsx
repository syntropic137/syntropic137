import GitHubStars from "./GitHubStars";
import GitHubIcon from "./GitHubIcon";
import SMark from "./SMark";
import Wordmark from "./Wordmark";
import { GITHUB_URL, NAV_CTA, NAV_GITHUB_LABEL, NAV_LINKS, REPO, isExternal } from "../data/copy";

/**
 * Site header (Landing and PhoneLanding boards): the S and wordmark, the
 * capsule of section links, GitHub with its live star count, and the call to
 * action. It sits over the top of the hero, whose ground runs behind it.
 * Phones keep the S, the wordmark and the GitHub button.
 */
export default function Nav() {
  return (
    <header className="site-header">
      <a href="/" className="site-header__brand" aria-label="Syntropic137 home">
        <SMark size={26} label="" />
        <Wordmark />
      </a>
      <nav aria-label="Site" className="site-nav">
        {NAV_LINKS.map((link) => (
          <a
            key={link.label}
            href={link.href}
            className="site-nav__link"
            {...(isExternal(link.href) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          >
            {link.label}
          </a>
        ))}
      </nav>
      <div className="site-header__actions">
        <a
          href={GITHUB_URL}
          className="site-header__github"
          target="_blank"
          rel="noopener noreferrer"
        >
          <GitHubIcon />
          <span className="site-header__github-label">{NAV_GITHUB_LABEL}</span>
          <GitHubStars repo={REPO} />
        </a>
        <a href={NAV_CTA.href} className="site-header__cta">
          {NAV_CTA.label}
        </a>
      </div>
    </header>
  );
}
