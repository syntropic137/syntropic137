import { useEffect, type ComponentType } from "react";
import { ArrowRight, ArrowUpRight, BookOpen, Globe, Lightbulb, Mail, MessagesSquare } from "lucide-react";
import GitHubIcon from "../components/GitHubIcon";
import InstallTerminal from "../components/InstallTerminal";
import SMark from "../components/SMark";
import Wordmark from "../components/Wordmark";
import { BIO_LINKS, LINKS_PAGE, type BioLink, type LinkId } from "../data/copy/links";
import "./Links.css";

function XIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

const ICONS: Record<LinkId, ComponentType<{ size?: number }>> = {
  website: Globe,
  github: GitHubIcon,
  docs: BookOpen,
  canny: Lightbulb,
  discussions: MessagesSquare,
  x: XIcon,
  email: Mail,
};

/** mailto stays in place; every other link opens in a new tab and says so. */
const opensTab = (href: string) => !href.startsWith("mailto:");

function LinkRow({ link }: { link: BioLink }) {
  const Icon = ICONS[link.id];
  const tab = opensTab(link.href);
  const Trail = tab ? ArrowUpRight : ArrowRight;
  return (
    <a
      href={link.href}
      className="bio-link"
      data-tier={link.tier}
      data-link-id={link.id}
      {...(tab ? { target: "_blank", rel: "noopener noreferrer" } : {})}
    >
      <span className="bio-link__icon" aria-hidden="true">
        <Icon size={link.tier === "secondary" ? 18 : 20} />
      </span>
      <span className="bio-link__text">
        <span className="bio-link__title">{link.title}</span>{" "}
        <span className="bio-link__desc">{link.desc}</span>
        {tab && <span className="sr-only"> {LINKS_PAGE.newTab}</span>}
      </span>
      <Trail className="bio-link__trail" size={18} aria-hidden="true" />
    </a>
  );
}

/**
 * /links, the link in bio (most visits come from X on a phone): the S and
 * wordmark, the tagline, the install box, then the links by priority. The
 * website is the featured card, GitHub and the docs full cards, the rest one
 * grouped list. No motion of its own beyond hover and press feedback.
 */
export default function Links() {
  useEffect(() => {
    document.title = LINKS_PAGE.documentTitle;
  }, []);

  const cards = BIO_LINKS.filter((l) => l.tier !== "secondary");
  const rest = BIO_LINKS.filter((l) => l.tier === "secondary");

  return (
    <div className="links-page">
      <div className="links-page__grain" aria-hidden="true" />
      <div className="links-page__col">
        <header className="links-head">
          <SMark size={58} label="" />
          <h1 className="links-head__title">
            <Wordmark />
          </h1>
          <p className="links-head__tagline">{LINKS_PAGE.tagline}</p>
        </header>

        <main className="links-main">
          <div className="links-install">
            <InstallTerminal caret />
            <p className="links-install__note">{LINKS_PAGE.installNote}</p>
          </div>

          <nav aria-label={LINKS_PAGE.listLabel} className="links-nav">
            <ul className="links-cards">
              {cards.map((link) => (
                <li key={link.id}>
                  <LinkRow link={link} />
                </li>
              ))}
            </ul>
            <ul className="links-group">
              {rest.map((link) => (
                <li key={link.id}>
                  <LinkRow link={link} />
                </li>
              ))}
            </ul>
          </nav>
        </main>

        <footer className="links-foot">{LINKS_PAGE.footer}</footer>
      </div>
    </div>
  );
}
