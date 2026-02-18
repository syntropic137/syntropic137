import fs from 'node:fs';
import path from 'node:path';

export const revalidate = false;

function stripFrontmatter(content: string): string {
  const match = content.match(/^---\n[\s\S]*?\n---\n/);
  return match ? content.slice(match[0].length).trim() : content.trim();
}

function stripJSXComponents(content: string): string {
  // Remove self-closing JSX tags like <SystemArchitectureDiagram />
  return content.replace(/<[A-Z][A-Za-z]+ \/>/g, '').replace(/\n{3,}/g, '\n\n');
}

function getFrontmatter(content: string): { title?: string; description?: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const fm: Record<string, string> = {};
  for (const line of match[1].split('\n')) {
    const [key, ...rest] = line.split(':');
    if (key && rest.length) fm[key.trim()] = rest.join(':').trim();
  }
  return fm;
}

function collectMdxFiles(dir: string): { filepath: string; content: string }[] {
  const results: { filepath: string; content: string }[] = [];

  function walk(d: string) {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.mdx')) {
        results.push({ filepath: full, content: fs.readFileSync(full, 'utf-8') });
      }
    }
  }

  walk(dir);
  return results;
}

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

  // Sort: guide pages first, then api, then cli
  const order = ['index.mdx', 'guide/', 'api/', 'cli/'];
  files.sort((a, b) => {
    const relA = path.relative(contentDir, a.filepath);
    const relB = path.relative(contentDir, b.filepath);
    const idxA = order.findIndex((p) => relA === p || relA.startsWith(p));
    const idxB = order.findIndex((p) => relB === p || relB.startsWith(p));
    return (idxA === -1 ? 99 : idxA) - (idxB === -1 ? 99 : idxB);
  });

  for (const file of files) {
    const fm = getFrontmatter(file.content);
    const body = stripJSXComponents(stripFrontmatter(file.content));
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
