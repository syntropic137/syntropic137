import path from 'node:path';
import { collectMdxFiles } from '@/lib/mdx-files';
import { stripFrontmatter, parseFrontmatter } from '@/lib/mdx-text';

export const revalidate = false;

const SECTION_ORDER = ['index.mdx', 'guide/', 'api/', 'cli/'];

function sectionSortKey(relPath: string): number {
  const idx = SECTION_ORDER.findIndex((p) => relPath === p || relPath.startsWith(p));
  return idx === -1 ? 99 : idx;
}

function renderFileSection(content: string, relPath: string): string[] {
  const fm = parseFrontmatter(content);
  const body = stripFrontmatter(content);
  if (!body) return [];

  const lines: string[] = [`## ${fm.title || relPath}`];
  if (fm.description) lines.push(`> ${fm.description}`);
  lines.push('', body, '', '---', '');
  return lines;
}

export function GET() {
  const contentDir = path.join(process.cwd(), 'content/docs');
  const files = collectMdxFiles(contentDir);

  files.sort((a, b) => {
    const relA = path.relative(contentDir, a.filepath);
    const relB = path.relative(contentDir, b.filepath);
    return sectionSortKey(relA) - sectionSortKey(relB);
  });

  const sections: string[] = [
    '# Syntropic137 — Complete Documentation',
    '',
    '> Agentic Engineering platform. Orchestrate AI agents with event-sourced workflows.',
    '',
    '---',
    '',
  ];

  for (const file of files) {
    const rel = path.relative(contentDir, file.filepath);
    sections.push(...renderFileSection(file.content, rel));
  }

  return new Response(sections.join('\n'), {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
