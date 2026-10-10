/**
 * The landing page's site nav (v4 Landing board), shown in the docs header.
 * Same links and order as syntropic137.com; on the docs site, Docs is the
 * selected item.
 */

export const LANDING_URL = 'https://syntropic137.com';

export const SITE_LINKS: ReadonlyArray<{ text: string; url: string; current?: boolean }> = [
  { text: 'Workflows', url: `${LANDING_URL}/#workflows` },
  { text: 'Harnesses', url: `${LANDING_URL}/#harnesses` },
  { text: 'Observability', url: `${LANDING_URL}/#observability` },
  { text: 'Evals', url: `${LANDING_URL}/#evals` },
  { text: 'Docs', url: '/docs/guide/getting-started', current: true },
];

export function DocsNav() {
  return (
    <nav aria-label="Site" className="syn-site-nav">
      {SITE_LINKS.map((link) => (
        <a
          key={link.text}
          href={link.url}
          className="syn-site-nav__link"
          aria-current={link.current ? 'page' : undefined}
        >
          {link.text}
        </a>
      ))}
    </nav>
  );
}
