import { useEffect, useRef, useState } from "react";
import GitHubStars from "./GitHubStars";
import GitHubIcon from "./GitHubIcon";
import SMark from "./SMark";
import Wordmark from "./Wordmark";
import { GITHUB_URL, NAV_CTA, NAV_GITHUB_LABEL, NAV_LINKS, REPO, isExternal } from "../data/copy";

/** True once the page has scrolled past the top 24px (a sentinel leaves the viewport; no scroll listener). */
function useScrolled() {
  const sentinel = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(([e]) => setScrolled(!(e?.isIntersecting ?? true)));
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { sentinel, scrolled };
}

/**
 * Site header (Landing and PhoneLanding boards): the S and wordmark, the
 * capsule of section links, GitHub with its live star count, and the call to
 * action. Phones keep the S, the wordmark and the GitHub button.
 *
 * It floats (owner review): fixed at the top, over the hero as on the board
 * while the page is at the top, then a glass capsule once scrolled
 * (data-scrolled), so the links and the call to action stay in reach. Fixed
 * from the start and changed only by paint and transform: no layout shift.
 */
export default function Nav() {
  const { sentinel, scrolled } = useScrolled();
  return (
    <>
      <div ref={sentinel} className="site-header__sentinel" aria-hidden="true" />
      <header className="site-header" data-scrolled={scrolled ? "" : undefined}>
        <div className="site-header__bar">
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
            <a href={GITHUB_URL} className="site-header__github" target="_blank" rel="noopener noreferrer">
              <GitHubIcon />
              <span className="site-header__github-label">{NAV_GITHUB_LABEL}</span>
              <GitHubStars repo={REPO} />
            </a>
            <a href={NAV_CTA.href} className="site-header__cta">
              {NAV_CTA.label}
            </a>
          </div>
        </div>
      </header>
    </>
  );
}
