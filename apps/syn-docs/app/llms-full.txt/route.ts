import path from 'node:path';
import { collectMdxFiles } from '@/lib/mdx-files';
import { stripFrontmatter, stripJSX, parseFrontmatter } from '@/lib/mdx-text';

export const revalidate = false;

export function GET() {
  const contentDir = path.join(process.cwd(), 'content/docs');
  const files = collectMdxFiles(contentDir);
  const sections: string[] = [];

  sections.push('# Syntropic137 — Complete Documentation');
  sections.push('');
  sections.push('> Agentic Engineering platform. Orchestrate AI agents with event-sourced workflows.');
  sections.push('');
  sections.push('---');
  sections.push('');

  const order = ['index.mdx', 'guide/', 'api/', 'cli/'];
  files.sort((a, b) => {
    const relA = path.relative(contentDir, a.filepath);
    const relB = path.relative(contentDir, b.filepath);
    const idxA = order.findIndex((p) => relA === p || relA.startsWith(p));
    const idxB = order.findIndex((p) => relB === p || relB.startsWith(p));
    return (idxA === -1 ? 99 : idxA) - (idxB === -1 ? 99 : idxB);
  });

  for (const file of files) {
    const fm = parseFrontmatter(file.content);
    const body = stripJSX(stripFrontmatter(file.content));
    const rel = path.relative(contentDir, file.filepath);

    if (!body) continue;

    sections.push(`## ${fm.title || rel}`);
    if (fm.description) sections.push(`> ${fm.description}`);
    sections.push('');
    sections.push(body);
    sections.push('');
    sections.push('---');
    sections.push('');
  }

  return new Response(sections.join('\n'), {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
