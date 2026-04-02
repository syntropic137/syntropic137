'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const tabs = [
  { label: 'Documentation', href: '/docs/guide' },
  { label: 'API Reference', href: '/docs/api' },
  { label: 'CLI Reference', href: '/docs/cli' },
];

export function DocsNav() {
  const pathname = usePathname();

  return (
    <nav className="flex gap-6 border-b border-fd-border px-2 -mx-4 md:-mx-6 xl:-mx-8 md:px-6 xl:px-8 mb-6">
      {tabs.map((tab) => {
        const active = pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`pb-2 pt-3 text-sm font-medium border-b-2 transition-colors ${
              active
                ? 'border-fd-primary text-fd-primary'
                : 'border-transparent text-fd-muted-foreground hover:text-fd-foreground'
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
