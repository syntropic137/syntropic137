import type { ReactElement } from 'react';
import Link from 'next/link';
import packageJson from '../package.json';
import { SMark, Wordmark } from './SMark';
import { GitHubIcon, XIcon, YouTubeIcon } from './SocialIcons';

const LAST_UPDATED = 'March 2026';
const REPO = 'https://github.com/syntropic137/syntropic137';

/** Footer columns from the v4 Landing board, pointed at the docs. */
const COLUMNS: ReadonlyArray<{ title: string; links: ReadonlyArray<{ text: string; href: string; icon?: () => ReactElement }> }> = [
  {
    title: 'Product',
    links: [
      { text: 'Docs', href: '/docs/guide/getting-started' },
      { text: 'CLI reference', href: '/docs/cli' },
      { text: 'API reference', href: '/docs/api' },
      { text: 'Docs for agents', href: '/llms' },
    ],
  },
  {
    title: 'Guides',
    links: [
      { text: 'Getting started', href: '/docs/guide/getting-started' },
      { text: 'Workflows', href: '/docs/guide/workflows' },
      { text: 'Evals', href: '/docs/guide/evals' },
      { text: 'Self-hosting', href: '/docs/guide/self-hosting' },
    ],
  },
  {
    title: 'Community',
    links: [
      { text: 'GitHub', href: REPO, icon: GitHubIcon },
      { text: 'X', href: 'https://x.com/syntropic137', icon: XIcon },
      { text: 'YouTube', href: 'https://www.youtube.com/@Syntropic137', icon: YouTubeIcon },
      { text: 'Changelog', href: `${REPO}/blob/main/CHANGELOG.md` },
      { text: 'Security', href: `${REPO}/blob/main/SECURITY.md` },
    ],
  },
];

export function DocsFooter() {
  return (
    <footer className="syn-footer not-prose">
      <div className="syn-footer__brand">
        <span className="syn-brand">
          <SMark className="syn-footer__mark" title={null} />
          <Wordmark />
        </span>
        <p className="syn-footer__tagline">The agentic engineering platform. MIT licensed.</p>
        <p className="syn-footer__meta">
          <a className="syn-footer__link" href={`${REPO}/releases/tag/v${packageJson.version}`}>Docs v{packageJson.version}</a>
          <span aria-hidden="true"> · </span>
          Last updated {LAST_UPDATED}
        </p>
      </div>
      <div className="syn-footer__cols">
        {COLUMNS.map((col) => (
          <div key={col.title} className="syn-footer__col">
            <span className="syn-footer__heading">{col.title}</span>
            {col.links.map((link) =>
              link.href.startsWith('/') ? (
                <Link key={link.text} href={link.href} className="syn-footer__link">
                  {link.text}
                </Link>
              ) : (
                <a
                  key={link.text}
                  href={link.href}
                  className="syn-footer__link"
                  data-social={link.icon ? '' : undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {link.icon && <link.icon />}
                  {link.text}
                </a>
              ),
            )}
          </div>
        ))}
      </div>
    </footer>
  );
}
