import { DocsLayout } from 'fumadocs-ui/layouts/notebook';
import { baseOptions } from '@/lib/layout.shared';
import { source } from '@/lib/source';
import { HeadingCopyLinks } from '@/components/HeadingCopyLinks';
import type { ReactNode } from 'react';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout
      tree={source.pageTree}
      tabMode="navbar"
      nav={{ mode: 'top' }}
      {...baseOptions()}
    >
      <HeadingCopyLinks />
      {children}
    </DocsLayout>
  );
}
