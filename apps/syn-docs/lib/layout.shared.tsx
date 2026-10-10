import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { DocsNav, SITE_LINKS } from '@/components/DocsNav';
import { SMark, Wordmark } from '@/components/SMark';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      url: '/docs/guide/getting-started',
      title: (
        <span className="syn-brand">
          <SMark className="syn-brand__mark" title={null} />
          <Wordmark />
          <span className="syn-brand__tag">Docs</span>
        </span>
      ),
    },
    links: [
      // Header (lg and up): the landing page's capsule nav.
      { type: 'custom', on: 'nav', children: <DocsNav /> },
      // Sidebar menu (below lg): the same links as plain items.
      ...SITE_LINKS.map((link) => ({
        text: link.text,
        url: link.current ? '/docs' : link.url,
        on: 'menu' as const,
        external: !link.current,
        active: link.current ? ('nested-url' as const) : ('none' as const),
      })),
    ],
    githubUrl: 'https://github.com/syntropic137/syntropic137',
  };
}
